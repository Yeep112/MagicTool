#!/bin/bash
# Developer (macOS): upload this version to GitHub — same as publish.bat on Windows.
# Runs the release check first (opens the program window and measures smoothness).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$HERE/run_magic.command" publish
