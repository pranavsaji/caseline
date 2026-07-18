#!/usr/bin/env bash
# One-shot Twilio Elastic SIP Trunk setup for Caseline outbound calls.
# Drives Twilio's REST API with curl (the twilio CLI has a Node bug on this box).
# Idempotency: not fully idempotent — re-running creates duplicate trunks. Run once.
#
# Produces a Termination SIP URI + credential username/password that the LiveKit
# outbound trunk (step in deploy/sip-outbound-trunk.md) authenticates with.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a; source "$ROOT/.env"; set +a

: "${TWILIO_ACCOUNT_SID:?missing}"; : "${TWILIO_AUTH_TOKEN:?missing}"
AUTH="$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN"

# A unique termination domain (must be globally unique, end in .pstn.twilio.com).
# Suffix keeps it unique if "caseline-outbound" is already taken worldwide.
SUFFIX="$(openssl rand -hex 3)"
DOMAIN="caseline-out-${SUFFIX}.pstn.twilio.com"

# Termination auth credential LiveKit will present.
CRED_USER="caseline"
CRED_PASS="Cl$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9')9x"   # >=12 chars, mixed

echo "==> 1/3 Creating trunk (domain: $DOMAIN)"
TRUNK_JSON="$(curl -sS -X POST "https://trunking.twilio.com/v1/Trunks" \
  --data-urlencode "FriendlyName=Caseline Outbound" \
  --data-urlencode "DomainName=$DOMAIN" \
  -u "$AUTH")"
TRUNK_SID="$(printf '%s' "$TRUNK_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sid",""))')"
[ -n "$TRUNK_SID" ] || { echo "FAILED to create trunk:"; echo "$TRUNK_JSON"; exit 1; }
echo "    TrunkSid: $TRUNK_SID"

echo "==> 2/3 Creating credential list + credential"
CL_JSON="$(curl -sS -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/SIP/CredentialLists.json" \
  --data-urlencode "FriendlyName=Caseline LK Auth" -u "$AUTH")"
CL_SID="$(printf '%s' "$CL_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sid",""))')"
[ -n "$CL_SID" ] || { echo "FAILED to create credential list:"; echo "$CL_JSON"; exit 1; }
echo "    CredentialListSid: $CL_SID"

CRED_JSON="$(curl -sS -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/SIP/CredentialLists/$CL_SID/Credentials.json" \
  --data-urlencode "Username=$CRED_USER" \
  --data-urlencode "Password=$CRED_PASS" -u "$AUTH")"
printf '%s' "$CRED_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if d.get("sid") else 1)' \
  || { echo "FAILED to create credential:"; echo "$CRED_JSON"; exit 1; }

echo "==> 3/3 Attaching credential list to trunk termination"
ASSOC_JSON="$(curl -sS -X POST \
  "https://trunking.twilio.com/v1/Trunks/$TRUNK_SID/CredentialLists" \
  --data-urlencode "CredentialListSid=$CL_SID" -u "$AUTH")"
printf '%s' "$ASSOC_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if d.get("sid") else 1)' \
  || { echo "FAILED to attach credential list:"; echo "$ASSOC_JSON"; exit 1; }

OUT="$ROOT/.tmp/twilio-trunk.out"
mkdir -p "$ROOT/.tmp"
cat > "$OUT" <<EOF
TRUNK_SID=$TRUNK_SID
TERMINATION_URI=$DOMAIN
AUTH_USERNAME=$CRED_USER
AUTH_PASSWORD=$CRED_PASS
CALLER_ID=$TWILIO_FROM_NUMBER
EOF

echo
echo "================= DONE — Twilio side ready ================="
echo "  Termination URI : $DOMAIN"
echo "  Auth username   : $CRED_USER"
echo "  Auth password   : $CRED_PASS"
echo "  Caller ID (From): ${TWILIO_FROM_NUMBER:-<set TWILIO_FROM_NUMBER>}"
echo "  (also saved to .tmp/twilio-trunk.out — gitignored)"
echo "==========================================================="
