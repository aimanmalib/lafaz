#!/usr/bin/env bash
# Run the test suite in a local uv virtualenv (.venv, ignored by git). Extra arguments go to pytest.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  uv venv -q --python 3.12 .venv
fi
uv pip install -q --python .venv/bin/python -r requirements-dev.txt
exec .venv/bin/python -m pytest "$@"
