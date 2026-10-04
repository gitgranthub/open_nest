# What's new: Gary can see the child's pictures

*2026-10-03, branch `phase-13-live-preview`. The numbers are in SPIKES.md §32.*

## In one sentence

When a child adds a picture, Gary now looks at it and knows what it shows: "It shows a
happy, fluffy blue monster with purple spots and big eyes."

## What changed

- **Two new local models, the only ones setup offers.** **Gary Fast** (Qwen3-VL 4B, the
  default) and **Gary Smart** (Qwen3-VL 8B, for Macs with 16 GB or more). Both can see.
  The older Qwen and other local models still work wherever they are already installed,
  but are no longer offered or suggested.
- **Gary looks once, and remembers in words.** Each picture is shown to the model when
  it is added. What it shows is saved with the picture and given to Gary every turn. A
  picture attached to a message is also shown with that message.
- **Still honest.** A picture counts as seen only when its pixels really reached the
  model. Until then Gary is told nobody has looked, and a made-up description is caught.
- **Setup and the app use the new models.** The wizard shows each model with what it is
  good for, and checks that the model can really see (it shows it a red picture). The
  app starts the model chosen in setup, and moves to Gary Fast once it is installed.
  Updating with `git pull` now installs the vision engine too.
- **The Fast Path still works.** It runs on whichever model is Gary; no second model is
  needed.

## How it measured

| | Good first moves (of 94) | Wrong Fast Path recipe edits (held-out) | Sees pictures |
|---|---|---|---|
| Qwen3 4B (the old default) | 67 | 0 | no |
| **Gary Fast** | **79** | 3 | yes |
| **Gary Smart** | **83** | 0 | yes |
| Qwen3 8B (not offered now) | 92 | not measured | no |

On the owner's test threads, both models built the maze. Gary Fast made the forest from
the child's own tree pictures in both rounds, and Gary Smart in its second. In the real
window, the setup wizard walk passed 53/53 and the app walk 42/42.

## Fixed along the way

- See-through pictures reached the model as solid black. They are now laid on white.
- Gary got stuck resending one broken edit. The refusal now says what to do instead.
- A line repeated in one reply is now said once.
- A promise ending in "What do you want next?" no longer counts as asking the child a
  question.

## Not done yet

- No 8 GB Mac has been measured. Gary Fast peaks at about 3.6 GB.
- Cloud models still are not sent pictures.
- On the whole-game request Gary Fast still tries to rewrite the file first. Gary Smart
  draws its own monsters instead of using the child's picture.
