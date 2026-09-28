#!/bin/bash
# Open Nest — demo launcher, for testing on this Mac.
#
# Runs the app against the project's own sandbox folder (.opennest-sandbox), where Qwen3 4B
# is already downloaded, instead of the normal install in ~/Library/Application Support.
# The same command as HANDOFF.md section 2:
#
#     OPENNEST_HOME=$PWD/.opennest-sandbox .venv/bin/python -m opennest.app
#
# Not wrapped in scripts/offline.sh on purpose: the app confines the child's code with its
# own Seatbelt profile, and Seatbelt does not nest (HANDOFF.md section 4).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1

TITLE="Open Nest Demo"
SANDBOX="$HERE/.opennest-sandbox"

show_error() {
    /usr/bin/osascript -e "display dialog \"$1\" with title \"$TITLE\" buttons {\"OK\"} \
default button 1 with icon stop" >/dev/null 2>&1
    echo "$1" >&2
}

if [ ! -x ".venv/bin/python" ]; then
    show_error "Open Nest is not set up on this Mac yet.

Open \\\"Setup Open Nest.command\\\" first."
    exit 1
fi

if [ ! -d "$SANDBOX/models/models--mlx-community--Qwen3-4B-Instruct-2507-4bit" ]; then
    show_error "The demo model (Qwen3 4B) is not in .opennest-sandbox yet.

Fetch it first with: scripts/fetch.sh model qwen3-4b-instruct"
    exit 1
fi

export OPENNEST_HOME="$SANDBOX"
exec .venv/bin/python -m opennest.app
