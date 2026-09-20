# Build Lab "Open Nest"— macOS Local AI Builder

## Product Goal

Build a native-feeling macOS desktop application that allows a child to create small software, games, robotics projects, Arduino projects, automations, and research projects with the assistance of primarily local AI models.

The application should prioritize:

- Local AI running on Apple silicon
- Simple, visual project creation
- Kid-friendly language
- Safe and constrained code execution
- Different environments for different project types
- The ability to upload images, documents, diagrams, datasets, schemas, and other project assets
- Optional OpenAI and Anthropic cloud models under parent control
- Learning and explanation rather than simply generating code
- Persistent project memory across AI conversation threads
- Automatic project saving and invisible version control
- Guided installation and model setup from the downloaded/cloned repository
- Easy future expansion

Initial target hardware:

- Apple-silicon Mac
- 8 GB unified memory baseline
- macOS
- Python-based application
- PySide6 desktop UI

The product name can temporarily be **Build Lab**.

---

# 1. Core Technology

## Desktop application

Use:

- Python 3.12+
- PySide6
- Qt layouts and native macOS-friendly controls
- Async/background workers for model generation and project execution
- Python virtual environment managed by the application

The UI should remain responsive while:

- models load
- models generate responses
- code runs
- files import
- projects build
- external APIs respond
- project memory is updated
- autosave occurs
- Git snapshots or commits occur

---

# 2. AI Architecture

Use a provider abstraction so the rest of the application does not depend on a specific model service.

Conceptually:

```python
class ModelProvider:
    async def chat(
        self,
        messages,
        tools=None,
        attachments=None,
        settings=None
    ):
        ...
```

Initial providers:

```text
MLXLocalProvider
OpenAIProvider
AnthropicProvider
```

Additional providers should be easy to add later.

---

# 3. Local AI

The preferred local architecture is Apple's MLX ecosystem.

Use:

- MLX
- MLX-LM
- local MLX-compatible Hugging Face models

The application should manage local model loading behind the scenes.

The child should never need to use Terminal to start the model.

## Initial model choices

Provide a curated model list rather than exposing the entire Hugging Face catalog.

Initial options should include models in approximately the 3B–4B range appropriate for an 8 GB Apple-silicon Mac.

Suggested UI:

```text
LOCAL AI

Qwen 3.5 4B
Recommended for coding and building

Gemma 3 4B
Good general-purpose helper

Llama 3.2 3B
Fast and lightweight

+ Add Local Model
```

The underlying model definitions should be configuration-driven.

Example:

```json
{
  "name": "Qwen 3.5 4B",
  "provider": "mlx",
  "model_id": "...",
  "description": "Recommended for coding and building",
  "recommended_ram_gb": 8,
  "supports_images": false,
  "supports_tools": true
}
```

Do not hard-code individual model logic throughout the application.

---

# 4. Model Picker

Every project should have a visible model selector.

Example:

```text
AI Model
[ Qwen 3.5 4B — Local ▼ ]
```

The menu should clearly differentiate:

```text
ON THIS MAC

Qwen 3.5 4B
Gemma 3 4B
Llama 3.2 3B

CLOUD

OpenAI
Claude
```

Add visual indicators:

- Local
- Cloud
- Internet required
- Potential cost
- Image support, if applicable

The child does not need to see model parameter counts unless opening an advanced information view.

---

# 5. Project Types

Projects should use a configurable **Project Profile** system.

Initial project profiles:

```text
🎮 Games

🤖 Raspberry Pi & Robots

🔌 Arduino

🔬 Research

✨ Blank / Invent Something
```

Each profile should define:

- system prompt
- preferred languages
- starter files
- allowed tools
- package allowlist
- run command
- compile command
- asset types
- safety rules
- optional educational instructions
- suggested starter prompts

Example internal profile:

```json
{
  "id": "games",
  "name": "Games",
  "default_language": "python",
  "frameworks": ["pygame"],
  "tools": [
    "read_file",
    "write_file",
    "run_project",
    "inspect_error"
  ],
  "starter_template": "pygame_basic",
  "system_prompt": "..."
}
```

---

# 6. Games Profile

Primary environment:

- Python
- Pygame

Optionally support simple browser-based HTML/CSS/JavaScript games later.

Suggested starter ideas:

```text
Make a platform game

Make a space game

Make a maze

Make a racing game

Make something from my drawing
```

The AI should favor:

- playable prototypes
- simple mechanics
- short source files
- incremental improvements
- clear variable names

Avoid creating unnecessarily sophisticated architectures.

---

# 7. Raspberry Pi / Robotics Profile

Target:

- Raspberry Pi Python projects
- sensors
- LEDs
- buttons
- motors
- servos
- basic automation
- simple robots

Initial development can happen on the Mac even when hardware is not connected.

Projects should be exportable to the Raspberry Pi.

Future support may include:

- SSH deployment
- remote execution
- Raspberry Pi device profiles
- GPIO pin maps

The AI should explicitly distinguish:

```text
Code that can run on this Mac

Code that needs to run on the Raspberry Pi
```

Hardware instructions should remain conservative and child-appropriate.

---

# 8. Arduino Profile

Support Arduino sketches.

Primary outputs:

```text
project.ino
README.md
wiring.md
```

Future Arduino CLI integration should support:

- compile
- board selection
- serial port selection
- upload

Initially, compilation is more important than automatic uploading.

The AI should clearly explain:

- board pins
- wiring
- power
- inputs
- outputs

The AI should never silently invent uncertain pin assignments when hardware details are missing.

---

# 9. Research Profile

Allow projects involving:

- datasets
- CSV files
- spreadsheets
- images
- PDFs
- text documents
- observations
- charts
- experiments

Primary environment:

- Python
- pandas
- matplotlib

Optional later capability:

- notebook-like interface

The AI should help the child:

1. Form a question
2. Examine evidence
3. Write code
4. Visualize results
5. Explain findings

The emphasis should be curiosity rather than simply returning answers.

---

# 10. Asset Uploads and Project Files

This is a core requirement.

Users must be able to add external materials to a project.

Prominent UI:

```text
+ Add to Project
```

Supported initial categories:

### Images

- PNG
- JPEG
- WebP
- GIF where reasonable

Use cases:

- game character artwork
- reference imagery
- diagrams
- robot sketches
- screenshots
- textures
- UI ideas

### Documents

- TXT
- Markdown
- PDF
- CSV
- JSON
- YAML

### Code

- Python
- JavaScript
- HTML
- CSS
- Arduino `.ino`
- common configuration files

### Data

