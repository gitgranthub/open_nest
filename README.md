# Open Nest

A Mac app where a child describes an idea and gets a real, running project: a game, a
website, an Arduino or Raspberry Pi project, a research project with charts, or
something else. **Gary**, the assistant, builds it with them, using AI that runs on the
Mac itself.

## Getting started

1. Clone or download this repository.
2. Open **Setup Open Nest.command** from Finder and follow the wizard.
3. Afterwards, open **Launch Open Nest.command**.

The wizard installs everything Open Nest needs, including its own Python, without
administrator access. It downloads and tests a local AI model, and asks a parent about
the optional parts: Arduino tools, cloud AI keys, a PIN, and what projects may do.
Projects are kept in `~/Open Nest/Projects`, outside this folder.

## The AI

Gary runs on this Mac. Setup offers two models, and both can see the pictures a child
adds:

- **Gary Fast**: suggested for Macs with 8 GB of memory (3.1 GB download).
- **Gary Smart**: stronger, for 16 GB or more (5.8 GB download).

A whole game is hard for Gary Fast, so Open Nest says so when a game is begun with it
and offers Gary Smart or a cloud model where the Mac can use one. Gary Smart writes a new
game whole, and Open Nest tests it before keeping it. A 3D game starts from
the 3D Block World: a first-person world of blocks you walk through.

Cloud AI (Claude, OpenAI) is optional, off by default, and turned on by a parent. Open
Nest never switches between local and cloud AI without saying so.

## Safe by default

- A child's code runs confined: no network, and writes only inside its project.
- Keys and the parent PIN live in the macOS Keychain, never in files.
- Open Nest checks what Gary says against what really happened: a change, a run, or
  what a picture shows.
- Projects save automatically and can be undone. They can be backed up privately to a
  parent's GitHub account.

## Updating

Settings → Advanced → **Check for Updates** tells you if there is a new version. Update
with `git pull` in this folder; the next launch finishes the job. Projects, settings and
keys are left as they are.

## Platform

macOS on Apple silicon, 8 GB of memory or more. Developers: see
[ONBOARDING.md](ONBOARDING.md).
