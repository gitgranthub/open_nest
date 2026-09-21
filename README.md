# Open Nest

Open Nest is a local-first project workspace that helps kids turn ideas into working software, games, robotics projects, Arduino projects, research projects, and other experiments with AI assistance.

The goal is simple:

> Have an idea, build it, run it, understand it, and keep making it better.

Open Nest is designed to hide the complicated parts of software development so kids can focus on creating.

## Getting Started

Open Nest installs itself. A parent needs no Terminal commands beyond cloning the
repository.

1. Clone or download this repository.
2. Open **Setup Open Nest.command** from Finder.
3. Follow the setup wizard.

The wizard checks the Mac, builds Open Nest its own Python environment, downloads and
tests a local AI model, and asks about the optional parts — Arduino tools, cloud AI
keys, a parent PIN and what projects are allowed to do. Nothing optional is required,
and nothing cloud-related is on until a parent turns it on.

Afterwards, **Launch Open Nest.command** opens the app directly. Running the setup
launcher again on a Mac that is already set up simply opens the app.

Projects are kept in `~/Open Nest/Projects`, outside this repository, so updating Open
Nest never touches them.

> Open Nest installs its own Python 3.12 if the Mac does not have one. It does not
> require administrator access and does not change any other Python on the machine.

## What You Can Build

Open Nest supports different kinds of projects, including:

- Games
- Raspberry Pi and robotics projects
- Arduino projects
- Research and data projects
- Pictures made with AI (needs a cloud provider a parent has enabled)
- Small software tools
- Experiments and original ideas

Each project gets its own workspace, files, assets, AI conversation, and project history.

## Local-First AI

Open Nest is built around AI models that can run directly on Apple silicon.

That means many projects can be created without sending conversations or project files to an external AI service.

Optional cloud AI providers can also be enabled by a parent when needed.

The app clearly distinguishes between AI running:

- on this Mac
- over the internet

Open Nest never silently switches from local AI to a cloud provider.

## Built for Kids

Open Nest is not meant to feel like a professional IDE.

Instead of requiring a child to understand terminals, Python environments, Git, package managers, model servers, or context windows, Open Nest manages those systems behind the scenes.

The normal workflow is closer to:

1. Choose what you want to build.
2. Describe your idea.
3. Let Open Nest create a small working version.
4. Run it.
5. Change it.
6. Add images, files, data, or hardware.
7. Keep improving it.

The app can also explain what it is doing along the way.

## Build or Learn

Open Nest supports two ways of working.

### Just Build

Focus on getting something working quickly with short explanations.

### Build + Teach

Build the same project while explaining useful programming, hardware, and research concepts along the way.

Kids can experiment with the code and see how their changes affect the project.

## Project Assets

Projects can include more than code.

Open Nest can work with materials such as:

- images
- PDFs
- CSV files
- text documents
- JSON and YAML
- diagrams
- source code
- wiring information
- project data

Files can be added directly to a project and used as part of the building process.

## Run What You Build

Open Nest is designed around making real things.

Depending on the project, kids can:

- run a game
- execute Python code
- analyze a dataset
- create charts
- test Raspberry Pi code on the Mac
- compile Arduino projects
- inspect and repair errors

When something breaks, Open Nest can examine the error, explain what happened, and attempt a safe repair.

## Projects Remember

Open Nest projects are designed to continue over time.

Important decisions, project state, assets, and progress are preserved so a child can return later and continue building without starting over.

Long AI conversations can be automatically continued behind the scenes without requiring the child to manage chat history or context limits.

## Automatic Saving and Project History

Projects save automatically.

Open Nest keeps useful project checkpoints so changes can be undone or older working versions can be restored.

Version control runs mostly in the background and does not require the child to understand Git.

Optional private GitHub backup is planned and is not available yet.

## Keeping Open Nest Up To Date

Settings → Advanced has **Check for Updates**. It asks GitHub whether a newer version
exists and tells you; it does not change anything on this Mac. Updating is a `git pull`
in the Open Nest folder, and the next launch finishes the job by itself — reinstalling
whatever changed and leaving projects, their history, what they remember, settings and
saved keys exactly as they were.

## Safe by Default

Open Nest is designed so AI does not receive unrestricted access to the computer.

Project tools are constrained to the current project workspace, and sensitive system areas remain protected.

Parent-controlled settings can manage features such as:

- cloud AI
- package installation
- internet access
- GitHub backup
- Arduino uploads
- Raspberry Pi deployment

Credentials are stored securely using macOS Keychain rather than inside project files.

## Offline-Friendly

Once the application and local AI models are installed, Open Nest can continue working without an internet connection for supported local projects.

Projects can still:

- save
- run
- use local AI
- create local checkpoints
- continue development

Online services can synchronize again when connectivity returns.

## Initial Platform

Open Nest currently targets:

- macOS
- Apple silicon
- Python 3.12+
- PySide6
- Apple MLX for local AI

The initial hardware target includes Macs with 8 GB of unified memory.

## Project Philosophy

Open Nest is built around a few ideas:

- Kids should be able to make real things.
- AI should help them think and build, not just return answers.
- Local AI should be useful without requiring an internet service.
- Technical complexity should stay out of the way until someone wants to see it.
- Projects should survive mistakes.
- Learning should happen naturally through making.
- A small working project is better than an over-engineered one.

Open Nest is a place to start with an idea and see how far you can take it.