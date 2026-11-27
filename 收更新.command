#!/bin/bash
# Developer (macOS): receive the update Claude prepared - same as the .bat on Windows.
# pending branch -> cloud tests passed? -> apply -> open the window and measure smoothness -> publish.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$HERE/run_magic.command" receive