- CSV
- JSON
- text datasets

### Technical material

- schemas
- wiring diagrams
- specifications
- pinout diagrams
- API examples
- configuration files

Additional formats can be added later.

---

# 11. Asset Library

Each project should have an Assets section.

Example:

```text
PROJECT

Files
  game.py
  settings.py

Assets
  spaceship.png
  enemy.png
  level-map.jpg
  robot-wiring.pdf
  sensor-schema.json
```

Assets should physically live inside the project directory when practical.

Example:

```text
BuildLab/
  Projects/
    Asteroid Game/
      src/
      assets/
      data/
      docs/
      project.json
```

Do not depend on the original location of a user's file after import.

Copy imported assets into the project workspace.

---

# 12. Drag and Drop

Support drag-and-drop.

A user should be able to drag:

- image
- file
- PDF
- CSV
- source code
- diagram

directly into:

- the chat
- project file panel
- asset panel

The app should determine whether the upload is:

```text
Reference material

Project asset

Data

Source code
```

The user should be able to change the classification.

---

# 13. Using Assets With AI

Attachments should become part of the AI request when appropriate.

Example:

```text
Child:

Use this spaceship drawing as the player in my game.

[ spaceship.png ]
```

or:

```text
Here is the wiring diagram for my sensor.
Help me make the Arduino code.

[ sensor-diagram.png ]
```

or:

```text
Here is my CSV.
Graph the number of birds we counted each day.

[ observations.csv ]
```

Models without native vision should receive derived text or metadata rather than pretending they saw the image.

The application should know model capabilities.

Example:

```python
model.supports_images
model.supports_documents
model.supports_tools
```

If a selected local model cannot interpret an attachment, tell the user clearly and offer an appropriate compatible model.

---

# 14. Project Workspace

Main project window:

```text
┌────────────────────────────────────────────────────────────┐
│ BUILD LAB      Asteroid Game           Qwen 3.5 4B ▼      │
├────────────────┬───────────────────────────────┬───────────┤
│ PROJECT        │ BUILD / PREVIEW               │ ASSISTANT │
│                │                               │           │
│ game.py        │                               │           │
│ settings.py    │                               │           │
│                │                               │           │
│ Assets         │                               │           │
│ spaceship.png  │                               │           │
│ sound.wav      │                               │           │
│                │                               │           │
│ + Add          │                               │           │
├────────────────┴───────────────────────────────┴───────────┤
│ ▶ Run           Build style: [Teach me ▼]                 │
└────────────────────────────────────────────────────────────┘
```

Exact appearance is flexible.

Prioritize simplicity over IDE complexity.

---

# 15. AI Conversation

The assistant should behave more like a project partner than a chatbot.

Examples:

```text
What should we build?

What should happen when the player touches an asteroid?

I found an error. I'm fixing it.

Your game works now.

Want to make it harder?
```

Avoid overly technical language unless the child asks.

## 15A. Persistent Project Memory and Automatic Thread Rollover

Each project's AI conversations should use deliberately limited working context rather than allowing one chat thread to grow indefinitely.

The purpose is to:

- keep model prompts efficient
- prevent context degradation
- improve answer quality
- reduce local inference load
- reduce cloud-token usage
- preserve important project decisions
- allow a project to continue naturally for weeks or months

The child should experience this as one continuous project conversation.

The internal thread-management system should remain invisible during normal use.

### Project memory files

Each project should maintain internal Markdown memory files, including at minimum:

```text
.buildlab/
  project_bible.md
  project_state.md
```

These files are internal application state.

They should not normally appear in the child's project file browser.

### project_bible.md

`project_bible.md` should contain durable knowledge about the project.

Examples:

- what the project is
- project goals
- major design decisions
- characters or game rules
- hardware being used
- board type
- pin assignments
- important user preferences
- architecture decisions
- asset roles
- naming conventions
- things the child explicitly decided
- things that should not be changed
- lessons already established
- unresolved ideas worth retaining

Example:

```markdown
# Asteroid Game — Project Bible

## Goal
Make a simple arcade game where the player pilots a spaceship and avoids asteroids.

## Player
- Uses spaceship.png
- Arrow keys control movement
- Player has 3 lives

## Decisions
- Asteroids should get faster over time.
- Do not add shooting yet.
- Elliot prefers the dark-blue background.

## Assets
- assets/spaceship.png — player sprite
- assets/asteroid.png — asteroid sprite

## Future Ideas
- Score counter
- Power-ups
```

### project_state.md

`project_state.md` should describe the current technical state.

Examples:

- current entry point
- files currently in use
- current implementation status
- dependencies
- current errors
- incomplete tasks
- recent modifications
- next likely actions

Example:

```markdown
# Current Project State

## Working
- Main game loop
- Player movement
- Asteroid spawning
- Collision detection

## Current Files
- game.py
- settings.py

## Dependencies
- pygame

## Current Task
Increase asteroid speed as score rises.

## Known Problems
None.

## Last Successful Run
Game launched successfully.
```

### Memory update behavior

After meaningful conversation events, the agent should evaluate whether the memory needs updating.

Do not rewrite memory after every trivial chat message.

Update memory when something important changes, such as:

- project requirement
- implementation decision
- asset addition
- hardware configuration
- user preference
- major code change
- completed milestone
- unresolved issue
- important discovery

Memory updating should happen asynchronously or during idle moments when practical so it does not unnecessarily delay the visible conversation.

### Never rely entirely on model-generated summaries

Project memory should combine:

1. deterministic project facts from the application
2. source-controlled project metadata
3. AI-generated semantic summaries

For example, file names, package versions, model selection, successful run status, and Git state should be populated programmatically rather than asking the language model to remember them.

### Context budget

Each provider/model should define a safe conversation-context budget.

Example concept:

```python
context_policy = {
    "max_context_tokens": 16000,
    "rollover_threshold": 12000,
    "memory_reserved_tokens": 2500
}
```

Exact limits should depend on the selected model.

Do not wait until the model's absolute context-window limit is reached.

Roll over earlier while there is sufficient context to create a high-quality handoff.

### Automatic thread rollover

When the active conversation reaches its configured threshold:

1. Complete the current interaction normally.
2. Update `project_bible.md`.
3. Update `project_state.md`.
4. Generate a concise thread handoff summary.
5. Save the completed conversation.
6. Start a new internal conversation thread.
7. Load the project memory into the new thread.
8. Continue naturally.

The child should not have to press "New Chat."

Do not interrupt them with:

```text
Your context window is full.
```

or other implementation details.

### Thread archive

Conversation history should be preserved inside the project.

