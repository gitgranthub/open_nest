#!/bin/bash
# Contain every file this project touches under one directory.
#
#   source scripts/sandbox.sh
#
# Sets OPENNEST_HOME so Open Nest's own state (runtime, models, logs, projects) lands
# inside the sandbox, and redirects the third-party caches that would otherwise write to
# ~/.cache and ~/Library/Caches. Without the second part, "contained" would still mean
# several gigabytes of model blobs in the machine-wide Hugging Face cache.
#
# Everything is removable with:  rm -rf .opennest-sandbox
#
# Verify with:  python -m opennest.paths   and   scripts/sandbox.sh --check

# Resolve the repository root. git is authoritative; the ${BASH_SOURCE}/$0 dance differs
# between bash and zsh and got this wrong once already.
_sandbox_repo() {
    git rev-parse --show-toplevel 2>/dev/null && return
    cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd
}

SANDBOX="$(_sandbox_repo)/.opennest-sandbox"

# Open Nest's own state.
export OPENNEST_HOME="$SANDBOX"

# Third-party caches that default to machine-wide locations.
export HF_HOME="$SANDBOX/cache/huggingface"
export HF_HUB_CACHE="$SANDBOX/cache/huggingface/hub"
export HF_DATASETS_CACHE="$SANDBOX/cache/huggingface/datasets"
export PIP_CACHE_DIR="$SANDBOX/cache/pip"
export XDG_CACHE_HOME="$SANDBOX/cache/xdg"
export MPLCONFIGDIR="$SANDBOX/cache/matplotlib"

# Never let a model download reach outside the sandbox by accident.
export HF_HUB_DISABLE_SYMLINKS_IN_WINDOWS_WARNINGS=1

mkdir -p "$SANDBOX"/{cache,models,runtime,logs,projects,state}

if [ "${1:-}" = "--check" ]; then
    echo "OPENNEST_HOME  $OPENNEST_HOME"
    echo "HF_HUB_CACHE   $HF_HUB_CACHE"
    echo "PIP_CACHE_DIR  $PIP_CACHE_DIR"
    echo "XDG_CACHE_HOME $XDG_CACHE_HOME"
    echo
    du -sh "$SANDBOX" 2>/dev/null
else
    echo "Open Nest sandbox active: $SANDBOX"
fi
