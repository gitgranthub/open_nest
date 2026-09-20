#!/bin/bash
# Open Nest — setup launcher.
#
# Double-click this from Finder. It resolves the repository directory itself, so it does
# not matter what directory Terminal starts in. No administrator password is required.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1

TITLE="Open Nest Setup"

show_error() {
    /usr/bin/osascript -e "display dialog \"$1\" with title \"$TITLE\" buttons {\"OK\"} \
default button 1 with icon stop" >/dev/null 2>&1
    echo "$1" >&2
}

# Find a Python to run the bootstrap with. /usr/bin/python3 is a stub until the Command
# Line Tools are installed, and executing the stub pops an installer, so gate on that.
PYTHON=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -x "$candidate" ] && "$candidate" -c "import sys" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ] && /usr/bin/xcode-select -p >/dev/null 2>&1; then
    if [ -x /usr/bin/python3 ]; then
        PYTHON="/usr/bin/python3"
    fi
fi

if [ -z "$PYTHON" ]; then
    show_error "Open Nest could not find Python on this Mac.

Open the Terminal app, run this command, then try again:

    xcode-select --install"
    exit 1
fi

"$PYTHON" bootstrap/bootstrap.py --setup
status=$?

if [ $status -ne 0 ]; then
    echo ""
    read -r -p "Setup did not finish. Press Return to close this window. " _
fi

exit $status
