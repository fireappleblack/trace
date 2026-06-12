<!-- flatten:begin
     repo-path: Docs/IDEAS.md
     generated: 2026-06-09T17:58:58Z by flatten.py — do not edit this block
flatten:end -->

# Trace — Ideas / backlog

Loose, not-yet-committed ideas. Unlike `STATUS.md` (which tracks the live
system and its risks), this is a parking lot for things still being thought
through. Move an item into a real task / `STATUS.md` once it's decided.

## Per-control "chef's choice" randomisers + "restaurant decides" — DONE (2026-06-07)

Implemented. Every interactive control now has a 🎲: **Path/wiggle**, **Walls**,
**Points**, and **Grid** each roll their own value (keeping the current seed), and
a **"🎲 Surprise me"** button ("restaurant decides") rolls *everything at once* —
mode, grid, difficulty, path, walls, points — with a fresh seed. Two-pen rolls
respect the constraints (odd grid dimensions, odd per-snake point counts). Every
rolled value is written to the URL via `updateURL`, so any randomised puzzle is
fully shareable/reproducible. Validated: 30 random "surprise" draws → 0 invariant
violations, 28/30 generated first try (misses are the 9×9 low-point frontier,
absorbed by `newPuzzle`'s reseed-retry).

Refs: `trace.html` randomiser IIFE (`wiggleDice`/`wallsDice`/`gridDice`/
`pointsDice`/`surpriseBtn`); `.dice-btn` styling.

Possible follow-ups: a Mode 🎲 (currently only via Surprise, since a binary toggle
is odd as a die); a brief "rolled: …" toast so players see what changed.

## Generation tuning — "Really Wiggly" fix + walls slider — DONE (2026-06-06)

Raised 2026-06-03; shipped 2026-06-06. The cluster of generation-control ideas
that used to live here has landed — see the `2026-06-06 [zip-game]` entries in
`DECISIONS.md` for the specifics.

- **"Really Wiggly" (`w=4`) predictability — fixed.** At the top of the range the
  path used to bend at nearly every opportunity, which paradoxically made it
  *easier*: maximal turn-ratio collapsed the branching factor, so "always turn"
  became a near-deterministic winning heuristic (e.g. the old
  `…/?seed=4l62ge&size=8&difficulty=fiendish&w=4` was solvable by wiggling at
  every step). High `w` is now tuned so it's genuinely harder rather than just
  bendier, and Really-Wiggly remains a user-chosen option (a choice, not a
  default). (DECISIONS 2026-06-06 "Really Wiggly fix".)
- **Walls slider — shipped.** An independent difficulty lever, separate from
  wiggliness, ranging from **"no walls"** to **"practically a maze (amaze!
  amaze!)"**, as a first-class URL parameter with its own main-UI slider (same
  pattern as `w`). Walls are placed so the guaranteed Hamiltonian-path solvability
  invariant is preserved — no required transition is ever walled off — which the
  surprise-draw validation above exercises. (DECISIONS 2026-06-06 "Walls slider".)
- **Per-control "chef's choice" + "restaurant decides" randomisers — shipped**,
  covered by the randomisers section above (DONE 2026-06-07).

**Retained principle (settled 2026-06-03): randomisers always write their rolled
values into the URL.** Every generated puzzle — manual, "chef's choice", or
"surprise" — resolves to concrete parameter values and calls the same `updateURL`
path, so the URL *is* the puzzle and nothing is ever ephemeral/unshareable. The
cost of writing rolled values back is negligible, whereas a puzzle that *can't* be
shared breaks the core expectation and would disappoint. This remains the rule for
any future generation control: roll values → write to URL → generate from them
(never the reverse).

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
  the attempts key + daily metadata. *(Note: the walls parameter, now shipped,
  has the same property — if the leaderboard key is ever revisited, fold `walls`
  in alongside `wiggle`.)*
- **Last-puzzle backdrop for returning users.** The backdrop only shows during
  onboarding (new / un-consented users). Could optionally surface the
  last-solve snapshot elsewhere (e.g. a small "your last solve" flourish), but
  not obviously worth it.
