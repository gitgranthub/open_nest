#!/bin/sh
# What git uses to ask Open Nest for the parent's GitHub credential.
#
# Git invokes this with the prompt as $1 ("Username for ..." / "Password for ...") and
# reads the answer from stdout. The values come from this process's environment, which
# opennest/versioning/git_manager.py sets for that one subprocess and nothing else.
#
# This is the whole point of the mechanism, measured in SPIKES.md section 17: the token
# never reaches .git/config, never reaches argv, and never reaches any file. The obvious
# alternative -- https://x-access-token:TOKEN@github.com/... as the remote URL -- was
# measured writing the token straight into .git/config, which WORKORDER_01 section 22
# forbids.
#
# This file holds no secret and is safe to read. It ships in the package rather than
# being written to a cache directory at run time, because git executes it: a file
# anything on the Mac could overwrite is a worse thing to hand to exec than one that
# arrives with the application.

case "$1" in
    Username*) printf '%s' "$OPEN_NEST_GIT_USER" ;;
    *)         printf '%s' "$OPEN_NEST_GIT_TOKEN" ;;
esac
