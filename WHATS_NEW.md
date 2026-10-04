# What's new: games -- what Gary can build, a 3D world, and a warning

*2026-10-04, branch `phase-13-live-preview`. The numbers are in SPIKES.md §33.*

## In one sentence

Asked for a 3D block game, Gary now gives one -- a first-person world of 1-metre blocks
you walk through with W A S D -- and starting a game on Gary Fast says plainly that it
struggles to build a whole game, and offers what this Mac can use instead.

## What we found

Eight game builds through the real Workbench, each step's goal written down before it
ran: a Blank start, an empty Games project, the idea cards, changing the characters,
changing the background, a side-scroller, the owner's own test05 (the block 3D game), and
a 3D walk in space. Both local models, before and after the fixes:

| | Steps done (of 22), before | after | Changing the 3D world |
|---|---:|---:|---|
| **Gary Fast** | 6 done, 3 partly | **11 done, 6 partly** | night ✓, a red tower ✗, walk faster ✗ |
| **Gary Smart** | 5 done, 2 partly | **8 done, 10 partly** | night ✓, a red tower ✗, walk faster ✓ |

Gary Smart took about twice as long for the same turns.

- **Both models do one concrete change well** -- a blue circle, the child's picture as the
  player, bigger, a night sky, trees. **Neither builds a whole game from one sentence**
  (the cat game, a platformer, a side-scroller), and before this pass **neither drew
  anything 3D**: Open Nest itself told every model to make "the closest 2D version".
- **Gary Smart is not clearly better at games.** Better at some steps, worse at others,
  and about twice as slow. It is better at changing the 3D world.
- **Cloud was not measured**: both saved keys were refused ("invalid" / "invalidated").

## What changed

- **The 3D Block World** -- a new way to start a Game ("How it starts"), and what a 3D
  request gets while the game is still the plain starter. First person, W/S walk, A/D
  turn, two hands, gold blocks to collect. Everything to change is a named line at the
  top: the map (`WORLD`, one letter a block), the kinds of block, `SKY = "day"`,
  `"sunset"`, `"night"` or `"space"`, `GROUND = "grass"`, `"sand"`, `"snow"` or `"moon"`,
  planets, hands, speeds. In it, Gary is told what the world is and which names to
  change; the 2D scene tool, recipes and plans step aside. Never replaces a game the child
  has changed -- they are told where to find it instead.
- **The warning.** Beginning a Game on Gary Fast: "Gary Fast struggles to build a game
  that works ... For a game, use at least Gary Smart or a cloud model." Buttons only for
  what this Mac can really use (Gary Smart if installed and it fits the memory, a cloud
  model if a parent turned cloud on and saved a key), the parent's step otherwise, and
  always "Keep Gary Fast". Which model gets it is catalogue data (`struggles_with`).
- **The Platform Game card** was built as the asteroid-dodging game on Gary Fast (and a
  side-scroller on Gary Smart). Fixed.
- **Fixed along the way:** a plan offering one step three times; Gary repeating Open
  Nest's plan from the turn before as his own reply; "The only change made was ..." in a
  turn that changed nothing; shapes placed off the screen when Gary gave screen positions
  and no size (Gary Smart's mountains and trees).

## Not done yet

- **Cloud models** -- unmeasured until a parent saves working keys (drop them in `.env` as
  before).
- Neither model added a new kind of block to the 3D map (the "red tower") in any run.
- Whole games in one sentence still fail on both local models; Open Nest offers a plan.
- No 8 GB Mac has been measured.
