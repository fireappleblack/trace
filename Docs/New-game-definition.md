<!-- flatten:begin
     repo-path: Docs/New-game-definition.md
     generated: 2026-06-13T21:50:00Z by flatten.py — do not edit this block
flatten:end -->

# Trace — Game Definition (v0.40.0)

This is the authoritative definition of the game as of **v0.40.0**. Where it
conflicts with earlier instructions it supersedes them, **unless** doing so would
break playability. Reproduction of boards generated *before* this definition (from
their old URL seeds) is explicitly **not** preserved — but, as before, every URL
produced under this definition must recreate a **fully reproducible** board with
all of its settings.

The biggest change from earlier versions: **a board no longer needs a unique
solution** (§14). That removes the uniqueness-enforcement machinery — which was
also the source of the 9×9 generation latency — and reframes play around
*choosing among* solutions (wriggliness competitions, find-the-shape challenges).

---

## A. Board & path

1. **Size.** 5–9 rows × 5–9 columns, each chosen independently (inclusive).
2. **Shape.** A rectangle, including the square case.
3. **Goal.** The board is solved by a **Hamiltonian path** that visits **every
   non-blank cell exactly once** (the blanked cells of §B are excluded from the
   path).
4. **Nodes.** The path threads numbered nodes. Count is set by random generation
   **XOR** an explicit user choice:
   - one snake: **5 … ⌊2·√area⌋** total nodes (so 5–16 at 8×8; up to 18 at 9×9);
   - two snakes: **3 … pairMax odd nodes *per snake*** (pairMax = largest odd ≤
     ⌊√area⌋+1), the two snakes sharing the kiss, so a combined **2m−1** nodes.
   *(Open decision — see §F1: keep the area-scaled cap, or hard-cap at 16.)*
5. **Snakes.** Either **1** or **2**.
6. **One snake.** Nodes numbered 1…N consecutively; the path runs node 1 → node N.
7. **Two snakes.** Each snake is numbered 1…m from its own outer end and both peak
   at the shared **"kiss"** cell, so the kiss is the **highest** number. Two snakes
   require **both board dimensions to be odd**, so a true centre cell exists for
   the kiss. *(Internally the solver still labels the whole path 1…K with the kiss
   mid-sequence; that is an implementation detail, not the player-facing model.)*

---

## B. Symmetry-breaking blanks

8. **Blanks.** Every board removes **1 or 2 cells from play** ("blanks"), placed in
   the bottom-left quadrant, chosen so that **no non-identity board symmetry leaves
   the playable region unchanged** — i.e. rotation about the centre, mirroring
   across the x or y axis, and (on a square) across either diagonal are all broken.
   This keeps every board distinct from its own transforms (anti-cheat / no board
   "collisions") and ensures no solution has a trivial rotated/mirrored twin — which
   matters more now that multiple solutions count (§14).
9. **Quadrant.** The bottom-left quadrant is **columns 0 … ⌊C/2⌋−1** by **rows
   0 … ⌊R/2⌋−1** (i.e. ⌊C/2⌋ columns and ⌊R/2⌋ rows). The "−1" is load-bearing: it
   keeps the **middle row/column of an odd dimension out** of the candidate set, so
   a blank can never sit on a centre line. *(Convention: this text takes the origin
   at the bottom-left; the implementation indexes row 0 at the top — same region,
   stated for clarity. The earlier "0 … floor(x/2)" inclusive form was off by one
   and would have included the centre line.)*
10. **How many blanks — driven by the snake count.** One snake → **1** blank;
    two snakes → **2** blanks. The parity justification: two equal snakes meeting at
    a central kiss need an **odd** playable-cell count (kiss at the exact midpoint of
    equal arms). Two-snake boards are odd×odd, so the total is odd, and odd − 2 = odd
    → two blanks. One snake has no such parity demand, so it uses just the single
    symmetry-breaking blank. *(This is the non-circular form of the earlier rule:
    the count comes from the snake configuration, not from "blanks needed to fill the
    board," which defines the count in terms of itself.)*
11. **Odd×odd parity (mandatory).** On a board with both dimensions odd, a single
    blank **must** sit on the majority checkerboard colour (even `r+c`); removing a
    minority-colour cell leaves no Hamiltonian path at all.
12. **Single blank — anti-diagonal (square only).** On a **square** board the lone
    blank must avoid the anti-diagonal (`r+c == N−1`), to break that reflection.
    **Exception: 5×5**, whose only two parity-legal quadrant cells both lie on the
    anti-diagonal — there the exclusion is skipped and the board keeps a harmless
    residual anti-diagonal symmetry (uniqueness is no longer required, so this costs
    nothing). Non-square boards have no anti-diagonal reflection, so no constraint.
13. **Two blanks — anti-diagonal (square only).** The **bottom-left corner** is
    always one of the two blanks; it lies *on* the anti-diagonal (it is precisely the
    cell that reflection fixes), so the corner alone cannot break it. The **second
    (rolled) blank** sits elsewhere in the quadrant and, on a square, must stay
    **off** the anti-diagonal — so at most one of the two blanks is ever on it.
    Confining the rolled blank to the quadrant is what makes this clean: a
    quadrant cell can never mirror-pair with the corner across any axis (its partner
    lands in a different quadrant), so it cannot re-impose a symmetry the corner has
    already broken. The only symmetry left to handle is therefore the anti-diagonal,
    hence this single rule.

---

## C. Multiple solutions & wriggliness

14. **Multiple solutions are allowed.** A board may admit many Hamiltonian paths
    through its nodes; the game does **not** enforce a unique solution and no longer
    adds walls to manufacture one. Generation needs only to guarantee that **at
    least one** ordered Hamiltonian path exists — which the generator does by
    construction (it lays the nodes along a real path). Players compete over the
    solution they find.
15. **Wriggliness.** A solution's wriggliness is the **number of direction changes
    (turns)** along the path: a cell where the incoming direction differs from the
    outgoing direction. The two path ends are not turns. Competitions can be:
    **least-wriggly**, **most-wriggly**, or **find a pre-selected target solution**
    (§D). *(Name note: this solution-score is distinct from the existing build-time
    "wiggle" `w`, which only biases how the board is generated. Keep the names
    separate — "build-wiggle" vs "solution-wriggliness".)*

---

## D. Admin tooling — solution enumeration & "find the shape"

A knock-on of §14: an admin can pre-select a solution (or several) and challenge
players to find it — "find the path that looks like a fish / smiley / rising sun."
This lives in the **admin back-end** (the same planned interface that edits
DB-stored content), runs **offline, one board at a time**, so heavy compute is
acceptable here in a way live generation never was.

**16. Combinatorial reality (measured on the 0.33.0 solver).** The number of
solutions is governed by **node density, not board size**:

| Board | nodes | solutions (walls off) |
|-------|-------|-----------------------|
| 5×5   | 5     | 13                    |
| 5×5   | 8     | 2                     |
| 7×7   | 5     | 44,539                |
| 7×7   | 10    | 277                   |
| 7×7   | 14    | 36                    |
| 9×9   | 5     | ≥844,000 (did not finish in 60 s) |
| 9×9   | 12    | ≥126,000 (did not finish)         |
| 9×9   | 18    | 10,872 (1.3 s)        |

So a heavily-noded board is trivially enumerable; a lightly-noded one is
effectively unbounded.

**17. Enumeration is always capped.** The enumerator runs under a **solution cap**
*and* a **node/time budget**. On overflow it reports "too many to enumerate — add
nodes or walls, or use targeted search" rather than hanging. (The existing solver
already counts-to-cap and aborts on a node budget; this is a repurpose.)