Example:

```text
.buildlab/
  conversations/
    thread_v01.jsonl
    thread_v02.jsonl
    thread_v03.jsonl
```

Optional human-readable summaries:

```text
.buildlab/
  conversations/
    thread_v01_summary.md
    thread_v02_summary.md
```

Use proper sequential numbering:

```text
v01
v02
v03
v04
```

rather than overwriting previous threads.

### New-thread bootstrap

A new thread should receive a compact beginning context composed from:

```text
Base system prompt
+
Project profile prompt
+
Build/Teach mode
+
project_bible.md
+
project_state.md
+
recent handoff summary
+
relevant current file information
```

Do not automatically inject every historical conversation.

Historical threads remain retrievable when needed but should not consume normal context.

### Memory retrieval

If a user references an older decision that is not present in the active thread, the agent may search:

```text
project_bible.md
project_state.md
conversation summaries
archived thread history
```

before telling the child that it does not remember.

### Memory compaction

As projects become large, periodically compact the project bible.

The goal is not endless accumulation.

Prefer:

- current truths
- durable decisions
- important history
- unresolved requirements

Remove or mark obsolete details when later decisions supersede them.

Where useful:

```markdown
## Superseded Decisions

- Original player speed was 5.
- Changed to 8 after play testing.
```

### Memory safety

The system must not store:

- API keys
- passwords
- Keychain contents
- tokens
- private credentials

inside project-memory Markdown files.

---

# 16. Build Modes

Provide:

```text
Build Style

● Just build it

○ Build it and teach me
```

## Just build it

Favor:

- action
- short explanations
- playable results

## Build it and teach me

Explain relevant concepts while developing.

Example:

```text
I created a variable called player_speed.

A variable is like a labeled box that holds information.

Try changing 5 to 8 and run the game again.
```

The teaching mode should encourage experimentation.

---

# 17. System Prompts

System prompts must be profile-specific.

They should be stored as external templates, not buried in UI code.

Example:

```text
prompts/
  base.txt
  games.txt
  raspberry_pi.txt
  arduino.txt
  research.txt
```

Prompt composition:

```text
Base safety + behavior prompt
        +
Project profile prompt
        +
Build style prompt
        +
Current project context
```

The current project context should be assembled from the persistent memory system described above rather than relying entirely on chat history.

---

# 18. Tool System

The AI must interact with projects through explicit tools.

Do not provide unrestricted shell access.

Initial tools:

```text
list_project_files()

read_file(path)

write_file(path, content)

create_directory(path)

delete_project_file(path)

run_project()

compile_project()

inspect_error()

list_assets()

read_text_asset()

get_project_info()
```

Internal agent tools may additionally include:

```text
read_project_memory()

update_project_bible()

update_project_state()

search_project_history()
```

These memory-management tools should not be presented as child-facing features.

Potential later tools:

```text
deploy_to_pi()

compile_arduino()

upload_arduino()

open_serial_monitor()
```

All paths must resolve inside the current project directory.

---

# 19. Execution Security

The AI must not receive unrestricted access to the Mac.

At minimum:

- restrict file operations to project folder
- prohibit `sudo`
- prohibit arbitrary filesystem deletion
- prohibit modifying system settings
- prohibit reading arbitrary home-directory files
- prohibit reading browser credentials
- prohibit reading Keychain
- prohibit arbitrary package installation
- prohibit unrestricted shell commands

Python execution should occur within the project's controlled environment.

Consider using:

- subprocess restrictions
- temporary execution directories
- command allowlists
- package allowlists
- timeouts

---

# 20. Python Packages

Provide a curated package set.

Initial allowlist might include:

```text
pygame
numpy
pandas
matplotlib
pillow
requests
```

Research carefully before expanding.

Projects should not arbitrarily execute:

```text
pip install <anything>
```

without parent approval.

---

# 21. Cloud AI

Support:

```text
OpenAI

Anthropic Claude
```

Cloud providers should use the same model-provider interface as local MLX models.

Cloud access must be optional.

The application must function without any cloud key.

---

# 22. API Keys

Create a Parent Settings section.

Example:

```text
PARENT SETTINGS

Cloud AI

OpenAI
✓ API key saved

Anthropic
Not configured
[ Add API Key ]

☑ Ask before using cloud AI
```

Store credentials in:

**macOS Keychain**

Never store API keys in:

- project files
- JSON configuration
- plaintext preferences
- logs
- prompts
- Git repositories
- project memory
- chat archives

---

# 23. Kid-Friendly API Explanation

Include:

```text
What is an API key?
```

Suggested explanation:

> An API key is a secret password that lets Build Lab use an AI service on the internet.
>
> A parent can add one here.
>
> You should never send an API key to another person or put it inside one of your projects.

---

# 24. Cloud Usage Warning

Before using a cloud model, when parental confirmation is enabled:

```text
USE CLOUD AI?

Claude uses the internet.

Information from this project may be sent to Anthropic.

Using Claude may also cost money.

[ Cancel ]

[ Use Claude ]
```

Similar language should be used for OpenAI.

Do not imply that cloud interactions remain completely on-device.

---

# 25. Parent Controls

Provide basic parent controls.

Possible settings:

```text
Allow cloud AI

Ask before cloud AI

Allow package installation

Allow external websites/API requests

Allow Arduino upload

Allow Raspberry Pi deployment
```

Parent Settings can use a lightweight PIN.

Do not over-engineer a full parental-control system for the first version.

---

# 26. Project Creation

New Project screen:

```text
What do you want to make?

🎮 Game

🤖 Raspberry Pi / Robot

🔌 Arduino

🔬 Research Project

✨ Something Else
```

Then:

```text
Tell me your idea.
```

Example:

```text
Make a game where a cat catches falling pizzas.
```

The AI should create a small functional first version rather than ask many preliminary questions.

---

# 27. Starter Ideas

Each project profile should provide idea cards.

Games:

```text
Space Game
Platform Game
Maze
Racing Game
Quiz Game
```

Robotics:

```text
Blink an LED
Motion Alarm
Robot Car
Distance Sensor
Weather Station
```

Arduino:

```text
Traffic Light
Servo Controller
Temperature Display
Button Game
```

Research:

```text
Analyze an Experiment
Graph a Dataset
Study Weather
Track Observations
Compare Results
```

---

# 28. Error Repair Loop

When code fails:

```text
Run project
   ↓
capture stdout/stderr
   ↓
send error + relevant code to model
   ↓
model proposes file changes
   ↓
apply allowed changes
   ↓
run again
```

Limit automatic retries.

Example:

