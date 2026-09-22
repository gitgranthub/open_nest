# Open Nest — Prepared Brand Asset Guide

This package contains production-ready derivatives of the supplied Open Nest pixel artwork.
The original uploaded files are preserved unchanged in `00_source/`.

## Core visual language

- **OPEN NEST wordmark** = full product identity
- **ON + Nest** = compact Open Nest identity for smaller app spaces
- **Nest** = home / project / place
- **Eagle cycle** = loading / processing / active work
- **White sunglasses** = authority / approval / meaningful completion

## Rendering rule

These are pixel-art assets. Always render them with **nearest-neighbor / no smooth interpolation**.

For PySide6 / Qt, do not use `Qt.SmoothTransformation` for these images.
Prefer `Qt.FastTransformation` or draw at prepared native sizes.

Do not vectorize, blur, recolor, antialias, add drop shadows, or apply glossy effects.

## 01_logos

### `open_nest_wordmark_master.png`
Tight transparent production master derived from the supplied OPEN NEST artwork.

Prepared width variants:
- 1024
- 768
- 512
- 384
- 256
- 192 px

Use the full wordmark for:
- installer / onboarding
- startup
- Flight Deck hero identity
- About
- setup-complete screens

### `open_nest_compact_*.png`
Standardized **ON over Nest** compact logo.

Use this in smaller app environments:
- Workbench header
- compact Flight Deck header
- sidebar / app chrome
- launcher or small identity areas
- compact branded empty states

Do not rebuild the ON + Nest relationship independently on each screen. Use these prepared composite assets.

### `on_wordmark_*`
Standalone ON assets are included for special layouts, but the prepared compact logo is the default shorthand identity.

## 02_symbols

### `nest_*`
Standalone nest symbol. Use where product identity is already established or where a larger home/project symbol is wanted.

### `approval_glasses_*`
White sunglasses approval mark.

Reserve for meaningful completion or approval:
- setup finished
- a major repair worked
- a project milestone works
- verified configuration
- rare “That did it.” / “It works.” states

Do **not** use for every save, minor success, or response.

## 03_eagle_animation

The supplied eagle sprite artwork has been prepared as a **12-frame animation**.

Folders:
- `master_frames/` — normalized 342×342 frames, no scaling
- `frames_256/`
- `frames_128/`
- `frames_96/`
- `frames_64/`

Frames are named sequentially:
`eagle_01.png` through `eagle_12.png`

Recommended playback:
- start around **8 fps** (125 ms per frame)
- loop continuously while real work is occurring
- no tweening or generated intermediate frames
- do not move the eagle across the screen; only cycle its wing poses

Suggested use:
- model loading
- AI generation
- project preparation
- error inspection
- model install/verification
- longer project processing

Do not show it for sub-second operations.

`04_preview/eagle_cycle_preview.gif` is only a visual preview. Runtime use should prefer the PNG frame sequence for predictable pixel fidelity.

## Suggested size use

### Compact logo
- 64 / 96 px: tiny utility areas
- 128 px: small header / sidebar
- 192 / 256 px: standard branded panel
- 384 / 512 px: onboarding / setup
- 1024 px: large presentation / future export needs

### Nest
- 96 / 128 px: empty state / small identity
- 192 / 256 px: normal branded area
- 384 / 512 px: onboarding / hero

### Sunglasses
- 64 / 96 px: small completion badge
- 128 / 192 px: standard completion moment
- 256+ px: setup completion / larger milestone

### Eagle
- 64 px: inline / small waiting state
- 96 / 128 px: preferred normal processing indicator
- 256 px: installer / larger waiting screen

## Color handling

Keep artwork monochrome.

Use Open Nest’s subtle beige / cream / charcoal interface palette around the assets.
Muted amber may highlight controls or progress.
Muted green/red remain semantic UI status colors.

Do not recolor the brand artwork itself.

## Accessibility

Never let the graphic be the only status signal.

Pair:
- eagle with text such as `Loading Qwen…`
- sunglasses with text such as `It works.`
- logo with an accessible `Open Nest` label

## Source preservation

Do not edit files in `00_source/`.

If future sizes are required, derive them from the prepared master or the original source using nearest-neighbor scaling.
