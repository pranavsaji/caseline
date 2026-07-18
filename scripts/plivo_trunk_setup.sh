#!/usr/bin/env bash
# Provision the LiveKit side of the Plivo <-> LiveKit voice bridge for Caseline.
#
# Architecture (mirrors deploy/plivo-trunk.md):
#   Inbound  : caller dials the Plivo number -> Plivo Zentrunk INBOUND trunk
#              (origination) forwards SIP to LiveKit -> LiveKit inbound trunk +
#              dispatch rule spin up a room -> the agent worker auto-joins.
#   Outbound : dashboard "Place a call" -> LiveKit OUTBOUND trunk -> Plivo
#              Zentrunk OUTBOUND trunk (termination) -> PSTN, caller-ID = number.
#
# This script automates the LiveKit side only (inbound trunk, dispatch rule,
# outbound trunk) via the `lk` CLI — the reliable, fiddly part. The Plivo
# Zentrunk side (two trunks + attach the number) is done in the Plivo console;
# deploy/plivo-trunk.md walks through it. Run the Plivo OUTBOUND-trunk steps in
# that doc FIRST, because this script needs the Plivo termination domain (and,
# if you chose credential auth, the SIP user/pass) to build the LiveKit
# outbound trunk.
#
# Idempotency: NOT idempotent — re-running creates duplicate trunks. Run once;
# if you need to redo it, delete the old trunks (`lk sip inbound/outbound list`
# then `... delete <id>`) first.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a; source "$ROOT/.env"; set +a

# --- required env (LiveKit creds + our Plivo number) ---------------------------
: "${LIVEKIT_URL:?missing LIVEKIT_URL}"
: "${LIVEKIT_API_KEY:?missing LIVEKIT_API_KEY}"
: "${LIVEKIT_API_SECRET:?missing LIVEKIT_API_SECRET}"
: "${PLIVO_FROM_NUMBER:?missing PLIVO_FROM_NUMBER (the Plivo number, E.164)}"

# --- values you copy from the Plivo console (see deploy/plivo-trunk.md §1) -----
# Plivo Zentrunk OUTBOUND (termination) SIP domain, e.g. "caseline.zt.plivo.com".
: "${PLIVO_SIP_TERMINATION:?set PLIVO_SIP_TERMINATION to your Plivo Zentrunk termination domain (Plivo console > Zentrunk > Outbound Trunk). See deploy/plivo-trunk.md}"
# Optional: Plivo outbound-trunk credential auth. Leave empty to use IP-ACL auth
# on the Plivo side instead (whitelist LiveKit's egress IPs in the Plivo console).
PLIVO_SIP_USERNAME="${PLIVO_SIP_USERNAME:-}"
PLIVO_SIP_PASSWORD="${PLIVO_SIP_PASSWORD:-}"

command -v lk >/dev/null || { echo "ERROR: the 'lk' CLI is not installed (brew install livekit-cli)"; exit 1; }

# LiveKit Cloud inbound SIP URI — what Plivo's INBOUND trunk origination URI
# must point at (§3b in the doc). This is NOT derivable from LIVEKIT_URL: LiveKit
# Cloud's SIP host uses the PROJECT ID subdomain (e.g. w75kzgln3ix.sip.livekit
# .cloud), which differs from the media-URL subdomain. Copy it from the LiveKit
# Cloud console > Settings > SIP URI into LIVEKIT_SIP_URI in .env.
LK_SIP_HOST="${LIVEKIT_SIP_URI:-<set LIVEKIT_SIP_URI from LiveKit console > Settings > SIP URI>}"
LK_SIP_HOST="${LK_SIP_HOST#sip:}"  # strip scheme for display

TMP="$ROOT/.tmp"; mkdir -p "$TMP"
# The outbound config carries the termination password — keep it out of git and
# delete it on exit.
trap 'rm -f "$TMP"/plivo-lk-*.json' EXIT

echo "==> LiveKit: $LK_HOST"
echo "==> Number : $PLIVO_FROM_NUMBER"
echo "==> Plivo termination: $PLIVO_SIP_TERMINATION"
echo

