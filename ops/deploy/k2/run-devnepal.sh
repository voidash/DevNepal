#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

github_env="${HOME}/.config/devnepal/github.env"
if [[ ! -r "${github_env}" ]]; then
  print -u2 "DevNepal GitHub environment is missing: ${github_env}"
  exit 1
fi

set -a
source "${github_env}"
set +a

cd "${HOME}/github/DevNepal"
exec /opt/homebrew/bin/uv run gunicorn \
  --bind 127.0.0.1:8000 \
  --workers 4 \
  --threads 2 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile - \
  config.wsgi:application
