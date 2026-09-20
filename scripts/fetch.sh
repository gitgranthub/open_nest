#!/bin/bash
# Phase 1 of the two-phase workflow: fetch pinned artifacts, with network.
#
#   scripts/fetch.sh model qwen3-4b-instruct
#   scripts/fetch.sh deps
#
# This is the ONLY script that is allowed to reach the internet. Everything downloaded
# here is subsequently exercised under scripts/offline.sh, which has no network at all.
#
# Artifacts are pinned: models to the commit SHA recorded in opennest/config/models.json,
# Python packages to the constraints in requirements/. Nothing tracks a moving branch.
# Everything lands inside .opennest-sandbox/ and nowhere else on this Mac.

set -eu

REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/.." && pwd))"
cd "$REPO"
# shellcheck source=/dev/null
source scripts/sandbox.sh >/dev/null

case "${1:-}" in
    model)
        [ $# -ge 2 ] || { echo "usage: scripts/fetch.sh model <model-id>" >&2; exit 64; }
        PYTHONPATH="$REPO" HF_HUB_DISABLE_PROGRESS_BARS=1 \
            .venv/bin/python spikes/download_model.py "$2"
        ;;
    deps)
        .venv/bin/python -m pip install -r requirements/base.txt \
                                        -r requirements/macos-apple-silicon.txt \
                                        -r requirements/dev.txt
        ;;
    *)
        echo "usage: scripts/fetch.sh {model <id>|deps}" >&2
        exit 64
        ;;
esac

echo
echo "Fetched into $OPENNEST_HOME"
du -sh "$OPENNEST_HOME" 2>/dev/null
echo "Now test it offline:  scripts/offline.sh .venv/bin/python -m pytest"