**18. Two authoring modes.**
   - **Enumerate-then-pick** (build first): only when the count is small (≤ a few
     thousand). Render a thumbnail of every solution; the admin clicks the one that
     looks like the target and names it.
   - **Shape-guided search** (follow-on): the admin sketches the rough target (or
     marks cells the path must turn through) and the solver searches *for matches*
     directly, instead of enumerating everything and filtering. This is the mode
     that scales to lightly-constrained boards.

**19. "Looks like a fish" is a label, not a classifier.** No automated shape
recognition. The admin selects an **exact path** and names it; the challenge is to
reproduce that exact path, validated by **exact match** against the stored target.
Because board symmetry is broken (§B), the target has **no mirror-image twin** that
would also win.

**20. Storage.** Target solution(s) are admin-authored metadata stored in the DB
(as a path, or a compact signature/hash of it), **keyed to the URL-reproducible
board** (seed + `bx`). Player submissions are matched against the stored signature.

**21. Walls as a sculpting knob (see §E walls).** Walls now shrink the solution
space on demand: an admin can pull a 126,000-solution board down into the enumerable
hundreds to make a curated find-the-shape challenge tractable.

**22. Free by-product.** The same enumeration pass yields the **true min/max
wriggliness** for the board, making the §15 least/most-wriggly competition *provably*
judgeable — but only on boards constrained enough to enumerate within budget; on
wide-open boards both the shape catalogue and the wriggle optimum are
"best-effort-within-budget."

---

## E. Carried-over rules (already in the game, compatible with the above)

- **Node ordering.** The path must pass through the numbered nodes in **ascending
  order** (one snake 1→N; two snakes each 1→kiss).
- **Two snakes ⇒ both dimensions odd** (so a true centre cell exists). Enforced.
- **Walls (`m`, levels 0–4).** Optional internal edges the path may not cross. No
  longer a uniqueness device (§14); now a difficulty/variety control and the
  solution-space sculpting knob of §21. Must always leave ≥1 valid solution.
- **`diffshades`.** Two-snake colour option: off = both snakes' numbers share one
  neutral shade (harder to tell the snakes apart); toggling regenerates the board so
  it can't be used as a difficulty cheat.
- **Per-control 🎲 + "Surprise me".** Randomisers for each control and a
  full-board randomiser.
- **Full URL reproducibility / determinism.** Every rolled or chosen value (grid,
  node count, snake count, build-wiggle `w`, wall level `m`, blank index `bx`, seed,
  point count `pts`) is written to the URL, and generation is **wall-clock-free**, so
  any URL reproduces the exact board on any machine, under any load.

---

## F. Open decisions

1. **Node-count cap.** Keep the area-scaled `5 … ⌊2·√area⌋` (up to 18 at 9×9), or
   hard-cap at 16? The original "5–16" was the 8×8 figure. *Default: keep the
   area-scaled bound.*
2. **Walls — keep or retire?** They no longer serve uniqueness, but they remain
   useful for difficulty/variety and for sculpting the solution space (§21).
   *Default: keep, repurposed.*

---

## G. Implementation notes (v0.40.0)

- **Drop uniqueness enforcement** from generation: no uniqueness solve, no
  wall-adding to force a single solution. Generation = pick a Hamiltonian path over
  the playable cells → place the ordered nodes along it → (optionally) lay
  difficulty/variety walls → done. This removes the expensive solve from the hot
  path, so large grids (esp. 9×9) generate fast.
- **Two-pen rolled blank** moves into the bottom-left quadrant (off the anti-diagonal
  on squares), per §13 — previously it could land anywhere on the board.
- **Add a `solution-wriggliness` measure** (count of direction changes) for §15.
- The admin enumerator/find-the-shape (§D) is a **separate, subsequent workstream**
  (admin back-end), not part of the core client change.
