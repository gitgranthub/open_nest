"""Game graphics: what things in a child's game look like, and the scene they are in.

Phase 13C (PHASE_13_HANDOFF.md section 9, SPIKES.md section 28). The owner's test found
Open Nest could make a game run and still not make it look like anything: an
``eagle.png`` in the Assets panel, Gary saying the eagle was the player, and the orange
starter square on screen. The picture was not a picture at all -- the model had written
a sentence into a file called ``eagle.png`` -- and the code loading it sat in a ``try``
that drew the square whenever it failed.

So the boring half of graphics moved out of the model's hands:

- ``kit/scene.py`` is a small, readable pygame helper that goes into the project as
  ``src/scene.py``: pictures, animations, drawings made of shapes (and a dozen ready-made
  ones built from the same shapes), and a scene that draws everything in layers. The
  game stays ordinary Python and pygame, and runs without Open Nest.
- ``game_object`` is the tool Gary calls for anything the child sees. He decides what it
  is, what it looks like, where it goes and what touching it does; this package writes
  one readable line for it in the game, in the right place.
- ``looks`` checks what he asked for -- a picture that really is one, colours the kit can
  draw, shapes in their own box -- and ``source`` finds and changes the game's scene with
  the parser.

Nothing here imports pygame. The application writes code that draws; only the child's
game, in its own sandboxed process, ever runs it.
"""
