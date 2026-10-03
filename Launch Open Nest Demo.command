#!/bin/bash
# Open Nest — demo launcher, for testing on this Mac.
#
# Runs the app against the project's own sandbox folder (.opennest-sandbox), where the demo
# model is already downloaded, instead of the normal install in ~/Library/Application Support.
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

export OPENNEST_HOME="$SANDBOX"

# The demo model is whatever the catalogue's default is (Gary Fast, the 4B vision model,
# since SPIKES.md section 32), asked through the app's own lookup rather than a folder
# name written here -- the folder this used to test was Qwen3 4B's.
MISSING="$(.venv/bin/python - <<'PY' 2>/dev/null
from opennest.ai.router import default_model_id, get_entry
from opennest.models.discovery import locate

entry = get_entry(default_model_id())
if locate(entry.model_id, entry.revision) is None:
    print(f"{entry.info.name}|{entry.info.id}")
PY
)"
if [ -n "$MISSING" ]; then
    show_error "The demo model (${MISSING%%|*}) is not in .opennest-sandbox yet.

Fetch it first with: scripts/fetch.sh model ${MISSING##*|}"
    exit 1
fi

exec .venv/bin/python -m opennest.app
