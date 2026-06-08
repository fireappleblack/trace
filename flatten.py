#!/usr/bin/env python3
# flatten:begin
# repo-path: flatten.py
# generated: 2026-06-08T22:02:12Z by flatten.py — do not edit this block
# flatten:end

"""
flatten.py — keep a repo's "flattened/" upload set in sync with the real tree.

Purpose
-------
Claude Projects store every uploaded file in one flat folder, so a repo's nested
files have to be renamed to avoid collisions. This script:

  1. Walks a repo.
  2. For each file that should be uploaded, writes (or refreshes) a small,
     datetime-stamped comment block at the head of THAT SAME source file,
     recording its path relative to the repo root. The block is idempotent:
     an UNCHANGED file is left byte-for-byte alone. But if the file's content
     has changed since it was last flattened, the block's `generated:` stamp is
     refreshed to the current run time, so the stamp tracks last-change rather
     than only first-injection. ("Changed" = the body, with the block itself
     ignored, differs from the mirrored copy under flattened/.)
  3. Mirrors the file into "<repo>/flattened/" under a collision-free flattened
     name (repo prefix + per-directory prefixes + original filename), copying
     only when the destination is missing or differs.

Inclusion / exclusion
----------------------
  • git decides most of it: anything `git check-ignore` reports as ignored is
    skipped silently (secrets, caches, build junk, etc.).
  • The path-comment block doubles as the "this file is included" marker: a file
    that already carries a correct block is treated as included and never
    re-prompts.
  • A brand-new, non-ignored file with no block is a candidate: you're prompted
    once (Y/n). "n" records it in the [flattenignore] list in flatten.cfg so it
    is never prompted again.
  • Directories get a short prefix token the first time a file inside them is
    included; you're prompted for the token (or it's auto-slugged with -y).

There is deliberately NO .dockerignore support: there is no CLI equivalent to
`git check-ignore`, its pattern syntax differs from gitignore, and conceptually
it excludes files (docs, deploy scripts) that you DO want in the Project.

Config lives in "<repo>/flattened/flatten.cfg".

Usage
-----
  flatten.py [REPO_ROOT] [options]

  REPO_ROOT            repo to process (default: cwd, or its git top-level)
  --output-dir NAME    flattened dir name (default: flattened)
  --repo-name NAME     repo name to record on first init
  --repo-prefix PFX    repo prefix token on first init (e.g. zg, zgt)
  -y, --yes            non-interactive: auto-include, auto-slug folder tokens
  -n, --dry-run        report what would change; write nothing
      --check          like --dry-run but exits 1 if anything is out of sync
                       (use in a pre-commit hook / CI to catch drift)
      --prune          delete flattened/ files that no longer map to a source
  -v, --verbose        show per-file detail (incl. skipped/ignored)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys
from pathlib import Path

# ───────────────────────────── comment styles ──────────────────────────────
# Each style is either a line-prefix string (e.g. "# ") or a (open, close) pair
# for block comments. "none" means the format cannot carry a comment.

LINE = "line"
BLOCK = "block"
NONE = "none"

STYLES = {
    "hash":       (LINE,  "#"),
    "dashdash":   (LINE,  "--"),
    "slashslash": (LINE,  "//"),
    "html":       (BLOCK, ("<!--", "-->")),
    "css":        (BLOCK, ("/*", "*/")),
    "none":       (NONE,  None),
}

# Map by extension (lowercase, with dot) or exact filename.
EXT_STYLE = {
    ".py": "hash", ".sh": "hash", ".bash": "hash", ".zsh": "hash",
    ".yaml": "hash", ".yml": "hash", ".toml": "hash", ".ini": "hash",
    ".cfg": "hash", ".conf": "hash", ".env": "hash", ".txt": "hash",
    ".properties": "hash", ".r": "hash",
    ".sql": "dashdash",
    ".js": "slashslash", ".mjs": "slashslash", ".cjs": "slashslash",
    ".ts": "slashslash", ".jsx": "slashslash", ".tsx": "slashslash",
    ".go": "slashslash", ".rs": "slashslash", ".java": "slashslash",
    ".c": "slashslash", ".h": "slashslash", ".cpp": "slashslash",
    ".html": "html", ".htm": "html", ".xml": "html", ".svg": "html",
    ".md": "html", ".markdown": "html", ".vue": "html",
    ".css": "css", ".scss": "css", ".less": "css",
    ".json": "none",
}
NAME_STYLE = {
    "Containerfile": "hash", "Dockerfile": "hash", "Makefile": "hash",
    ".gitignore": "hash", ".dockerignore": "hash", ".gitattributes": "hash",
    "requirements.txt": "hash", ".editorconfig": "hash",
}

MARKER = "flatten"            # appears in "flatten:begin" / "flatten:end"
SCAN_LINES = 40              # how far into the head we look for an existing block
TOOL = "flatten.py"


def style_for(path: Path) -> str:
    """Pick a comment style key for a file, by exact name then extension."""
    if path.name in NAME_STYLE:
        return NAME_STYLE[path.name]
    # An env file can be named like ".secrets.env" or "foo.env.example".
    if path.name.endswith(".env") or ".env." in path.name:
        return "hash"
    return EXT_STYLE.get(path.suffix.lower(), "none")


# ───────────────────────── block rendering / parsing ───────────────────────

def render_block(style_key: str, relpath: str, when: str) -> list[str]:
    """Return the comment block as a list of lines (no trailing newlines)."""
    kind, spec = STYLES[style_key]
    gen = f"generated: {when} by {TOOL} \u2014 do not edit this block"
    if kind == LINE:
        p = spec + " "
        return [
            f"{p}{MARKER}:begin",
            f"{p}repo-path: {relpath}",
            f"{p}{gen}",
            f"{p}{MARKER}:end",
        ]
    if kind == BLOCK:
        open_, close = spec
        return [
            f"{open_} {MARKER}:begin",
            f"     repo-path: {relpath}",
            f"     {gen}",
            f"{MARKER}:end {close}",
        ]
    raise ValueError(f"cannot render a block for style {style_key!r}")


def find_block(lines: list[str]) -> tuple[int, int, str] | None:
    """Locate an existing flatten block in the head.

    Returns (start_idx, end_idx_inclusive, recorded_path) or None.
    """
    begin = None
    horizon = min(len(lines), SCAN_LINES)
    for i in range(horizon):
        if f"{MARKER}:begin" in lines[i]:
            begin = i
            break
    if begin is None:
        return None
    end = None
    for j in range(begin, min(len(lines), begin + 8)):
        if f"{MARKER}:end" in lines[j]:
            end = j
            break
    if end is None:
        return None
    recorded = ""
    for k in range(begin, end + 1):
        m = re.search(r"repo-path:\s*(.+?)\s*$", lines[k])
        if m:
            recorded = m.group(1)
            break
    return (begin, end, recorded)


def block_stripped(lines: list[str]) -> list[str]:
    """Return the lines with the flatten block (and one trailing blank line)
    removed, so two versions of a file can be compared on body alone —
    independent of the block's timestamp."""
    blk = find_block(lines)
    if not blk:
        return lines
    b0, b1, _ = blk
    after = b1 + 1
    if after < len(lines) and lines[after].strip() == "":
        after += 1
    return lines[:b0] + lines[after:]


