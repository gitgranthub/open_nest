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
        # projects.txt is the curated set a child's project may import. It is installed
        # here and by the bootstrap: without it no profile's starter template runs, and
        # Games looked fine only because a developer machine already had pygame.
        .venv/bin/python -m pip install -r requirements/base.txt \
                                        -r requirements/macos-apple-silicon.txt \
                                        -r requirements/projects.txt \
                                        -r requirements/dev.txt
        ;;
    arduino)
        # Pinned to a release tag and verified against the checksum Arduino publishes
        # alongside it. Never "latest": the same rule models.json follows for model
        # weights. Lands in $OPENNEST_HOME/tools, which is where paths.tools_dir()
        # looks, and every arduino-cli call afterwards is told to keep its data there
        # (it creates ~/Library/Arduino15 otherwise -- SPIKES.md section 14).
        ARDUINO_VERSION="1.5.1"
        case "$(uname -m)" in
            arm64) ARDUINO_ARCH="macOS_ARM64" ;;
            x86_64) ARDUINO_ARCH="macOS_64bit" ;;
            *) echo "Unsupported architecture $(uname -m)" >&2; exit 1 ;;
        esac
        TOOLS="$OPENNEST_HOME/tools"
        TARGET="$TOOLS/arduino-cli-$ARDUINO_VERSION"
        BASE="https://github.com/arduino/arduino-cli/releases/download/v$ARDUINO_VERSION"
        TARBALL="arduino-cli_${ARDUINO_VERSION}_${ARDUINO_ARCH}.tar.gz"

        if [ -x "$TARGET/arduino-cli" ]; then
            echo "arduino-cli $ARDUINO_VERSION already installed."
        else
            mkdir -p "$TARGET"
            echo "Fetching arduino-cli $ARDUINO_VERSION ($ARDUINO_ARCH)..."
            curl -fsSL -o "$TOOLS/$ARDUINO_VERSION-checksums.txt" \
                "$BASE/$ARDUINO_VERSION-checksums.txt"
            curl -fsSL -o "$TOOLS/$TARBALL" "$BASE/$TARBALL"

            EXPECTED="$(grep "$TARBALL" "$TOOLS/$ARDUINO_VERSION-checksums.txt" | awk '{print $1}')"
            ACTUAL="$(shasum -a 256 "$TOOLS/$TARBALL" | awk '{print $1}')"
            if [ -z "$EXPECTED" ] || [ "$EXPECTED" != "$ACTUAL" ]; then
                echo "Checksum mismatch for $TARBALL -- refusing to install." >&2
                rm -f "$TOOLS/$TARBALL"
                exit 1
            fi
            tar -xzf "$TOOLS/$TARBALL" -C "$TARGET"
            rm -f "$TOOLS/$TARBALL"
        fi

        # Board cores are a separate download and the only part that needs network at
        # compile time -- once installed, compiling is fully offline.
        echo "Installing the AVR board core (about 324 MB of tool data)..."
        ARDUINO_DIRECTORIES_DATA="$TOOLS/arduino-data" \
        ARDUINO_DIRECTORIES_USER="$TOOLS/arduino-user" \
        ARDUINO_DIRECTORIES_DOWNLOADS="$TOOLS/arduino-downloads" \
            "$TARGET/arduino-cli" core install arduino:avr
        ;;
    *)
        echo "usage: scripts/fetch.sh {model <id>|deps|arduino}" >&2
        exit 64
        ;;
esac

echo
echo "Fetched into $OPENNEST_HOME"
du -sh "$OPENNEST_HOME" 2>/dev/null
echo "Now test it offline:  scripts/offline.sh .venv/bin/python -m pytest"
