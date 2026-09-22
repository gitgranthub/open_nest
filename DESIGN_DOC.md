# Open Nest — Design & Naming Amendment

This document defines the product name, visual direction, and interface naming conventions only.

All technical architecture, functionality, setup, AI behavior, security, memory, Git/GitHub, execution, project types, and implementation requirements remain defined in the existing main work order.

---

## 1. Product Name

The product name is:

# Open Nest

Preferred display:

**OPEN NEST**

or:

**Open Nest**

Do not use Build Lab as the final child-facing product name.

Open Nest should stand on its own as a product. The Flying Eagle Productions influence should remain subtle and should not be explained to the user.

---

## 2. Design Direction

The interface should feel like a clean modern interpretation of a **late-1980s / early-1990s creative workstation**.

Reference direction:

- Braun industrial design
- early Nintendo hardware simplicity
- professional video/edit equipment
- early Macintosh-era workstation organization
- beige / bone / charcoal computing hardware
- physical buttons and equipment labels
- restrained early-'90s data/computer interface language

The target is:

**retro-informed, not retro-simulated**

Do not make it look like a parody of old software.

Avoid:

- fake CRT scanlines
- green terminal screens
- pixel fonts everywhere
- Windows 95 imitation
- vaporwave
- neon gaming UI
- cyberpunk styling
- excessive gradients
- glowing AI effects
- cartoon children's software

Modern usability should remain intact.

---

## 3. Visual Character

Open Nest should feel:

- practical
- calm
- tactile
- slightly industrial
- intelligent
- warm
- understated
- capable
- creative without looking playful or childish

It should feel appropriate for both a younger child and a teenager.

The product should look like a **real creative tool**, not an educational toy.

---

## 4. Color Direction

Base palette:

- warm beige / bone
- soft off-white
- charcoal
- graphite
- warm gray

Accent colors should be limited and muted.

Suggested directions:

- equipment amber/orange
- muted status green
- desaturated slate blue

Avoid highly saturated color systems.

Status indicators may borrow from physical equipment LEDs, but should remain small and functional.

---

## 5. Typography

Primary interface typography:

- clean
- highly readable
- modern macOS-compatible sans serif

Technical/status information may use a restrained monospace font.

Good uses for monospace:

- file names
- status labels
- model information
- build output
- code
- timestamps

Do not use novelty retro fonts.

Section headers may use simple uppercase labels such as:

`PROJECT`

`ASSETS`

`LOCAL AI`

`STATUS`

`BUILD`

---

## 6. Controls

Controls should have slightly more physical presence than contemporary ultra-flat UI.

Use:

- rectangular buttons
- modest corner radius
- visible borders
- clear pressed states
- obvious enabled / disabled states
- strong hierarchy

Avoid making every control a rounded pill.

Avoid excessive floating cards.

The design should subtly suggest physical equipment controls while remaining native-feeling on macOS.

---

## 7. Open Nest Vocabulary

Use a small number of subtle thematic names throughout the interface.

Do not theme every feature.

### Flight Deck

The main Open Nest home/dashboard screen.

Contains things such as:

- recent projects
- new project
- local AI status
- project status
- backup/sync status where appropriate

Example:

**OPEN NEST**

**FLIGHT DECK**

What do you want to make?

---

### Workbench

The primary project workspace.

This is where the child works with:

- files
- assets
- preview/build area
- assistant
- run controls

Example:

**Asteroid Game — Workbench**

---

### Field Notes

Optional child-facing notes area for:

- ideas
- observations
- things to try
- experiment notes

This should remain separate from internal project-memory files.

---

### Checkpoint

Acceptable child-facing term for a saved project version.

Examples:

- Saved checkpoint
- Restore checkpoint
- Return to earlier checkpoint

---

### Launch

May be used selectively as a general project action, but clarity takes priority.

Prefer contextual actions when clearer:

- Run Game
- Run Analysis
- Compile
- Test on Mac

Do not replace everything with themed terminology.

---

## 8. Terms That Should Stay Plain

Keep these names clear and conventional:

