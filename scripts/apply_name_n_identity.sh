#!/usr/bin/env bash
# Apply the Name_N identity fix to python/extract.py and python/build.py
set -euo pipefail
cd "$(dirname "$0")/.."
patch -p1 < patches/extract-name-n-identity.diff
patch -p1 < patches/build-name-n-identity.diff
echo "Applied. Run: PYTHONPATH=python python -m pytest python/tests/test_import_identity.py -q"
