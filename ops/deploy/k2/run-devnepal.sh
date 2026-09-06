#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

runtime_env="${HOME}/.config/devnepal/runtime.env"
if [[ ! -r "${runtime_env}" ]]; then
  print -u2 "DevNepal runtime environment is missing: ${runtime_env}"
  exit 1
fi

github_env="${HOME}/.config/devnepal/github.env"
if [[ ! -r "${github_env}" ]]; then
  print -u2 "DevNepal GitHub environment is missing: ${github_env}"
  exit 1
fi

github_private_key="${HOME}/.config/devnepal/github-app.pem"
if [[ ! -r "${github_private_key}" ]]; then
  print -u2 "DevNepal GitHub App private key is missing: ${github_private_key}"
  exit 1
fi

set -a
source "${runtime_env}"
source "${github_env}"
set +a
export GITHUB_APP_PRIVATE_KEY="${github_private_key}"

cd "${HOME}/github/DevNepal"
exec /opt/homebrew/bin/uv run gunicorn \
  --bind 127.0.0.1:8000 \
  --workers 4 \
  --threads 2 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile - \
  config.wsgi:application
