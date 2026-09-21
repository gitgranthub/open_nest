# Wiring

## Right now: nothing to wire

This sketch uses `LED_BUILTIN` -- the small light soldered onto the board itself. There
is no wire to connect and nothing to get wrong yet.

## Connections

| What | Board pin | Notes |
|---|---|---|
| Onboard LED | `LED_BUILTIN` | Already connected inside the board |

Add a row every time you connect something. Keep this table and the pin constants at the
top of `project.ino` saying the same thing.

## Power notes

Nothing here draws power from a pin yet, so there is nothing to be careful about.

That changes the moment you add real parts. Two things worth knowing before you do:

- **An LED needs a resistor.** Connecting one straight across a pin lets too much current
  through and can damage the LED, the pin, or both.
- **A motor or a servo should not be powered from a board pin.** They pull far more
  current than a pin can give. They need their own power supply, with the grounds
  connected together.

If you are not sure what something needs, ask before you plug it in. Say what the part
is -- or add a photo or its datasheet to the project -- and you will get a real answer
instead of a guess.