```text
Maximum automatic repair attempts: 3
```

After that, explain the problem and ask the user what they want to do.

---

# 29. File Changes

Maintain basic change history.

Before AI modifications:

```text
snapshot project state
```

Allow:

```text
Undo last AI change
```

Eventually support:

```text
Project History
```

A lightweight Git-backed implementation is acceptable, but Git should remain invisible to the child unless Advanced Mode is enabled.

## 29A. Autosave and Git/GitHub Version Control

Project preservation should be automatic.

The child should never need to understand when to press Save.

### Autosave

Automatically save:

- source files
- imported assets
- project manifest
- project state
- project bible
- conversation state
- project settings

Autosave should occur after meaningful modifications and at short safe intervals.

Use atomic file writes where practical so a crash or power loss does not leave important project metadata partially written.

Maintain a dirty-state tracker so the application does not unnecessarily rewrite unchanged files.

### Recovery

On startup, detect interrupted sessions.

Where possible, offer automatic restoration:

```text
Your project was recovered.
```

Do not expose technical recovery mechanics to the child unless something actually requires attention.

### Local Git repository

Every Build Lab project should automatically initialize as a Git repository unless explicitly disabled in Parent/Advanced Settings.

The child should not have to know Git exists.

Example internal project structure:

```text
Asteroid Game/
  .git/
  .buildlab/
  src/
  assets/
  project.json
```

Build Lab should generate an appropriate `.gitignore`.

At minimum exclude:

- Python virtual environments
- caches
- temporary execution files
- ML models
- secrets
- credentials
- API keys
- generated build artifacts where appropriate

### Automatic commits

Build Lab may create automatic commits at meaningful checkpoints.

Do not commit after every keystroke.

Suitable checkpoints include:

- initial project creation
- successful first build
- successful AI modification
- imported major asset
- completed repair cycle
- milestone reached
- before substantial AI refactor
- before destructive operation
- thread rollover

Example internal commit messages:

```text
Build Lab: Initial project

Build Lab: Add asteroid spawning

Build Lab: Use custom spaceship asset

Build Lab: Working checkpoint before difficulty changes
```

These commits do not need to be shown to the child.

### Safe rollback

Git history should power:

```text
Undo last AI change
```

and potentially:

```text
Restore earlier version
```

The child-facing language should describe project versions rather than Git commits.

Example:

```text
Restore the version from before we added power-ups?
```

not:

```text
git reset --hard HEAD~2
```

### Git account settings

Settings should include an optional Git/GitHub area.

Example:

```text
PARENT SETTINGS

GitHub Backup

GitHub
✓ Connected

Account
grant-example

Automatic private backup
✓ Enabled

[ Disconnect ]
```

Prefer secure OAuth/device authorization where possible rather than asking users to paste a long-lived GitHub password or personal access token.

Credentials should be stored using secure macOS credential storage and never inside projects.

### GitHub repositories

When enabled by the parent, Build Lab may create a corresponding **private GitHub repository** for a project.

Private should be the default for child-created projects.

Do not automatically make repositories public.

Example:

```text
BuildLab-Asteroid-Game
```

The GitHub integration can provide:

- backup
- version history
- parent access
- future collaboration
- recovery across Macs

### Automatic push

When enabled:

```text
local autosave
   ↓
local Git commit
   ↓
background push to private GitHub repository
```

A temporary loss of internet should never block local development.

Queue pushes and retry later.

### Automatic branches and pull requests

Support optional advanced automation where substantial AI work occurs on a temporary branch.

Example:

```text
main
   ↓
buildlab/feature-powerups
   ↓
AI modifies project
   ↓
tests/run succeeds
   ↓
commit
   ↓
optional pull request
```

This should primarily exist for:

- parent review
- advanced users
- future collaborative workflows
- safer large refactors

It should not add visible complexity to the child's normal experience.

### PR policy

Automatic PR creation should be configurable.

Suggested modes:

```text
Off

Large changes only

Always create PR before merging AI changes
```

For the normal child experience, **Off** or **Large changes only** is preferable.

Small successful modifications can remain ordinary local commits.

### Git safety

Never automatically commit:

- API keys
- secrets
- credentials
- Keychain data
- cloud tokens

Before commits and pushes, perform secret scanning against known credential patterns.

If suspected secrets are found:

1. block the commit/push
2. remove or quarantine the secret where safe
3. notify the parent
4. do not expose the credential in logs

### Memory and Git

Internal project memory should also be versioned where useful.

This includes:

```text
project_bible.md
project_state.md
```

Conversation archives may be kept local by default rather than pushed to GitHub.

Provide a setting such as:

```text
Include AI conversation history in GitHub backup

○ No — recommended
○ Yes
```

The project bible and state file can normally be included because they are part of project continuity, but they must first be screened for credentials and sensitive content.

---

# 30. Preview / Run Experience

Games should launch easily:

```text
▶ Run Game
```

Research:

```text
▶ Run Analysis
```

Arduino:

```text
✓ Compile
```

Raspberry Pi:

```text
▶ Test on Mac
```

Later:

```text
Send to Raspberry Pi
```

Errors should appear in child-friendly language rather than raw tracebacks by default.

Provide:

```text
Show technical details
```

for deeper troubleshooting.

---

# 31. Project Manifest

Every project should contain metadata.

Example:

```json
{
  "name": "Asteroid Game",
  "profile": "games",
  "created": "...",
  "model": "qwen-local",
  "entrypoint": "game.py",
  "assets_directory": "assets",
  "build_style": "teach"
}
```

The manifest may additionally track internal continuity metadata such as:

```json
{
  "active_thread": 3,
  "last_successful_run": "...",
  "git_enabled": true,
  "github_backup": false
}
```

Do not store secrets in the manifest.

This will simplify future compatibility.

---

# 32. Settings

Settings sections:

```text
General

Local AI

Cloud AI

Parent Settings

Projects

Advanced
```

Parent/Advanced settings should also provide configuration for:

- GitHub account
- automatic Git commits
- private GitHub backups
- pull request policy
- conversation backup policy
- project-memory visibility for advanced users

Advanced settings may include:

- model context length
- model repository
- temperature
- local model storage
- MLX server information
- logs
- context rollover threshold
- memory compaction controls

Hide these from the default child experience.

---

# 33. Logging

Maintain internal logs for debugging.

Logs must not contain:

- API keys
- passwords
- Keychain contents
- GitHub credentials

Useful logs:

- model load failures
- tool calls
- build errors
- provider failures
- project execution errors
- context rollover events
- memory update failures
- Git commit failures
- GitHub backup failures