# --- 1/3 Inbound trunk (accept calls to our number from Plivo) -----------------
echo "==> 1/3 Creating LiveKit INBOUND trunk"
cat > "$TMP/plivo-lk-inbound.json" <<JSON
{
  "trunk": {
    "name": "Caseline Plivo Inbound",
    "numbers": ["$PLIVO_FROM_NUMBER"]
  }
}
JSON
IN_OUT="$(lk sip inbound create "$TMP/plivo-lk-inbound.json" 2>&1)"; echo "$IN_OUT"
IN_ID="$(printf '%s' "$IN_OUT" | grep -oE 'ST_[A-Za-z0-9]+' | head -1)"
[ -n "$IN_ID" ] || { echo "FAILED to create inbound trunk"; exit 1; }
echo "    inbound trunk: $IN_ID"

# --- 2/3 Dispatch rule (route inbound calls into per-call rooms) ----------------
# "individual" + roomPrefix gives each caller their own room; the agent worker
# (registered with agent_name="" = automatic dispatch) auto-joins it and greets.
echo "==> 2/3 Creating dispatch rule"
# Use the CLI flags (--individual sets an individual-caller rule with a room
# prefix). The equivalent JSON body is rejected by `lk` with "missing rule".
DR_OUT="$(lk sip dispatch create --name "Caseline Plivo Dispatch" --trunks "$IN_ID" --individual "call-" 2>&1)"; echo "$DR_OUT"

# --- 3/3 Outbound trunk (LiveKit -> Plivo termination -> PSTN) ------------------
echo "==> 3/3 Creating LiveKit OUTBOUND trunk"
if [ -n "$PLIVO_SIP_USERNAME" ] && [ -n "$PLIVO_SIP_PASSWORD" ]; then
  AUTH_JSON=", \"auth_username\": \"$PLIVO_SIP_USERNAME\", \"auth_password\": \"$PLIVO_SIP_PASSWORD\""
else
  AUTH_JSON=""  # relying on Plivo IP-ACL auth (whitelist LiveKit egress IPs)
fi
cat > "$TMP/plivo-lk-outbound.json" <<JSON
{
  "trunk": {
    "name": "Caseline Plivo Outbound",
    "address": "$PLIVO_SIP_TERMINATION",
    "numbers": ["$PLIVO_FROM_NUMBER"]$AUTH_JSON
  }
}
JSON
OUT_OUT="$(lk sip outbound create "$TMP/plivo-lk-outbound.json" 2>&1)"; echo "$OUT_OUT"
OUT_ID="$(printf '%s' "$OUT_OUT" | grep -oE 'ST_[A-Za-z0-9]+' | head -1)"
[ -n "$OUT_ID" ] || { echo "FAILED to create outbound trunk"; exit 1; }
echo "    outbound trunk: $OUT_ID"

# --- Wire the outbound trunk id into .env (make_dialer() -> LiveKitSIPDialer) ---
if grep -q '^CASELINE_SIP_OUTBOUND_TRUNK_ID=' "$ROOT/.env"; then
  # portable in-place edit (macOS + GNU sed)
  sed -i.bak "s|^CASELINE_SIP_OUTBOUND_TRUNK_ID=.*|CASELINE_SIP_OUTBOUND_TRUNK_ID=$OUT_ID|" "$ROOT/.env" && rm -f "$ROOT/.env.bak"
else
  printf '\nCASELINE_SIP_OUTBOUND_TRUNK_ID=%s\n' "$OUT_ID" >> "$ROOT/.env"
fi

cat <<DONE

======================================================================
LiveKit side done.
  inbound trunk id : $IN_ID
  outbound trunk id: $OUT_ID  (written to .env as CASELINE_SIP_OUTBOUND_TRUNK_ID)

NEXT — finish the Plivo INBOUND trunk (Plivo console > Zentrunk > Inbound Trunk):
  * Origination "Primary URI": sip:$LK_SIP_HOST
  * Attach the number $PLIVO_FROM_NUMBER to that inbound trunk.
  (Confirm the SIP host above in the LiveKit Cloud console > Settings > SIP.)

Then restart the backend + agent worker and test — see deploy/plivo-trunk.md §5.
======================================================================
DONE