# ───────────────────────────── preamble handling ───────────────────────────
# Some lines MUST stay first (shebang, doctype, XML decl, coding cookie, YAML/MD
# front-matter). The block is inserted immediately after them.

_CODING_RE = re.compile(r"coding[:=]\s*[-\w.]+")


def split_preamble(lines: list[str], style_key: str, path: Path) -> int:
    """Return the index at which the block should be inserted (after preamble)."""
    i = 0
    n = len(lines)

    # Shebang.
    if i < n and lines[i].startswith("#!"):
        i += 1
        # A python coding cookie may sit on line 2.
        if path.suffix.lower() == ".py" and i < n and _CODING_RE.search(lines[i]):
            i += 1
        return i

    # Python coding cookie on line 1.
    if path.suffix.lower() == ".py" and i < n and _CODING_RE.search(lines[i]):
        return i + 1

    # HTML / XML must-be-first lines.
    if style_key == "html" and i < n:
        head = lines[i].lstrip().lower()
        if head.startswith("<?xml") or head.startswith("<!doctype"):
            return i + 1

    # YAML / Markdown front-matter fenced by --- ... ---
    if path.suffix.lower() in (".md", ".markdown", ".yaml", ".yml") and i < n:
        if lines[i].strip() == "---":
            for j in range(i + 1, min(n, 60)):
                if lines[j].strip() in ("---", "..."):
                    return j + 1
    return i