Provide:

```text
Export Diagnostic Log
```

for support.

---

# 34. Offline Behavior

The application should clearly identify whether something requires internet access.

Local development should continue to work without internet once models and dependencies are installed.

Example:

```text
Qwen 3.5 4B
● On this Mac
```

versus:

```text
Claude
☁ Internet
```

GitHub synchronization should also be non-blocking.

If offline:

- continue saving locally
- continue making local Git commits
- queue remote synchronization
- push when connectivity returns

---

# 35. First-Run Experience

The first launch should guide the parent through setup.

Suggested sequence:

```text
Welcome to Build Lab

1. Set up Local AI

2. Download recommended model

3. Create Parent PIN

4. Optional: Connect OpenAI

5. Optional: Connect Anthropic

6. Optional: Connect GitHub Backup

7. Make your first project
```

Downloading a model should display:

- download size
- progress
- disk usage
- cancel control

---

# 35A. Repository Launcher, Installation Wizard, and Guided Setup

The downloaded or cloned repository must include a simple launcher that allows a parent to install and configure Build Lab without manually assembling Python environments, MLX dependencies, local models, API credentials, or GitHub integration.

The intended experience is:

```text
git clone <Build Lab repository>

open the Build Lab setup launcher

follow the GUI wizard

launch Build Lab
```

The parent should not need to manually run a series of undocumented Terminal commands.

## Repository launcher

The repository must include a clearly named macOS launcher at the repository root.

Suggested options:

```text
Setup Build Lab.command
```

and optionally:

```text
Launch Build Lab.command
```

The setup launcher should:

- work when double-clicked from Finder
- resolve the repository directory automatically
- bootstrap the required Python environment
- install required dependencies
- launch the graphical setup wizard
- display a useful GUI error if setup cannot continue

The script should not assume that Terminal is already open in the repository directory.

Where macOS security requires the user to approve execution, provide a clear parent-facing explanation.

The launcher should not require `sudo` for normal installation.

---

## Setup architecture

The repository should contain a dedicated bootstrap layer separate from the main Build Lab application.

Suggested structure:

```text
BuildLab/
│
├── Setup Build Lab.command
├── Launch Build Lab.command
│
├── bootstrap/
│   ├── bootstrap.py
│   ├── environment.py
│   ├── dependency_check.py
│   ├── model_setup.py
│   ├── github_setup.py
│   └── installer_ui.py
│
├── buildlab/
│   └── ...
│
└── requirements/
    ├── base.txt
    └── macos-apple-silicon.txt
```

The bootstrap code should be capable of launching before the complete Build Lab environment exists.

Do not tightly couple the installer to the primary application runtime.

---

## Installation environment

The setup launcher should determine:

- macOS version
- Apple silicon availability
- available disk space
- available memory
- Python availability
- architecture
- existing Build Lab installation
- existing local model files
- Git availability
- GitHub CLI availability if used

The installer should target Apple silicon directly.

The wizard should warn if the computer does not meet supported requirements.

Example:

```text
BUILD LAB SETUP

Mac detected:
Apple silicon

Memory:
8 GB

Available storage:
126 GB

✓ This Mac can run Build Lab.
```

---

## Python environment

Build Lab should create and manage its own Python environment.

Do not depend on the child's global Python installation.

Preferred approach:

```text
BuildLab/
  .venv/
```

The setup process should:

1. Find a suitable Python version.
2. Install or guide installation if unavailable.
3. Create the virtual environment.
4. Upgrade required packaging tools.
5. Install Build Lab dependencies.
6. Verify imports.
7. Record the installed environment version.

The child should never need to know what a virtual environment is.

---

## Dependency installation

The installer should automatically install the packages required for Build Lab.

Examples:

```text
PySide6
mlx
mlx-lm
keyring
pygame
numpy
pandas
matplotlib
pillow
requests
```

Dependencies should use pinned or safely constrained versions.

Maintain a versioned dependency manifest.

Avoid blindly installing newest package versions every time Build Lab launches.

Setup should validate that important components can actually import before reporting success.

---

## Graphical setup wizard

After bootstrap succeeds, launch a PySide6 setup wizard.

Suggested flow:

```text
Welcome

→ About You

→ Local AI

→ Optional Cloud AI

→ GitHub Backup

→ Parent Settings

→ Test Setup

→ Finish
```

The wizard is intended for the parent, not the child.

---

## Step 1 — Welcome

Example:

```text
Welcome to Build Lab

Build Lab helps kids make games, robots,
Arduino projects, research projects, and more
with AI running primarily on this Mac.

We'll set everything up for you.

[ Get Started ]
```

Provide a concise explanation that most AI can operate locally and that cloud AI is optional.

---

## Step 2 — User identity

Collect basic non-sensitive project identity information.

Example:

```text
Who will use Build Lab?

Name:
[ Elliot ]

Git display name:
[ Elliot ______ ]

Git email:
[ __________________ ]
```

The child-facing display name and Git identity should be separate fields.

Git configuration should initially be scoped to Build Lab repositories when possible rather than silently modifying unrelated global Git configuration.

If no Git identity is supplied, Build Lab should still function locally.

---

## Step 3 — Local AI model setup

The wizard should inspect the hardware and recommend appropriate local models.

For the baseline 8 GB Mac:

```text
LOCAL AI

Recommended

✓ Qwen 3.5 4B
  Best choice for coding and building
  Approx. download: ___ GB

Optional

□ Gemma 3 4B
  Good general helper

□ Llama 3.2 3B
  Lightweight and fast
```

Actual model repository IDs and download sizes should come from the model configuration file rather than being hard-coded into wizard logic.

The user should be able to select:

```text
Install recommended model only

Install recommended + alternatives

Skip model installation for now
```

Skipping local AI should be allowed, but the wizard should clearly explain that Build Lab will require either a local model or configured cloud AI to provide AI assistance.

---

## Model installation

The installer must install MLX-compatible models in the correct managed location.

It should:

- create the model directory
- download the selected model
- validate model files
- display download progress
- show expected disk usage
- support cancellation
- support resume when possible
- detect an already downloaded valid model
- avoid downloading duplicate copies unnecessarily

Example:

```text
Installing Qwen 3.5 4B

Downloading...
████████████████░░░░  78%

3.1 GB of 4.0 GB

[ Cancel ]
```

Do not make the parent manually determine which Hugging Face quantization to install.

The application owns that decision through its curated model configuration.

---

## Model verification

After installation, run a lightweight inference test.

Example internal test:

```text
Respond with exactly:
BUILD LAB READY
```