- Files
- Assets
- Settings
- Parent Settings
- Local AI
- Cloud AI
- Model
- Project History
- GitHub Backup
- Undo
- Restore
- Compile
- Arduino
- Raspberry Pi
- Research
- API Key

Theme must never make the interface harder to understand.

---

## 9. Main Screen Naming

Recommended top-level hierarchy:

```text
OPEN NEST

Flight Deck
    Recent Projects
    New Project

Workbench
    Project
    Files
    Assets
    Build / Preview
    Assistant
    Field Notes

Project History

Settings
```

This is terminology guidance, not a requirement for a specific navigation layout.

---

## 10. Flight Deck Visual Direction

The home screen should feel simple and spacious.

Example concept:

```text
OPEN NEST

FLIGHT DECK

Good evening, Elliot.

What do you want to make?

[ GAME ]
Build a game

[ ROBOT / PI ]
Build with Raspberry Pi

[ ARDUINO ]
Build a device

[ RESEARCH ]
Explore something

[ SOMETHING ELSE ]
Start with an idea


RECENT PROJECTS

Asteroid Game
Weather Station
Servo Creature


LOCAL AI
● READY ON THIS MAC
```

No aviation graphics are required.

The phrase Flight Deck should work as a subtle internal name rather than a visual theme.

---

## 11. Workbench Visual Direction

The main workspace should remain simpler than a traditional IDE.

Concept:

```text
┌──────────────────────────────────────────────────────────┐
│ OPEN NEST   /   ASTEROID GAME          LOCAL AI ●       │
├───────────────┬────────────────────────┬─────────────────┤
│ PROJECT       │                        │                 │
│               │    BUILD / PREVIEW     │    ASSISTANT    │
│ game.py       │                        │                 │
│ settings.py   │                        │                 │
│               │                        │                 │
│ ASSETS        │                        │                 │
│ spaceship.png │                        │                 │
│               │                        │                 │
│ + ADD         │                        │                 │
├───────────────┴────────────────────────┴─────────────────┤
│ ▶ RUN GAME      BUILD + TEACH             SAVED ●       │
└──────────────────────────────────────────────────────────┘
```

Avoid making it resemble:

- VS Code
- Xcode
- a terminal
- a professional IDE with many tiny controls

Technical complexity should remain visually secondary.

---

## 12. Assistant Presentation

Do not create a mascot.

Avoid:

- eagle assistant
- cartoon bird
- robot character
- animated helper

The assistant can simply be labeled:

**Assistant**

or remain integrated naturally into the workspace.

Its visual treatment should match the rest of the application rather than resemble a separate chatbot website.

---

## 13. Local vs Cloud AI

Clearly distinguish the two visually.

Example:

```text
AI MODEL

ON THIS MAC
● Qwen
  Recommended

  Gemma
  Llama

INTERNET
☁ OpenAI
☁ Claude
```

Do not visually position cloud models as inherently superior.

Avoid terms such as:

- Premium
- Pro
- Better
- Most Powerful

---

## 14. Status Language

Use restrained equipment-like system labels.

Examples:

```text
LOCAL AI     ● READY
PROJECT      ● SAVED
BUILD        ● WORKING
GITHUB       ○ OFFLINE
CLOUD        OFF
```

Indicators should be small and non-distracting.

Do not use flashing or decorative status lights.

---

## 15. Dark Mode

Dark mode should resemble a dim professional workstation/edit room.

Use:

- charcoal
- warm off-white
- graphite
- muted amber
- muted green

Avoid:

- pure-black sci-fi UI
- neon accents
- glowing borders
- cyberpunk visual language

The feeling should be:

**the room lights were lowered**

not:

**the software became futuristic**

---

## 16. Motion

Keep animation minimal.

Appropriate:

- subtle panel transitions
- button press states
- short fades
- progress animation
- small status changes

Avoid:

- flying birds
- swooping transitions
- confetti
- bouncing controls
- exaggerated spring animations

The projects should provide the excitement, not the shell application.

---

## 17. Sound

The application should normally be silent.

Do not add thematic:

- bird calls
- tape sounds
- CRT sounds
- fake keyboard sounds
- startup jingles

