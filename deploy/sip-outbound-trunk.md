# Provisioning a LiveKit SIP outbound trunk (real outbound calls)

The dashboard's **Place a call** button (`POST /v1/calls/dial`) and the Digital
Lead Chaser both dial through `api/telephony.py`. Until a SIP outbound trunk is
configured they use `LoggingDialer` (records intent, `placed:false`, no phone
rings). Set **one** environment variable — `CASELINE_SIP_OUTBOUND_TRUNK_ID` —
and `make_dialer()` switches to `LiveKitSIPDialer` and real calls connect.

You already have: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`. Below, LiveKit
originates the call and Twilio's Elastic SIP Trunk terminates it to the PSTN.

Run these yourself (they touch billed telephony + your accounts). In this
session, prefix a line with `!` to run it here, e.g. `! lk --version`.

## 0. Install the CLIs (one-time)

```bash
brew install livekit-cli        # the `lk` command
brew tap twilio/brew && brew install twilio
lk cloud auth                   # or: export LIVEKIT_URL/API_KEY/API_SECRET
twilio login                    # uses your Account SID + Auth Token
```

## 1. Create a Twilio Elastic SIP Trunk (PSTN termination)

```bash
# Create the trunk and capture its SID
twilio api trunking v1 trunks create \
  --friendly-name "Caseline Outbound" \
  --domain-name caseline-outbound.pstn.twilio.com

# Termination URI LiveKit will send calls to:
#   caseline-outbound.pstn.twilio.com
```

Add **Termination** auth (LiveKit authenticates to Twilio) and attach a caller
ID number. In the Twilio Console → Elastic SIP Trunking → your trunk:

- **Termination**: set a SIP URI (e.g. `caseline-outbound.pstn.twilio.com`) and
  create **Credential List** auth with a username/password (used in step 2), or
  an IP ACL for LiveKit's egress IPs.
- **Numbers**: assign your `TWILIO_FROM_NUMBER` as the outbound caller ID.

CLI equivalent for the credential list:

```bash
twilio api trunking v1 trunks credential-lists create \
  --trunk-sid <TRUNK_SID> --credential-list-sid <CL_SID>
```

## 2. Create the LiveKit outbound trunk

Save this as `sip-outbound-trunk.json` (fill in the Twilio termination URI +
credential-list user/pass from step 1, and your caller-ID number):

```json
{
  "trunk": {
    "name": "Caseline Twilio Outbound",
    "address": "caseline-outbound.pstn.twilio.com",
    "numbers": ["+1XXXXXXXXXX"],
    "auth_username": "<twilio-termination-username>",
    "auth_password": "<twilio-termination-password>"
  }
}
```

Create it and copy the returned trunk id (`ST_...`):

```bash
lk sip outbound create sip-outbound-trunk.json
# → SIPTrunkID: ST_xxxxxxxxxxxx
```

## 3. Wire it into Caseline

```bash
# Local dev (.env)
echo 'CASELINE_SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxx' >> .env

# Railway (backend service — where /v1/calls/dial runs)
railway variables --service backend --set CASELINE_SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxx
```

## 4. Run the agent worker (it answers the call in the room)

The dialer only places the SIP call; the intake brain runs in the LiveKit
agent worker, which must be online to join the room:

```bash
# Local
python -m agent.agent dev

# Railway — the second service from the same image already does this
#   (deploy/railway/start.sh with CASELINE_SERVICE=agent)
```

## 5. Verify end-to-end

```bash
curl -s -X POST "$CASELINE_BACKEND_URL/v1/calls/dial" \
  -H "Authorization: Bearer $CASELINE_FIRM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to_number":"+1YOURCELL","purpose":"trunk smoke test"}'
# → {"placed": true, "dialer": "livekit", "call_id": "outbound-manual-...", ...}
```

Your phone rings; the agent greets you and runs intake. The call, transcript,
and per-turn latency appear at `/calls/<call_id>` in the dashboard. From the UI,
the **Calls → Place a call** card does the same thing.

### Notes / gotchas
- Keep credentials in the Twilio Console / LiveKit trunk config — never commit
  `sip-outbound-trunk.json` (it holds the termination password). Add it to
  `.gitignore` or delete it after `lk sip outbound create`.
- TCPA: this manual endpoint is operator-gated (firm token) for calling known
  numbers (a partner firm, your own test line). The *automated* Lead Chaser
  still enforces prior-express-consent + quiet hours in `api/compliance/outbound.py`.
- Region: keep the agent worker and LiveKit in the same region (us-west) to hold
  per-turn latency inside the 800 ms budget (see `plan.md`).
```