Validate that:

- MLX loads
- model loads
- tokenizer loads
- inference completes
- memory usage does not immediately fail

The wizard should only mark the model as ready after this test succeeds.

Example UI:

```text
Qwen 3.5 4B

✓ Installed
✓ Loaded successfully
✓ Test response received
```

---

## Step 4 — Optional cloud AI

Cloud AI must remain optional.

Wizard:

```text
CLOUD AI

Build Lab can also use powerful AI services
on the internet.

You can skip this completely.

□ Enable OpenAI
□ Enable Anthropic Claude

[ Skip Cloud AI ]
```

If enabled, reveal API-key configuration.

---

## OpenAI setup

Example:

```text
OpenAI

API Key:
[ ••••••••••••••••••••• ]

[ Test Connection ]

✓ Connected
```

Include:

```text
What is an API key?
```

with the same kid/parent-friendly explanation defined elsewhere in this work order.

Store the credential immediately in macOS Keychain.

Do not save it in:

- installer logs
- project files
- `.env` files
- plaintext settings
- Git
- application configuration

---

## Anthropic setup

Use equivalent behavior:

```text
Anthropic Claude

API Key:
[ ••••••••••••••••••••• ]

[ Test Connection ]
```

Store securely in macOS Keychain.

---

## Cloud feature master switch

Setup must create a persistent parent-controlled option:

```text
Allow Cloud AI

ON / OFF
```

Default:

```text
OFF
```

unless explicitly enabled during setup.

This switch must also remain available later in:

```text
Settings → Parent Settings → Cloud AI
```

Turning cloud AI off should prevent OpenAI and Anthropic requests without requiring the stored keys to be deleted.

---

## Step 5 — Git and GitHub

Git functionality should be configured during setup but remain optional.

First detect whether Git is installed.

Example:

```text
VERSION HISTORY

✓ Git is installed

Build Lab automatically keeps safe versions
of every project on this Mac.
```

Local Git project history should work even without GitHub.

---

## GitHub account connection

Offer:

```text
GITHUB BACKUP

Would you like Build Lab to privately back up
projects to GitHub?

○ Not now
○ Connect GitHub
```

GitHub must not be mandatory.

If the user selects Connect GitHub, use a secure supported authorization workflow.

Prefer:

- OAuth
- GitHub device authorization
- GitHub CLI authentication when appropriate

Avoid requiring a manually created personal access token unless no better supported approach exists.

---

## GitHub connection flow

Example:

```text
Connect GitHub

1. A GitHub sign-in window will open.
2. Sign in to the parent's GitHub account.
3. Approve Build Lab.
4. Return here.

[ Connect GitHub ]
```

After completion:

```text
✓ GitHub connected

Account:
example-parent
```

Credentials/tokens must be stored securely.

---

## GitHub defaults

Wizard options:

```text
GitHub Backup

✓ Automatically create private repositories

✓ Automatically push safe checkpoints

□ Create pull requests for large AI changes

□ Include AI chat history in backups
```

Recommended defaults:

```text
Private repositories: ON

Automatic backup: ON if GitHub is connected

Automatic PRs: OFF

AI conversation history backup: OFF
```

---

## Commit identity

The wizard should configure project commit identity.

Example:

```text
COMMITS

Author name:
Elliot

Author email:
buildlab@example.com
```

Allow the parent to use:

- child's GitHub noreply address
- parent's preferred Git identity
- another suitable address

Do not expose this setting in the normal child workspace.

---

## Pull request behavior

During setup or Parent Settings, provide:

```text
AI CHANGE REVIEW

How should Build Lab handle large changes?

○ Save them normally

○ Create a review branch

○ Create a GitHub Pull Request
```

Default:

```text
Save them normally
```

PR functionality should exist but should not introduce complexity into the default child experience.

---

## Step 6 — Parent controls

Configure the parent PIN and initial permissions.

Example:

```text
PARENT SETTINGS

Create Parent PIN
[ •••• ]

Cloud AI
OFF

External internet requests
OFF

Package installation
Ask Parent

Arduino device upload
Ask Parent

Raspberry Pi deployment
Ask Parent

GitHub private backup
ON
```

These settings can be changed later.

---

## Step 7 — Installation test

Before finishing, run a setup health check.

Check:

```text
✓ Python environment

✓ PySide6

✓ MLX

✓ MLX-LM

✓ Local model

✓ Project directory

✓ Project sandbox

✓ macOS Keychain access

✓ Git

✓ GitHub connection, if enabled

✓ OpenAI, if enabled

✓ Anthropic, if enabled
```

Any optional unconfigured service should show:

```text
○ Not configured
```

rather than an error.

---

## End-to-end local AI test

The installer should perform one real local model request through the same provider code used by Build Lab.

Do not create a separate installer-only inference implementation.

This helps verify that the actual application path works.

---

## Step 8 — Finish

Example:

```text
BUILD LAB IS READY

Local AI
✓ Qwen 3.5 4B

Cloud AI
○ Not enabled

Version History
✓ Local Git

GitHub Backup
✓ Connected

Projects Folder
~/BuildLab/Projects

[ Launch Build Lab ]
```

---

## Installation state

Maintain a machine-level Build Lab configuration indicating setup status.

Example conceptual data:

```json
{
  "setup_complete": true,
  "schema_version": 1,
  "preferred_model": "qwen-local",
  "cloud_enabled": false,
  "github_enabled": true
}
```

Do not store secrets in this configuration.

Secrets belong in macOS Keychain.

---

## Relaunch behavior

After setup, the repository launcher should detect that installation already exists.

Instead of rerunning setup, it should launch Build Lab normally.

Conceptually:

```text
Setup Build Lab.command
        │
        ├── setup incomplete → Setup Wizard
        │
        └── setup complete → Build Lab
```

The separate:

```text
Launch Build Lab.command
```

may directly launch the installed environment.

---

## Repair setup

Provide:

```text
Settings → Advanced → Repair Installation
```

and allow the setup launcher to detect broken dependencies.

Repair should be able to:

- recreate the virtual environment
- reinstall required Python dependencies
- verify MLX
- verify models
- redownload missing model files
- rebuild launcher configuration
- recheck Git
- recheck Keychain
- preserve projects
- preserve project Git repositories
- preserve project memory
- preserve valid credentials

Do not delete projects during repair.

---

## Setup rerun

Allow:

```text
Settings → Parent Settings → Run Setup Again
```

This should allow the parent to:

- add another local model
- change the default model
- configure OpenAI
- configure Anthropic
- disable cloud AI
- connect GitHub
- disconnect GitHub
- change Git identity
- alter PR preferences
- change parent permissions