# ───────────────────────────── file IO helpers ─────────────────────────────

def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def read_text(path: Path):
    """Return (text, eol, had_trailing_nl, bom) or None if binary/undecodable."""
    data = path.read_bytes()
    if is_binary(data):
        return None
    bom = ""
    if data.startswith(b"\xef\xbb\xbf"):
        bom = "\ufeff"
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    eol = "\r\n" if "\r\n" in text else "\n"
    had_nl = text.endswith("\n")
    text = text.replace("\r\n", "\n")
    return (text, eol, had_nl, bom)


def write_text(path: Path, lines: list[str], eol: str, had_nl: bool, bom: str):
    body = eol.join(lines)
    if had_nl:
        body += eol
    path.write_bytes((bom + body).encode("utf-8"))


def body_changed(src: Path, dest: Path) -> bool:
    """True if src's body (ignoring its flatten block) differs from the already-
    flattened copy at dest — i.e. the content changed since the last flatten.
    A missing dest counts as changed (nothing to compare against yet)."""
    if not dest.exists():
        return True
    s = read_text(src)
    d = read_text(dest)
    if s is None or d is None:
        # Binary / undecodable: fall back to a raw byte comparison.
        try:
            return src.read_bytes() != dest.read_bytes()
        except OSError:
            return True
    s_body = block_stripped(s[0].split("\n"))
    d_body = block_stripped(d[0].split("\n"))
    return s_body != d_body


# ───────────────────────────── comment injection ───────────────────────────

def ensure_comment(path: Path, relpath: str, when: str, dry_run: bool,
                   restamp: bool = False) -> str:
    """Ensure the file head carries a correct flatten block.

    When a correct block already exists, the timestamp is preserved UNLESS
    `restamp` is True (the caller has determined the body changed since the last
    flatten), in which case only the `generated:` stamp is refreshed.

    Returns one of: 'unchanged', 'restamped', 'inserted', 'updated',
    'nocomment', 'binary'.
    """
    style_key = style_for(path)
    if style_key == "none":
        # Cannot carry a comment (JSON, unknown text). Flag, don't touch.
        return "nocomment"

    rt = read_text(path)
    if rt is None:
        return "binary"
    text, eol, had_nl, bom = rt
    lines = text.split("\n")
    if had_nl and lines and lines[-1] == "":
        lines = lines[:-1]  # drop the artefact empty element from a trailing \n

    existing = find_block(lines)
    if existing:
        b0, b1, recorded = existing
        if recorded == relpath:
            if not restamp:
                return "unchanged"
            # Body changed since last flatten — refresh ONLY the timestamp,
            # leaving the rest of the file byte-for-byte.
            new_block = render_block(style_key, relpath, when)
            new_lines = lines[:b0] + new_block + lines[b1 + 1:]
            if not dry_run:
                write_text(path, new_lines, eol, had_nl if had_nl else True, bom)
            return "restamped"
        # Path is wrong (file moved): strip old block + one trailing blank.
        after = b1 + 1
        if after < len(lines) and lines[after].strip() == "":
            after += 1
        lines = lines[:b0] + lines[after:]
        action = "updated"
    else:
        action = "inserted"

    ins = split_preamble(lines, style_key, path)
    pre, rest = lines[:ins], lines[ins:]
    while rest and rest[0].strip() == "":
        rest.pop(0)
    block = render_block(style_key, relpath, when)
    new_lines = pre + block + ([""] + rest if rest else [])

    if not dry_run:
        write_text(path, new_lines, eol, had_nl if had_nl else True, bom)
    return action


