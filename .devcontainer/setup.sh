#!/usr/bin/env bash
set -euo pipefail

task_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_repo_root"

# The app imports this file automatically; never load an existing configuration
# into the disposable review database or overwrite somebody's local settings.
if [[ -e env.py || -L env.py ]]; then
    echo "Review setup stopped: this checkout contains env.py. Use a fresh Codespace without that file."
    exit 1
fi

if [[ "${HAULAGE_REVIEW:-}" != "True" || "${DEVELOPMENT:-}" != "True" || \
      "${DB_URL:-}" != "postgresql://review:review@review-db:5432/haulage_review" ]]; then
    echo "Review setup stopped: use this repository's review dev container."
    exit 1
fi

python3 -c 'import sys; assert sys.version_info[:2] == (3, 11), "The review environment requires Python 3.11"'
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Recreate .venv with Python 3.11"'
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python tools/setup_review.py

echo "Review setup ready. Start the preview with: python3 run.py"
echo "Open port 8080 from the Ports tab and keep its Codespaces visibility Private."