A full reinstall should not be necessary for these changes.

---

## Repository update behavior

Design the launcher so later versions can support safe application updates after:

```text
git pull
```

The next launch should detect:

- dependency manifest changes
- configuration schema changes
- model-definition changes

and perform required migrations before launching the app.

Example:

```text
Build Lab was updated.

A few components need to be refreshed.

[ Update Build Lab ]
```

The updater must preserve:

- projects
- Git history
- project memories
- assets
- settings
- Keychain credentials

---

## Development mode versus child mode

The repository should support two distinct launch concepts.

### Developer mode

Allows:

- verbose logs
- debug console
- development configuration
- direct Python launch
- advanced model controls

### Normal Build Lab mode

Provides:

- no Terminal dependency visible to child
- no debug console
- simplified interface
- normal safety controls

The setup launcher should configure normal Build Lab mode by default.

---

## Eventual macOS application bundle

The repository-based launcher is required for V1.

However, the architecture should allow later packaging as:

```text
Build Lab.app
```

using an appropriate packaging approach such as PyInstaller, Briefcase, or equivalent.

Do not architect the program in a way that requires the repository structure forever.

Long term, the ideal child-facing experience is:

```text
Applications
    └── Build Lab.app
```

while the repository remains the development and update source.

---

## Launcher Definition of Done

The installation system is complete when this sequence works on a newly prepared supported Mac:

1. Parent clones or downloads the Build Lab repository.
2. Parent opens:

```text
Setup Build Lab.command
```

3. A graphical installer appears.
4. The installer detects the Apple-silicon Mac.
5. It creates the Python environment.
6. It installs Build Lab dependencies.
7. It recommends the correct local model for the available hardware.
8. Parent selects Qwen.
9. Build Lab downloads the correct MLX model automatically.
10. The installer tests local inference.
11. Parent enters the child's display name.
12. Parent optionally configures OpenAI.
13. Parent optionally configures Anthropic.
14. API keys are stored in macOS Keychain.
15. Parent optionally connects GitHub.
16. Git identity is configured.
17. Private-repository backup preferences are configured.
18. Parent establishes initial permissions.
19. Setup runs its health checks.
20. Parent presses:

```text
Launch Build Lab
```

21. Build Lab opens ready to create a project.

22. The child never needed to:

- create a Python virtual environment
- install Python packages manually
- locate a Hugging Face model
- choose an MLX quantization
- type an MLX server command
- configure Git from Terminal
- configure GitHub credentials from Terminal
- create a `.env` file
- enter an API key into source code

The installation system should make cloning the repository effectively equivalent to installing a self-contained Build Lab development application.

---

# 36. Model Management

Settings → Local AI should allow:

```text
Installed Models

Qwen 3.5 4B
3.4 GB
[ Remove ]

Gemma 3 4B
Not installed
[ Download ]
```

The application should gracefully handle:

- interrupted download
- insufficient disk space
- model load failure
- unsupported architecture

---

# 37. Asset Intelligence

Build the asset subsystem so future capabilities can include:

- OCR
- image understanding
- PDF extraction
- schematic interpretation
- audio files
- 3D files
- SVG
- richer multimodal models

For V1, prioritize:

1. images
2. CSV
3. text/code
4. JSON/YAML
5. PDFs

---

# 38. Child Privacy

Default behavior should favor local operation.

Clearly communicate:

```text
Local AI

Your conversation and project stay on this Mac.
```

When switching to cloud AI:

```text
Cloud AI

This request may be sent over the internet.
```

Do not silently switch from a local model to a cloud provider.

Internal conversation archives should remain local by default.

GitHub backup should default to:

- private repositories
- source/project files
- project-memory files where appropriate
- no full AI conversation archives unless explicitly enabled by the parent

---

# 39. Architecture

Recommended high-level architecture:

```text
PySide6 Application
        │
        ├── UI Layer
        │
        ├── Project Manager
        │
        ├── Asset Manager
        │
        ├── Conversation Manager
        │       │
        │       ├── Context Budget
        │       ├── Thread Rollover
        │       ├── Thread Archive
        │       └── History Retrieval
        │
        ├── Memory Manager
        │       │
        │       ├── Project Bible
        │       ├── Project State
        │       ├── Memory Compaction
        │       └── Handoff Generator
        │
        ├── Agent Controller
        │       │
        │       ├── Prompt Manager
        │       ├── Tool Manager
        │       ├── Safety / Permission Layer
        │       └── Repair Loop
        │
        ├── Model Router
        │       │
        │       ├── MLX Local Provider
        │       ├── OpenAI Provider
        │       └── Anthropic Provider
        │
        ├── Execution Manager
        │
        ├── Version Manager
        │       │
        │       ├── Autosave
        │       ├── Local Git
        │       ├── Restore / Undo
        │       └── GitHub Sync / PR
        │
        ├── Credential Manager
        │       └── macOS Keychain
        │
        └── Project Storage
```

---

# 40. Suggested Source Structure

```text
buildlab/
│
├── app.py
│
├── ui/
│   ├── main_window.py
│   ├── new_project.py
│   ├── project_view.py
│   ├── chat_panel.py
│   ├── file_panel.py
│   ├── asset_panel.py
│   └── settings.py
│
├── ai/
│   ├── router.py
│   ├── provider.py
│   ├── mlx_provider.py
│   ├── openai_provider.py
│   └── anthropic_provider.py
│
├── agent/
│   ├── controller.py
│   ├── tools.py
│   ├── permissions.py
│   └── repair_loop.py
│
├── conversations/
│   ├── manager.py
│   ├── context_budget.py
│   ├── rollover.py
│   └── archive.py
│
├── memory/
│   ├── manager.py
│   ├── project_bible.py
│   ├── project_state.py
│   ├── compactor.py
│   └── history_search.py
│
├── projects/
│   ├── manager.py
│   ├── profiles.py
│   └── templates/
│
├── assets/
│   ├── manager.py
│   ├── image_handler.py
│   ├── document_handler.py
│   └── data_handler.py
│
├── execution/
│   ├── python_runner.py
│   ├── pygame_runner.py
│   └── arduino_runner.py
│
├── versioning/
│   ├── autosave.py
│   ├── git_manager.py
│   ├── github_manager.py
│   ├── checkpoint.py
│   └── secret_scanner.py
│
├── prompts/
│   ├── base.txt
│   ├── games.txt
│   ├── raspberry_pi.txt
│   ├── arduino.txt
│   └── research.txt
│
├── security/
│   ├── keychain.py
│   └── sandbox.py
│
└── config/
    ├── models.json
    └── profiles.json
```

