# My Arduino Project

## What it does

Blinks the small light that is already built into the board, on for half a second and
off for half a second, forever.

## What you need

- An Arduino board
- A USB cable

Nothing else yet. The light this uses is already on the board, so there is nothing to
wire up until you add your own parts.

## How to use it

1. Press **Compile**. That checks the code is valid without needing the board plugged in.
2. Plug the board into your Mac with the USB cable.
3. Press **Upload** to put the sketch on the board.

Compile first. It is much easier to find a mistake before the board is involved.

## Changing it

The two numbers at the top of `project.ino` are the on and off times in milliseconds
(1000 milliseconds is one second). Make them smaller for a faster blink.

When you add real parts, write down what is connected where in `wiring.md` and keep it
up to date. If you change a pin in the sketch, change it in `wiring.md` too.