# ───────────────────────────────── config ──────────────────────────────────
# flatten.cfg is a tiny, hand-editable, line-based format:
#
#   [repo]
#   name = zip-game
#   prefix = zg
#
#   [folders]            # full relative dir -> cumulative prefix
#   . ->
#   platform -> pl
#   platform/mariadb -> pl-mdb
#
#   [flattenignore]      # one relative path per line; files OR folders
#   notes/private.md

class Config:
    def __init__(self):
        self.repo_name = ""
        self.repo_prefix = ""
        self.folders: dict[str, str] = {".": ""}
        self.ignore: list[str] = []

    @classmethod
    def load(cls, path: Path) -> "Config":
        c = cls()
        if not path.exists():
            return c
        section = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue
            if section == "repo":
                if "=" in line:
                    k, v = (s.strip() for s in line.split("=", 1))
                    if k == "name":
                        c.repo_name = v
                    elif k == "prefix":
                        c.repo_prefix = v
            elif section == "folders":
                if "->" in line:
                    k, v = (s.strip() for s in line.split("->", 1))
                    c.folders[k] = v
            elif section == "flattenignore":
                c.ignore.append(line)
        c.folders.setdefault(".", "")
        return c

    def save(self, path: Path):
        out = [
            "# flatten.cfg \u2014 generated and maintained by flatten.py.",
            "# Hand-editable; keys are stable. Lines beginning with # are ignored.",
            "",
            "[repo]",
            f"name = {self.repo_name}",
            f"prefix = {self.repo_prefix}",
            "",
            "# Full relative directory -> its cumulative flattened prefix.",
            "[folders]",
        ]
        for k in sorted(self.folders):
            out.append(f"{k} -> {self.folders[k]}")
        out += [
            "",
            "# Files or folders you chose NOT to upload. Remove a line to reconsider.",
            "[flattenignore]",
        ]
        out += sorted(set(self.ignore))
        out.append("")
        path.write_text("\n".join(out), encoding="utf-8")

    def is_ignored(self, rel: str) -> bool:
        for e in self.ignore:
            if rel == e or rel.startswith(e.rstrip("/") + "/"):
                return True
        return False


# ───────────────────────────────── git ─────────────────────────────────────

def git_ignored_set(repo: Path, rel_paths: list[str]) -> set[str]:
    """Return the subset of rel_paths that git considers ignored.

    Empty set if this isn't a git work-tree or git is unavailable.
    """
    try:
        chk = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        )
        if chk.returncode != 0 or chk.stdout.strip() != "true":
            return set()
    except FileNotFoundError:
        return set()
    if not rel_paths:
        return set()
    stdin = "\0".join(rel_paths)
    proc = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-z", "--stdin"],
        input=stdin, capture_output=True, text=True,
    )
    # check-ignore exits 0 (some ignored), 1 (none), 128 (error). 0/1 are fine.
    if proc.returncode not in (0, 1):
        return set()
    return {p for p in proc.stdout.split("\0") if p}


# ───────────────────────────── name flattening ─────────────────────────────

