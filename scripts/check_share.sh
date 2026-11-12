#!/usr/bin/env bash
# End-to-end share-link check against a fresh app. Prints "share links OK" and exits 0 when it all holds.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=$(mktemp -d)
PORT=${PORT:-8765}
BASE="http://127.0.0.1:$PORT"
FERNPAGE_DB="$DIR/fp.db" uv run uvicorn app.main:app --port "$PORT" >"$DIR/server.log" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true; rm -rf "$DIR"' EXIT
for _ in $(seq 50); do curl -sf "$BASE/api/pages" >/dev/null && break; sleep 0.2; done
json() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
expect() { [ "$2" = "$3" ] || { echo "FAIL: $1: got $2, want $3"; exit 1; }; echo "ok: $1"; }

ID=$(curl -s -X POST "$BASE/api/pages" -H 'content-type: application/json' \
  -d '{"title":"Shared","body":"- [ ] a task"}' | json id)
TOKEN=$(curl -s -X POST "$BASE/api/pages/$ID/share" | json token)
expect "public page opens" "$(code "$BASE/s/$TOKEN")" 200
expect "shared title" "$(curl -s "$BASE/api/shared/$TOKEN" | json title)" Shared
expect "page id not exposed" "$(curl -s "$BASE/api/shared/$TOKEN" \
  | python3 -c 'import sys,json;print("id" in json.load(sys.stdin))')" False
expect "turn off" "$(code -X DELETE "$BASE/api/pages/$ID/share")" 204
expect "old link page gone" "$(code "$BASE/s/$TOKEN")" 404
expect "old link api gone" "$(code "$BASE/api/shared/$TOKEN")" 404
NEW=$(curl -s -X POST "$BASE/api/pages/$ID/share" | json token)
[ "$NEW" != "$TOKEN" ] || { echo "FAIL: new link equals the old one"; exit 1; }
echo "ok: new link differs"
expect "old link stays dead" "$(code "$BASE/s/$TOKEN")" 404
expect "new link opens" "$(code "$BASE/s/$NEW")" 200
echo "share links OK"