Normal system feedback sounds may be considered later if useful.

---

## 18. Application Icon

The app icon may subtly reference the name without literally depicting an eagle.

Preferred concepts:

- abstract nest viewed from above
- concentric open rings
- an incomplete circular structure
- a small central project/egg shape
- negative space forming a subtle `O`

Style:

- simple
- geometric
- warm neutral colors
- one restrained accent
- readable at small macOS sizes

Avoid:

- detailed bird nests
- literal eagle head
- wings
- feathers
- `AI` lettering

The icon should look like software, not a wildlife organization.

---

## 19. Wordmark

Preferred:

```text
OPEN NEST
```

Simple uppercase type with restrained spacing.

Optional secondary descriptor:

```text
OPEN NEST
PROJECT WORKSTATION
```

Do not brand the product as:

`Open Nest AI`

AI is part of the product, not the identity of the product.

---

## 20. Child-Facing Tone

UI copy should be short, calm, and confident.

Preferred:

> What do you want to make?

> Start with an idea.

> Your game is ready.

> I found a problem.

> Try it again.

> Saved.

Avoid:

> Let's soar!

> Ready for takeoff!

> Spread your wings!

> Awesome job, young coder!

> Let's go on an amazing coding adventure!

The Flying Eagle influence should remain beneath the surface.

---

## 21. Internal Naming Convention

Where the existing implementation has not yet locked naming, use:

```text
Build Lab      → Open Nest
BuildLab       → OpenNest
buildlab       → opennest
.buildlab      → .opennest
```

Preferred launchers:

```text
Setup Open Nest.command
Launch Open Nest.command
```

Future application bundle:

```text
Open Nest.app
```

Preferred repository name:

```text
open-nest
```

---

## 22. Design Rule

The interface should feel like a **forgotten early-'90s creative workstation that was continuously refined instead of replaced**.

The retro influence should come from:

- proportion
- typography
- restrained colors
- control shapes
- equipment-like labeling
- interface hierarchy

Not from decorative nostalgia effects.

Open Nest should ultimately feel:

**serious enough to be a real tool, simple enough for a kid to own it.**
---

## 23. Precedence — amended in Phase 10

`brand_design_guide.md` was written after this document and is the newer, more specific
statement of the same design intent. **Where the two differ, the brand guide governs.**
Everything in §§2–22 that the guide does not contradict still stands, and most of the
guide extends this document rather than replacing it — its colour direction, its restraint
about mascots, and its "modern usability, not retro simulation" balance are all the same
position in more detail.

One substantive conflict, resolved by developer direction in Phase 10:

### The eagle activity indicator

§12 lists "eagle assistant" and "animated helper" under *Avoid*, and §16 lists "flying
birds" under motion to avoid. Brand guide §§34–37 specify a twelve-frame eagle wing-cycle
as the activity indicator.

**Ruling: use the eagle animation.** The older language was written to prevent a mascot
flying around the interface — swooping across screens, bouncing, orbiting controls. The
approved usage is much narrower, and the restrictions are what make it compatible:

- stationary in one location; only the wing poses animate
- used for loading, processing and waiting, never as decoration
- always paired with real status text, never the only signal
- shown only when work is genuinely taking long enough to justify it
- never moved spatially around the interface

It is **not** Gary, and it is not a mascot. Brand guide §47 keeps that separation: Gary has
no illustrated face, the symbols belong to Open Nest rather than to him, and he never
refers to them out loud.

So the semantic hierarchy is:

```text
Nest             identity / home
Eagle cycle      processing / activity
White sunglasses rare approval / completion
```

§12's substance survives intact — no mascot, no cartoon bird, no robot character, and the
assistant's visual treatment still matches the rest of the application. §16's substance
survives too: nothing swoops, bounces, or flies across anything.

### The application icon

§18's guidance still applies. Brand guide §31 mentions the nest for "future app icon
development" permissively, while §18 argues concretely against a detailed nest at small
macOS sizes. The legibility argument is the stronger one at 16 px, so icon work in 10D
follows §18.