def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "", name).lower()
    return s or "x"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def ensure_dir_prefix(reldir: str, cfg: Config, args) -> str | None:
    """Return the cumulative prefix for a directory, prompting/auto-slugging as
    needed. Returns None if the directory (or an ancestor) is skipped/ignored."""
    if reldir in (".", ""):
        return ""
    if cfg.is_ignored(reldir):
        return None
    parts = reldir.split("/")
    acc = ""
    cur = ""
    for seg in parts:
        cur = seg if cur == "" else f"{cur}/{seg}"
        if cfg.is_ignored(cur):
            return None
        if cur in cfg.folders:
            acc = cfg.folders[cur]
            continue
        # New directory: need a token for this segment.
        default_tok = slug(seg)
        if args.yes or args.check or args.dry_run:
            token = default_tok
        else:
            # Enter accepts the suggested token; '-' (or 'skip') skips the
            # whole folder. A blank answer can't reach us as "skip" because
            # ask() substitutes the default, so we use an explicit sentinel.
            token = ask(
                f"  new folder '{cur}/' \u2014 prefix token "
                f"(Enter to accept, or '-' to SKIP this folder)",
                default_tok,
            )
            if token.lower() in ("-", "skip"):
                cfg.ignore.append(cur)
                return None
        acc = token if acc == "" else f"{acc}-{token}"
        cfg.folders[cur] = acc
    return acc


def flattened_name(repo_prefix: str, dir_prefix: str, filename: str) -> str:
    parts = [p for p in (repo_prefix, dir_prefix) if p]
    return ("-".join(parts) + "-" + filename) if parts else filename


