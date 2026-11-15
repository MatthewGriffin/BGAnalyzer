#!/usr/bin/env bash
# Start BGAnalyzer from any working directory using its local environment.
set -euo pipefail

launcher_path="$(readlink -f -- "${BASH_SOURCE[0]}")"
project_dir="$(dirname -- "$launcher_path")"
cd -- "$project_dir"

if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    printf 'BGAnalyzer needs its Python environment. In %s, run: uv sync --locked\n' "$project_dir" >&2
    exit 1
fi

exec "$project_dir/.venv/bin/python" -m bganalyzer "$@"
