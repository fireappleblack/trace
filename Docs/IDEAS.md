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
