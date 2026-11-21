#!/usr/bin/env bash
# Deploy Lafaz as one container behind the host's reverse proxy.
#   deploy/deploy.sh             build HEAD from a clean `git archive`, run it, install the route, verify
#   deploy/deploy.sh --rollback  run the previous image again (held by the stopped `lafaz-undo` container)
#   deploy/deploy.sh --status    container, tags, rollback image and the public health code
#
# Host values live in deploy/hos.env (not tracked; see deploy/hos.env.example). Keys stay in the file
# LAFAZ_ENV_FILE points to and reach the container as environment only: never the image, never the repo.
set -euo pipefail
cd "$(dirname "$0")"
[ -r hos.env ] || { echo "deploy/hos.env missing (copy deploy/hos.env.example)"; exit 1; }
# shellcheck disable=SC1091
. ./hos.env
: "${LAFAZ_DOMAIN:?}" "${LAFAZ_NETWORK:?}" "${PROXY_CONTAINER:?}" "${PROXY_DYNAMIC_DIR:?}" "${CERT_RESOLVER:?}"
BUILD_CMD=${BUILD_CMD:-docker build}
MIN_FREE_GB=${MIN_FREE_GB:-20}
LAFAZ_ENV_FILE=${LAFAZ_ENV_FILE:-}
[ -z "$LAFAZ_ENV_FILE" ] || [ -r "$LAFAZ_ENV_FILE" ] || { echo "LAFAZ_ENV_FILE is set but not readable"; exit 1; }
export LAFAZ_ENV_FILE LAFAZ_NETWORK
DC="docker compose -f compose.yaml"
URL="https://$LAFAZ_DOMAIN"
HOLDER=lafaz-undo

# Certificates use the HTTP-01 challenge: a name that does not resolve fails it for every name on the router.
dns_ok() { getent ahosts "$LAFAZ_DOMAIN" >/dev/null; }

code_of() { curl -s -m 20 -o /dev/null -w '%{http_code}' "$URL$1" || true; }

hold_previous() {  # $1 = image ID the replaced container ran: keep it by ID in a stopped container
  local prev id=${1:-}
  prev=$(cat PREVIOUS_TAG 2>/dev/null) || { echo "note: first deploy, no rollback image yet"; return 0; }
  [ -n "$id" ] || id=$(docker image inspect -f '{{.Id}}' "lafaz:$prev" 2>/dev/null) || id=""
  [ -n "$id" ] || { echo "WARNING: rollback image lafaz:$prev not found; --rollback will fail" >&2; return 1; }
  docker rm -f "$HOLDER" >/dev/null 2>&1 || true
  docker tag "$id" "lafaz:$prev"
  docker create --name "$HOLDER" --network none --restart no --label "lafaz.tag=$prev" "lafaz:$prev" >/dev/null
  echo "rollback image held: lafaz:$prev (${id:7:12})"
}

case "${1:-}" in
  --status)
    $DC ps
    echo "current $(cat CURRENT_TAG 2>/dev/null || echo -) · previous $(cat PREVIOUS_TAG 2>/dev/null || echo -)"
    docker inspect -f 'rollback holder: {{index .Config.Labels "lafaz.tag"}}' "$HOLDER" 2>/dev/null || echo "rollback holder: none"
    echo "public /healthz $(code_of /healthz)"; exit 0 ;;
  --rollback)
    dns_ok || { echo "$LAFAZ_DOMAIN does not resolve, nothing was changed"; exit 1; }
    TAG=$(cat PREVIOUS_TAG 2>/dev/null) || { echo "no PREVIOUS_TAG"; exit 1; }
    if ! docker image inspect "lafaz:$TAG" >/dev/null 2>&1; then
      id=$(docker inspect -f '{{.Image}}' "$HOLDER" 2>/dev/null) || { echo "image lafaz:$TAG is gone"; exit 1; }
      docker tag "$id" "lafaz:$TAG"
    fi
    [ -r CURRENT_TAG ] && cp CURRENT_TAG PREVIOUS_TAG ;;
  "")
    dns_ok || { echo "$LAFAZ_DOMAIN does not resolve: create the DNS record first, nothing was changed"; exit 1; }
    [ -z "$(git -C .. status --porcelain)" ] || { echo "working tree not clean: commit first (the image is built from HEAD)"; exit 1; }
    free=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
    [ "$free" -ge "$MIN_FREE_GB" ] || { echo "less than ${MIN_FREE_GB} GB free on /, stopping"; exit 1; }
    TAG=$(git -C .. rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M)
    ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
    git -C .. archive HEAD | tar -x -C "$ctx"   # clean tree: untracked and ignored files never reach the image
    $BUILD_CMD -t "lafaz:$TAG" "$ctx"
    [ -r CURRENT_TAG ] && cp CURRENT_TAG PREVIOUS_TAG ;;
  *) echo "usage: deploy.sh [--rollback|--status]"; exit 2 ;;
esac

old_id=$(docker inspect -f '{{.Image}}' lafaz 2>/dev/null || true)
docker volume create lafaz-data >/dev/null   # external in compose.yaml: `compose down -v` never deletes the data

LAFAZ_TAG=$TAG $DC up -d --force-recreate lafaz
echo "$TAG" > CURRENT_TAG

route=$(mktemp)
sed -e "s|@DOMAIN@|$LAFAZ_DOMAIN|g" -e "s|@CERT_RESOLVER@|$CERT_RESOLVER|g" traefik.yaml.tmpl > "$route"
docker cp "$route" "$PROXY_CONTAINER:$PROXY_DYNAMIC_DIR/lafaz.yaml"; rm -f "$route"

for _ in $(seq 30); do [ "$(docker inspect -f '{{.State.Health.Status}}' lafaz)" = healthy ] && break; sleep 3; done
no_rollback=0; hold_previous "$old_id" || no_rollback=1

# Keep only the current and previous images of this project; the host disk is shared with other projects.
docker images lafaz --format '{{.Tag}}' | grep -vxF -e "$TAG" -e "$(cat PREVIOUS_TAG 2>/dev/null || echo -)" \
  | sed 's/^/lafaz:/' | xargs -r docker rmi >/dev/null 2>&1 || true

# A new route or certificate can take a little while: wait and retry before calling it a failure.
code=000
for _ in $(seq 6); do code=$(code_of /healthz); [ "$code" = 200 ] && break; sleep 10; done
enc=$(curl -s -m 20 -o /dev/null -D - -H 'Accept-Encoding: gzip, br' "$URL/" | tr -d '\r' \
  | awk -F': ' 'tolower($1)=="content-encoding"{print $2}')
echo "tag $TAG · public /healthz $code · / content-encoding ${enc:-none}"
[ "$code" = 200 ] || { echo "public health is not 200 yet: check the certificate and route; undo with deploy/deploy.sh --rollback"; exit 1; }
[ -n "$enc" ] || echo "WARNING: the home page is not compressed: check the compress middleware"
[ "$no_rollback" = 0 ] || { echo "live, but no rollback image is held (warning above)"; exit 1; }
