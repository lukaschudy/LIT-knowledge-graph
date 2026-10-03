#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -v
python3 -m atlas validate data/fixtures/atlas-demo.json