# ───────────────────────────────── main ────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Flatten a repo for Claude Projects.")
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--output-dir", default="flattened")
    ap.add_argument("--repo-name", default=None)
    ap.add_argument("--repo-prefix", default=None)
    ap.add_argument("-y", "--yes", action="store_true")
    ap.add_argument("-n", "--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    # --check implies a read-only, non-interactive run.
    if args.check:
        args.dry_run = True
        args.yes = True

    repo = Path(args.repo).resolve()
    # Prefer the git top-level if we're inside one.
    try:
        top = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if top.returncode == 0 and top.stdout.strip():
            repo = Path(top.stdout.strip())
    except FileNotFoundError:
        pass

    out_dir = repo / args.output_dir
    cfg_path = out_dir / "flatten.cfg"
    cfg = Config.load(cfg_path)

    first_init = not cfg_path.exists()
    if not cfg.repo_name:
        cfg.repo_name = args.repo_name or repo.name
    if not cfg.repo_prefix:
        if args.repo_prefix:
            cfg.repo_prefix = args.repo_prefix
        elif args.yes or args.check or args.dry_run:
            cfg.repo_prefix = slug(cfg.repo_name)[:3]
        else:
            cfg.repo_prefix = ask(
                f"Repo prefix for '{cfg.repo_name}'", slug(cfg.repo_name)[:3]
            )

    when = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1) Gather candidate files (skip .git, the output dir, and dotgit internals).
    candidates: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo):
        rel_dir = os.path.relpath(dirpath, repo)
        rel_dir = "." if rel_dir == "." else rel_dir.replace(os.sep, "/")
        # Prune directories we never descend into.
        dirnames[:] = [
            d for d in dirnames
            if d != ".git"
            and not (rel_dir == "." and d == args.output_dir)
        ]
        for fn in filenames:
            rel = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            candidates.append(rel)

    # 2) Ask git which are ignored (one batched call).
    ignored = git_ignored_set(repo, candidates)

    # 3) Process.
    stats = {"unchanged": 0, "restamped": 0, "inserted": 0, "updated": 0,
             "copied": 0, "flat-unchanged": 0, "skipped": 0, "ignored": 0}
    nocomment: list[str] = []
    binary: list[str] = []
    drift = False
    expected_flat: set[str] = set()

    for rel in sorted(candidates):
        if rel in ignored:
            stats["ignored"] += 1
            if args.verbose:
                print(f"  ignored (git)   {rel}")
            continue
        if cfg.is_ignored(rel):
            stats["skipped"] += 1
            if args.verbose:
                print(f"  skipped (cfg)   {rel}")
            continue

        src = repo / rel
        rel_dir = os.path.dirname(rel) or "."

        dir_prefix = ensure_dir_prefix(rel_dir, cfg, args)
        if dir_prefix is None:
            stats["skipped"] += 1
            if args.verbose:
                print(f"  skipped (dir)   {rel}")
            continue

        # Flattened destination — also the reference for "did the body change?".
        flat_name = flattened_name(cfg.repo_prefix, dir_prefix, src.name)
        expected_flat.add(flat_name)
        dest = out_dir / flat_name

        # Include decision. A correct/any existing block => already included.
        rt = read_text(src)
        has_block = False
        if rt is not None:
            head_lines = rt[0].split("\n")
            has_block = find_block(head_lines) is not None

        if not has_block:
            # New candidate. Prompt unless it's binary/none (still copyable).
            if args.yes or args.check or args.dry_run:
                include = True
            else:
                include = ask(f"  include '{rel}'? (Y/n)", "Y").lower() != "n"
            if not include:
                cfg.ignore.append(rel)
                stats["skipped"] += 1
                continue

        # Refresh the timestamp when the body changed since the last flatten.
        restamp = body_changed(src, dest)

        # Ensure the path comment in the SOURCE.
        action = ensure_comment(src, rel, when, args.dry_run, restamp)
        if action in ("inserted", "updated", "restamped"):
            drift = True
        if action == "nocomment":
            nocomment.append(rel)
        elif action == "binary":
            binary.append(rel)
        else:
            stats[action] += 1

        # Mirror into flattened/.
        new_bytes = src.read_bytes()  # post-injection content
        if dest.exists() and dest.read_bytes() == new_bytes:
            stats["flat-unchanged"] += 1
        else:
            drift = True
            stats["copied"] += 1
            if not args.dry_run:
                out_dir.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(new_bytes)
        if args.verbose:
            print(f"  {action:9} -> {flat_name}")

    # 4) Prune / report stale flattened files.
    stale: list[str] = []
    if out_dir.exists():
        for f in out_dir.iterdir():
            if f.is_file() and f.name != "flatten.cfg" and f.name not in expected_flat:
                stale.append(f.name)
    if stale:
        drift = True
        for s in stale:
            if args.prune and not args.dry_run:
                (out_dir / s).unlink()
                print(f"  pruned stale    {s}")
            else:
                print(f"  STALE (no source) {s}  (use --prune to remove)")

    # 5) Persist config (unless read-only).
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        cfg.save(cfg_path)

    # 6) Summary + flags.
    print("\n" + "-" * 60)
    if first_init and not args.dry_run:
        print(f"Initialised {cfg_path.relative_to(repo)}")
    print(f"repo={cfg.repo_name!r} prefix={cfg.repo_prefix!r}  output={args.output_dir}/")
    print("  comments:  "
          f"{stats['inserted']} inserted, {stats['updated']} updated, "
          f"{stats['restamped']} re-stamped, {stats['unchanged']} unchanged")
    print("  flattened: "
          f"{stats['copied']} copied, {stats['flat-unchanged']} unchanged")
    print(f"  skipped:   {stats['skipped']} (cfg/dir), {stats['ignored']} (gitignore)")
    if nocomment:
        print("\n  \u26a0  CANNOT hold a comment (copied WITHOUT a path header):")
        for r in nocomment:
            print(f"       {r}")
    if binary:
        print("\n  \u26a0  binary / undecodable (copied WITHOUT a path header):")
        for r in binary:
            print(f"       {r}")

    if args.check and drift:
        print("\n--check: OUT OF SYNC (run without --check to fix).")
        return 1
    if args.check:
        print("\n--check: in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
