#!/bin/bash
# Open Nest — launcher.
#
# Starts an installation that setup has already prepared. If Open Nest is not set up yet,
# this points at "Setup Open Nest.command" instead of trying to install anything.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1

TITLE="Open Nest"

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

exec .venv/bin/python bootstrap/bootstrap.py --launch
