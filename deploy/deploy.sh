#!/usr/bin/env bash
# Deploy (or roll back) images built by GitHub Actions:
#   deploy/deploy.sh                      # the current main of both repositories
#   deploy/deploy.sh <back-sha> <front-sha>   # exact commits, e.g. to roll back
# Copies compose.prod.yaml and the Caddyfile to the server, records the tags in the server's .env, pulls and
# restarts the stack. Migrations run in the app container's entrypoint before it starts serving.
set -euo pipefail

SERVER=${DEPLOY_SERVER:-deploy@185.233.44.60}
DIR=${DEPLOY_DIR:-/srv/dzen}

latest() { git ls-remote "https://github.com/sni10/$1.git" refs/heads/main | cut -f1; }
BACK=${1:-$(latest dzen-test-back)}
FRONT=${2:-$(latest dzen-test-front)}
for sha in "$BACK" "$FRONT"; do
  if [[ ! $sha =~ ^[0-9a-f]{40}$ ]]; then
    echo "usage: $0 [<back-sha> <front-sha>]  (full 40-char commit SHAs with images in ghcr.io/sni10)" >&2
    exit 1
  fi
done

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ssh "$SERVER" "test -f $DIR/.env" || { echo "$SERVER:$DIR/.env is missing (see .env.production.example)" >&2; exit 1; }
scp -q "$ROOT/compose.prod.yaml" "$SERVER:$DIR/compose.prod.yaml"
scp -q "$ROOT/docker/caddy/Caddyfile" "$SERVER:$DIR/Caddyfile"

ssh "$SERVER" bash -s -- "$DIR" "$BACK" "$FRONT" <<'REMOTE'
set -euo pipefail
cd "$1"
set_tag() { if grep -q "^$1=" .env; then sed -i "s/^$1=.*/$1=$2/" .env; else echo "$1=$2" >> .env; fi; }
set_tag BACK_TAG "$2"
set_tag FRONT_TAG "$3"
compose() { docker compose -f compose.prod.yaml "$@"; }
compose pull --quiet
compose up -d --remove-orphans --wait --wait-timeout 300
compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null || true
compose ps --format '{{.Service}}\t{{.Status}}'
REMOTE
echo "Deployed back ${BACK:0:7}, front ${FRONT:0:7}"
