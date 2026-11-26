#!/usr/bin/env bash
# End-to-end smoke test of every major MeetMind feature against a running `docker compose` stack.
# Usage: ./scripts/smoke.sh            (expects API on :20701, web on :20700)
set -euo pipefail

API="${API_URL:-http://localhost:20701}"
WEB="${WEB_URL:-http://localhost:20700}"
V1="$API/api/v1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEMO="$ROOT/backend/app/seed_data/demo_meeting.wav"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0
FAIL=0
STAMP="$(date +%s)"

ok()   { PASS=$((PASS + 1)); printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad()  { FAIL=$((FAIL + 1)); printf '  \033[31m✘\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
check() { # check "<description>" <condition-command...>
  local desc="$1"; shift
  if "$@"; then ok "$desc"; else bad "$desc"; fi
}
req() { # req METHOD PATH TOKEN [curl args...] -> body in $TMP/body, status in $CODE
  local method="$1" path="$2" token="$3"; shift 3
  CODE=$(curl -sS -o "$TMP/body" -w '%{http_code}' -X "$method" "$V1$path" \
    ${token:+-H "Authorization: Bearer $token"} "$@")
}
body() { cat "$TMP/body"; }
jqb() { jq -r "$1" "$TMP/body"; }
wait_done() { # wait_done MEETING_ID TOKEN -> final status
  local id="$1" token="$2" status=""
  for _ in $(seq 1 120); do
    req GET "/meetings/$id/progress" "$token"
    status=$(jqb .status)
    [[ "$status" == "completed" || "$status" == "failed" ]] && break
    sleep 1
  done
  echo "$status"
}

step "1. Health"
check "API /health is ok (db, redis, storage)" bash -c "curl -fsS $API/health | jq -e '.status==\"ok\"' >/dev/null"
curl -sS "$API/health" | jq -c '.checks'
check "Web app serves /login" bash -c "curl -fsS -o /dev/null $WEB/login"
check "OpenAPI docs available" bash -c "curl -fsS $API/openapi.json | jq -e '.paths | length > 25' >/dev/null"
check "Security headers present" bash -c "curl -sSI $API/health | grep -qi 'x-content-type-options: nosniff'"

step "2. Auth (JWT + rotating refresh cookie)"
EMAIL="smoke-$STAMP@example.com"
req POST /auth/register "" -H 'Content-Type: application/json' -c "$TMP/jar" \
  -d "{\"email\":\"$EMAIL\",\"name\":\"Smoke Owner\",\"password\":\"smoke-pass-123\"}"
check "register -> 201" test "$CODE" = 201
TOKEN=$(jqb .access_token)
req POST /auth/refresh "" -b "$TMP/jar" -c "$TMP/jar"
check "refresh via httpOnly cookie -> 200" test "$CODE" = 200
TOKEN=$(jqb .access_token)
req GET /auth/me "$TOKEN"
check "GET /auth/me" test "$(jqb .email)" = "$EMAIL"
req GET /workspaces "$TOKEN"
WS=$(jqb '.[0].id')
check "personal workspace created (owner)" test "$(jqb '.[0].role')" = owner

step "3. Team workspace & RBAC"
VEMAIL="smoke-viewer-$STAMP@example.com"
req POST /auth/register "" -H 'Content-Type: application/json' -d "{\"email\":\"$VEMAIL\",\"name\":\"Smoke Viewer\",\"password\":\"smoke-pass-123\"}"
VTOKEN=$(jqb .access_token)
req POST "/workspaces/$WS/members" "$TOKEN" -H 'Content-Type: application/json' -d "{\"email\":\"$VEMAIL\",\"role\":\"viewer\"}"
check "invite teammate as viewer -> 201" test "$CODE" = 201

step "4. Upload -> FFmpeg normalise -> transcribe -> diarize -> summarise (live Socket.IO progress)"
node "$ROOT/scripts/socket-listen.mjs" "$API" "$TOKEN" "$WS" >"$TMP/events.log" 2>&1 &
LISTENER=$!
sleep 1.5
T0=$(date +%s.%N)
req POST "/workspaces/$WS/meetings" "$TOKEN" -F "file=@$DEMO;type=audio/wav" -F "title=Smoke Launch Planning"
check "upload demo audio -> 201" test "$CODE" = 201
MID=$(jqb .id)
STATUS=$(wait_done "$MID" "$TOKEN")
T1=$(date +%s.%N)
check "pipeline completed" test "$STATUS" = completed
printf '  pipeline wall time: %.2fs for 74.4s of audio\n' "$(echo "$T1 - $T0" | bc)"
sleep 1
kill "$LISTENER" 2>/dev/null || true
EVENTS=$(grep -c 'meeting:progress' "$TMP/events.log" || true)
check "received live Socket.IO progress events ($EVENTS)" test "$EVENTS" -ge 5
grep -o '"stage":"[a-z]*"' "$TMP/events.log" | tr '\n' ' ' | sed 's/"stage"://g'; echo
req GET "/meetings/$MID" "$TOKEN"
cp "$TMP/body" "$TMP/meeting.json"
check "3 speakers diarized" test "$(jqb '.speakers | length')" = 3
check "4 action items extracted" test "$(jqb '.insights.action_items | length')" = 4
check "2 decisions, open question found" test "$(jqb '(.insights.decisions | length) == 2 and (.insights.open_questions | length) >= 1')" = true
jq -r '"  summary: " + .insights.executive_summary' "$TMP/meeting.json"
jq -r '.insights.action_items[] | "  • " + .title + " — " + (.owner // "?") + " (due " + (.due_date // "-") + ")"' "$TMP/meeting.json"
jq -c '{stage_timings, stt_backend, diarizer_backend, llm_provider}' "$TMP/meeting.json"
req GET "/meetings/$MID/transcript" "$TOKEN"
check "speaker-labelled transcript (13 segments)" test "$(jqb length)" = 13
SPK=$(jq -r '.speakers[] | select(.display_name=="Speaker 2") | .id' "$TMP/meeting.json")
req PATCH "/meetings/$MID/speakers/$SPK" "$TOKEN" -H 'Content-Type: application/json' -d '{"display_name":"Marcus"}'
check "rename speaker" test "$(jqb .display_name)" = Marcus
AUDIO=$(jq -r .audio_url "$TMP/meeting.json")
RANGE_CODE=$(curl -sS -o /dev/null -w '%{http_code}' -H 'Range: bytes=0-1023' "$AUDIO")
check "audio streams with HTTP Range (206) for waveform seeking" test "$RANGE_CODE" = 206

step "5. Viewer permissions & tenant isolation"
req PATCH "/meetings/$MID" "$VTOKEN" -H 'Content-Type: application/json' -d '{"title":"hijack"}'
check "viewer cannot edit (403)" test "$CODE" = 403
req GET "/meetings/$MID" "$VTOKEN"
check "viewer can read (200)" test "$CODE" = 200
OEMAIL="smoke-outsider-$STAMP@example.com"
req POST /auth/register "" -H 'Content-Type: application/json' -d "{\"email\":\"$OEMAIL\",\"name\":\"Outsider\",\"password\":\"smoke-pass-123\"}"
OTOKEN=$(jqb .access_token)
req GET "/meetings/$MID" "$OTOKEN"
check "other tenant gets 404 (no IDOR)" test "$CODE" = 404

step "6. Task board"
req GET "/workspaces/$WS/action-items" "$TOKEN"
check "action items on board" test "$(jqb length)" = 4
ITEM=$(jqb '.[0].id')
req PATCH "/action-items/$ITEM" "$TOKEN" -H 'Content-Type: application/json' -d '{"status":"in_progress"}'
check "move card to in_progress" test "$(jqb .status)" = in_progress
req POST "/workspaces/$WS/action-items" "$TOKEN" -H 'Content-Type: application/json' -d '{"title":"Write launch FAQ","due_date":"2026-12-10"}'
check "create manual task" test "$CODE" = 201

step "7. Ask your meetings (RAG + timestamped citations)"
req POST "/workspaces/$WS/ask" "$TOKEN" -H 'Content-Type: application/json' -d '{"question":"What did we decide about pricing?"}'
check "answer cites the meeting" test "$(jqb '.citations | length > 0')" = true
jq -r '"  answer: " + (.answer | gsub("\n"; " ")) ' "$TMP/body"
jq -r '.citations[] | "  [\(.index)] \(.meeting_title) @ \(.start_s)s"' "$TMP/body"
req GET "/workspaces/$WS/search?q=press%20release" "$TOKEN"
check "semantic search (pgvector)" test "$(jqb 'length > 0')" = true

step "8. Export, share link, Slack"
req GET "/meetings/$MID/export?format=md" "$TOKEN"
check "Markdown export" grep -q "## Action items" "$TMP/body"
req GET "/meetings/$MID/export?format=pdf" "$TOKEN"
check "PDF export" bash -c "head -c4 $TMP/body | grep -q %PDF"
req POST "/meetings/$MID/share" "$TOKEN" -H 'Content-Type: application/json' -d '{"expires_in_days":7}'
SHARE=$(jqb .share_token)
req GET "/share/$SHARE" ""
check "public share link works without auth" test "$CODE" = 200
req DELETE "/meetings/$MID/share" "$TOKEN"
req GET "/share/$SHARE" ""
check "revoked share link -> 404" test "$CODE" = 404
req POST "/meetings/$MID/slack" "$TOKEN"
check "Slack post without webhook fails gracefully (422, not 500)" test "$CODE" = 422

step "9. Video & compressed formats via FFmpeg"
docker compose -f "$ROOT/docker-compose.yml" exec -T backend sh -c \
  'ffmpeg -loglevel error -y -f lavfi -i "sine=frequency=180:duration=6" -f lavfi -i "color=c=blue:s=160x120:d=6" -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac /tmp/smoke.mp4 && cat /tmp/smoke.mp4' >"$TMP/smoke.mp4"
req POST "/workspaces/$WS/meetings" "$TOKEN" -F "file=@$TMP/smoke.mp4;type=video/mp4" -F "title=Smoke video"
VID=$(jqb .id)
check "mp4 video processed (audio extracted)" test "$(wait_done "$VID" "$TOKEN")" = completed
printf 'garbage' >"$TMP/broken.mp3"
req POST "/workspaces/$WS/meetings" "$TOKEN" -F "file=@$TMP/broken.mp3;type=audio/mpeg"
BROKEN=$(jqb .id)
check "corrupt file fails cleanly (status=failed)" test "$(wait_done "$BROKEN" "$TOKEN")" = failed
req GET "/meetings/$BROKEN" "$TOKEN"
echo "  error: $(jqb .error | head -c 120)"

step "10. Worker outage: queued jobs survive and resume"
docker compose -f "$ROOT/docker-compose.yml" stop worker >/dev/null 2>&1
req POST "/workspaces/$WS/meetings" "$TOKEN" -F "file=@$DEMO;type=audio/wav" -F "title=Queued during outage"
QID=$(jqb .id)
sleep 2
req GET "/meetings/$QID/progress" "$TOKEN"
check "job waits in queue while worker is down" test "$(jqb .status)" = queued
docker compose -f "$ROOT/docker-compose.yml" start worker >/dev/null 2>&1
check "job completes after worker restart" test "$(wait_done "$QID" "$TOKEN")" = completed

step "11. Usage dashboard"
req GET "/workspaces/$WS/usage?days=7" "$TOKEN"
jq -c '.totals' "$TMP/body"
check "minutes transcribed recorded" test "$(jqb '.totals.minutes_transcribed > 2')" = true

step "12. Rate limiting"
LIMITED=0
for _ in $(seq 1 30); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$V1/auth/login" -H 'Content-Type: application/json' -d '{"email":"nobody@example.com","password":"x"}')
  [[ "$c" == 429 ]] && LIMITED=1 && break
done
check "brute-force login throttled (429)" test "$LIMITED" = 1

printf '\n\033[1mSmoke result: %d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
