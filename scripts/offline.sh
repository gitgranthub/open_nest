#!/bin/bash
# Run a command with no network access and writes confined to this project.
#
#   scripts/offline.sh .venv/bin/python -m pytest
#   scripts/offline.sh .venv/bin/python spikes/spike_mlx.py
#
# Development workflow is two-phase, deliberately:
#
#   1. FETCH   (network on)  -- scripts/fetch.sh, pinned artifacts, checksums verified
#   2. TEST    (network off) -- this script, everything downloaded runs untrusted
#
# So a model, library, or generated child-project script cannot phone home, exfiltrate
# anything, or write outside the project no matter what it contains.
#
# Enforced by macOS Seatbelt (sandbox-exec). No root required. Apple marks sandbox-exec
# deprecated but it remains present and functional; it is a development control here, and
# WORKORDER_01 section 19 will need a comparable boundary for running child project code.

set -u

REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/.." && pwd))"
SANDBOX="$REPO/.opennest-sandbox"

if [ $# -eq 0 ]; then
    echo "usage: scripts/offline.sh <command> [args...]" >&2
    exit 64
fi

mkdir -p "$SANDBOX"

# Containment (where files go) on top of isolation (what the process may do).
export OPENNEST_HOME="$SANDBOX"
export HF_HOME="$SANDBOX/cache/huggingface"
export HF_HUB_CACHE="$SANDBOX/cache/huggingface/hub"
export PIP_CACHE_DIR="$SANDBOX/cache/pip"
export XDG_CACHE_HOME="$SANDBOX/cache/xdg"
export MPLCONFIGDIR="$SANDBOX/cache/matplotlib"

# Belt and braces: these make well-behaved libraries fail fast and loudly offline
# rather than hanging on a connection the sandbox is going to refuse anyway.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export NO_PROXY='*'

# The repo is importable without installing it, so spikes and tests can import opennest.
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"

PROFILE="(version 1)
(allow default)

; No network of any kind.
(deny network*)

; Writes only where this project owns the bytes.
(deny file-write*)
(allow file-write*
    (subpath \"$REPO\")
    (subpath \"$SANDBOX\")
    (subpath \"$TMPDIR\")
    (subpath \"/private/tmp\")
    (subpath \"/private/var/folders\")
    (literal \"/dev/null\")
    (literal \"/dev/stdout\")
    (literal \"/dev/stderr\")
    (regex #\"^/dev/tty\"))
"

exec /usr/bin/sandbox-exec -p "$PROFILE" "$@"