Repository-level setup files should additionally include:

```text
BuildLab/
│
├── Setup Build Lab.command
├── Launch Build Lab.command
│
├── bootstrap/
│   ├── bootstrap.py
│   ├── environment.py
│   ├── dependency_check.py
│   ├── model_setup.py
│   ├── github_setup.py
│   └── installer_ui.py
│
└── requirements/
    ├── base.txt
    └── macos-apple-silicon.txt
```

---

# 41. V1 Scope

The first usable release should focus on:

### Required

- PySide6 desktop application
- repository setup launcher
- GUI installation/setup wizard
- Apple-silicon hardware detection
- managed Python virtual environment
- automatic dependency installation
- local model download and verification
- first-run parent setup
- New Project screen
- Games profile
- Raspberry Pi profile
- Arduino profile
- Research profile
- Blank profile
- MLX local model provider
- curated model picker
- Qwen local support
- Gemma local support
- OpenAI provider
- Anthropic provider
- optional cloud-AI master switch
- macOS Keychain API-key storage
- parent cloud controls
- project file browser
- asset import
- drag-and-drop assets
- image support
- text/document support
- CSV support
- PDF import
- safe project file tools
- Python execution
- Pygame execution
- error capture
- AI-assisted repair
- undo last AI change
- Just Build mode
- Teach Me mode
- project-specific system prompts
- automatic project autosave
- persistent `project_bible.md`
- persistent `project_state.md`
- context-budget management
- automatic conversation-thread rollover
- versioned conversation archives
- memory-based thread bootstrap
- local Git repository per project
- automatic checkpoint commits
- Git-backed restore/undo
- Git identity configuration during setup
- GitHub account connection in Parent Settings/setup wizard
- optional private GitHub backup
- optional automatic background push
- configurable PR behavior
- secret scanning before remote push
- offline Git queueing/retry
- installation health check
- repair-installation workflow
- setup rerun workflow
- safe update behavior after `git pull`

### V1.1 / Later

- Arduino CLI compilation
- Arduino upload
- Raspberry Pi deployment via SSH
- serial monitor
- browser-based games
- notebook interface
- multimodal local models
- richer visual previews
- advanced Git history UI
- automatic branch creation
- automatic GitHub pull requests
- parent review workflow for PRs
- native packaged `Build Lab.app`
- project sharing
- project templates marketplace
- voice interface

---

# 42. Definition of Done

A successful first release should allow the following scenario:

1. Parent clones or downloads the Build Lab repository.

2. Parent opens:

```text
Setup Build Lab.command
```

3. A GUI setup wizard appears.

4. The installer checks the Mac and identifies compatible hardware.

5. Build Lab creates and configures its own Python environment.

6. Build Lab installs its required dependencies.

7. The setup wizard recommends an appropriate local model.

8. Parent installs Qwen from inside the wizard.

9. Build Lab downloads the correct MLX-compatible model automatically.

10. Build Lab verifies that the model can load and produce an answer.

11. Parent enters the child's display name.

12. Parent optionally enables OpenAI.

13. Parent optionally enables Anthropic.

14. Any API keys are stored only in macOS Keychain.

15. Parent optionally connects GitHub.

16. Git identity is configured for Build Lab projects.

17. Parent optionally enables private GitHub backup.

18. Parent sets initial permissions.

19. Setup runs all health checks successfully.

20. Parent launches Build Lab.

21. Child creates:

```text
New Project → Game
```

22. Child types:

```text
Make a game where a spaceship moves around and avoids asteroids.
```

23. Build Lab creates the project.

24. Child presses:

```text
Run Game
```

25. The game launches.

26. Child drags a spaceship PNG into the project.

27. Child says:

```text
Use this picture for my spaceship.
```

28. AI updates the project.

29. Child says:

```text
Make the asteroids move faster.
```

30. AI updates and reruns the project.

31. Child presses:

```text
Undo
```

and the previous version returns.

32. Child creates a Research project and drops in a CSV.

33. Child asks:

```text
Graph this and tell me what changed the most.
```

34. Build Lab generates Python analysis and a chart.

35. Parent has optionally configured an Anthropic API key.

36. Child attempts to switch to Claude.

37. Build Lab displays the configured cloud-use warning or parent approval step.

38. At no point does the AI have unrestricted filesystem or shell access.

39. The child continues working on the same game across enough conversation that the original AI thread approaches its context threshold.

40. Build Lab automatically updates:

```text
project_bible.md
project_state.md
```

and archives:

```text
thread_v01
```

41. Build Lab automatically begins:

```text
thread_v02
```

using the project's persistent memory.

42. The child experiences no interruption and continues:

```text
Now let's add a boss level like we talked about before.
```

43. The new thread understands the relevant project decisions without replaying the entire original conversation.

44. Build Lab continuously saves the project locally.

45. Build Lab creates useful Git checkpoints without requiring the child to understand Git.

46. If GitHub backup is enabled, Build Lab synchronizes safe project checkpoints to a private repository.

47. If automatic PR behavior is enabled for large changes, Build Lab may create a review branch or pull request based on the configured parent policy.

48. Internet connectivity is temporarily lost.

49. Build Lab continues to work, save, create local commits, and use local AI normally.

50. When connectivity returns, queued GitHub synchronization resumes without disrupting the child's project.

51. The repository is later updated with:

```text
git pull
```

52. On next launch, Build Lab detects any dependency or configuration changes and safely updates itself without losing:

- projects
- assets
- Git history
- project memory
- settings
- Keychain credentials

53. The child never needed to:

- create a Python environment manually
- install Python packages manually
- choose an MLX quantization
- search Hugging Face for a compatible model
- run an MLX server from Terminal
- configure Git manually
- configure GitHub manually
- enter credentials into source files
- understand context windows
- manually save chats
- manually save project state
- manually create Git commits

---

# Product Principle

Build Lab should feel less like an IDE and more like:

**“I have an idea. Help me build it, run it, understand it, remember it, and make it better.”**

The complexity of Python environments, MLX, model loading, model downloads, context windows, memory summaries, conversation rollover, Git, GitHub, prompts, tools, APIs, installation, credentials, and project structure should remain mostly invisible until the user deliberately asks to see it.

The child's experience should stay simple.

The parent's experience should provide enough control, setup guidance, safety, backup, and transparency to trust the system.

The developer architecture should remain modular so local AI models, cloud providers, project types, execution environments, asset formats, and deployment targets can evolve independently.