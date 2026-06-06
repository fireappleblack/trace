<!-- flatten:begin
     repo-path: Docs/IDEAS.md
     generated: 2026-06-06T16:14:29Z by flatten.py — do not edit this block
flatten:end -->

# Trace — Ideas / backlog

Loose, not-yet-committed ideas. Unlike `STATUS.md` (which tracks the live
system and its risks), this is a parking lot for things still being thought
through. Move an item into a real task / `STATUS.md` once it's decided.

## Onboarding backdrop — "other" image option (3c)

The onboarding gate now shows a **finished-puzzle backdrop** behind the welcome
banner and consent card, so a first-time player sees a worked example without
seeing the real puzzle they're about to play (which would let them pre-solve it
before the timer can start). Two sources are implemented:

- **(a)** a built-in wiggly 6×6 sample (`SAMPLE_PUZZLE`) for new players / cleared
  data;
- **(b)** a snapshot of the player's **last completed puzzle**, stored locally
  (`trace.lastPuzzle`) and refreshed on every solve.

**Still to decide — (c) a designated "other" backdrop image**, e.g. a charity
sponsor card or seasonal art. Open questions before building:

- **Source & control:** like the welcome-banner text, this should be editable
  without a code change — so probably a new `ui_text` / config category (e.g.
  `onboarding_backdrop`) holding an image URL or inline SVG, served via
  `/api/ui-text`. Ties into the **admin backend** that still needs building.
- **Selection rules:** when does the sponsor image win over (a)/(b)? Always for
  a campaign window? A rotation/weighting? Only for brand-new users?
- **Format & weight:** inline SVG (themeable, sharp, tiny) vs a hosted raster
  (easier for a sponsor to supply, but a network fetch on a blocking screen —
  needs a cached/offline fallback to the sample).
- **Disclosure:** if it's a paid sponsor, it must be clearly labelled as such
  (and kept consistent with "no ads inside the puzzle itself").
- **Sizing/safe-area:** must read well behind the centred banner/card on a
  narrow phone — reuse the `.onboarding-backdrop` sizing.

Lowest-friction first step when ready: add an optional `onboarding_backdrop`
entry to the DB UI-text, have the client prefer it over the sample when present
(still falling back to the last-puzzle snapshot / sample offline), and gate it
behind the admin UI for editing.

## Related, smaller follow-ups

- **Wiggliness in the leaderboard key.** `w` is now a first-class URL parameter
  (like Grid/Difficulty), but the server leaderboard key is still
  `(seed, size, difficulty)`. Two *independently* generated identical base
  seeds with different `w` would share a board — a ~1-in-2-billion collision, so
  not worth a schema change now, but noting it. If ever wanted, add `wiggle` to
  the attempts key + daily metadata.
- **Last-puzzle backdrop for returning users.** The backdrop only shows during
  onboarding (new / un-consented users). Could optionally surface the
  last-solve snapshot elsewhere (e.g. a small "your last solve" flourish), but
  not obviously worth it.

## Generation tuning — fix "Really Wiggly", add a walls slider, add randomisers

Raised 2026-06-03. A cluster of related generation-control ideas.

- **"Really Wiggly" (`w=4`) is too predictable — the real bug to fix.** At the
  top of the range the path bends at nearly every opportunity, which paradoxically
  makes it *easier*: the solver can just take every available turn and walk it.
  Example: `…/?seed=4l62ge&size=8&difficulty=fiendish&w=4` was solvable by
  wiggling at every step. The failure mode: maximal turn-ratio collapses the
  branching factor (few legal non-turning moves left), so "always turn" becomes a
  near-deterministic winning heuristic. Fixes to explore — cap the top of the
  range below pathological wiggliness; or make high `w` target a turn-ratio
  *band* rather than "as wiggly as possible"; or inject some straight runs so
  "always turn" stops being a valid strategy. **Decision for now:** keep
  Really-Wiggly as a user-chosen option (it's a choice, not a default), but treat
  the predictability as a real defect to address.
- **New "walls" slider** — the other obvious difficulty lever, independent of
  wiggliness. Range from **"no walls"** to **"practically a maze (amaze! amaze!)"**.
  Likely a first-class URL parameter alongside `w` (e.g. a `walls`/`m` param) with
  its own main-UI slider, same pattern as the wiggliness control. Open question:
  how walls interact with guaranteed-solvability of the Hamiltonian path (must not
  wall off a required transition).
- **"Chef's choice" per control** — a button next to each slider/drop-down (grid
  size, difficulty, wiggliness, walls) that picks *that one* parameter at random.
  Leaves the others as set.
- **"Chef's gone home; let the restaurant decide"** *(working name — may be
  renamed)* — a single button that randomises **every** parameter at once (grid
  size, difficulty, wiggliness, wall proliferation) on each press, for a fully
  surprise puzzle.

Implementation notes when this is picked up: walls + a random-all button mean the
URL needs to round-trip every generation parameter (already true for `seed`,
`size`, `difficulty`, `w`; add the walls param), so a randomised puzzle is still
shareable/reproducible.

**Settled (2026-06-03): randomisers always write their rolled values into the
URL.** Every generated puzzle — including anything produced by a "chef's choice"
or "restaurant decides" press — must be fully shareable/reproducible. The cost of
writing the rolled values back is negligible programmatically and conceptually,
whereas a puzzle that *can't* be shared breaks the expectation that the URL *is*
the puzzle, and would disappoint. So the randomisers resolve to concrete
parameter values and call the same `updateURL` path as the manual controls — no
ephemeral/unshareable generation states. (Practical consequence: a randomise
button rolls values, writes them to the URL, then generates from them — not the
reverse.)
