# Using a Plivo number for Caseline voice + SMS

This wires the Plivo number **+1 209 222 2430** into Caseline for **both**
inbound intake calls and outbound "Place a call", plus SMS. It's the Plivo
equivalent of `deploy/sip-outbound-trunk.md` (Twilio).

## How it fits together

```
                 ┌─────────── Plivo (owns the PSTN number) ───────────┐
   Caller  ──▶   │  Zentrunk INBOUND trunk  ──(SIP origination)──▶     │ ──▶ LiveKit inbound trunk
  dials the      │                                                    │        + dispatch rule
   number        │  Zentrunk OUTBOUND trunk ◀─(SIP termination)──      │ ◀── LiveKit outbound trunk
                 └────────────────────────────────────────────────────┘         (Place a call)
                                                                                        │
                                                              agent worker auto-joins the room
```

- **Voice** rides LiveKit SIP (same media plane as the browser widget), so the
  same agent worker handles phone + web.
- **SMS** goes through the app's messaging seam — already coded, see §4.

You need: the `lk` CLI (`brew install livekit-cli`), your `LIVEKIT_*` creds and
`PLIVO_*` values in `.env`, and a Plivo account with the number and **Zentrunk**
(SIP trunking) enabled.

> These steps touch billed telephony and your live accounts — run them
> yourself. In this session you can prefix a line with `!` to run it here
> (e.g. `! lk sip inbound list`).

---

## 1. Plivo console — create the OUTBOUND (termination) trunk

Plivo console → **Zentrunk → Outbound Trunks → Create**:

- **Name**: `caseline-outbound`
- **Secure** (auth): pick one —
  - **IP ACL**: whitelist LiveKit Cloud's egress IPs (simplest; get them from
    LiveKit support/docs), or
  - **Credentials**: create a SIP username/password (more portable — recommended).
- Note the **Termination SIP domain** Plivo shows, e.g. `caseline.zt.plivo.com`.

Put these in `.env` so the script (step 3) can build the matching LiveKit trunk:

```bash
PLIVO_SIP_TERMINATION=caseline.zt.plivo.com     # your termination domain
PLIVO_SIP_USERNAME=...        # only if you chose credential auth
PLIVO_SIP_PASSWORD=...        # only if you chose credential auth
```

## 2. Plivo console — enable the number for Voice + SMS

Plivo console → **Phone Numbers → your number**:

- **Voice**: leave it ready to attach to the inbound trunk (step 3b).
- **SMS**: ensure the number is SMS-enabled (it is, per the capabilities you
  chose at purchase).

## 3a. Run the script — creates the LiveKit trunks + dispatch rule

```bash
./scripts/plivo_trunk_setup.sh
```

It creates the LiveKit **inbound** trunk (bound to your number), a **dispatch
rule** (each caller gets a `call-*` room the agent auto-joins), and the
**outbound** trunk (pointed at `PLIVO_SIP_TERMINATION`), then writes
`CASELINE_SIP_OUTBOUND_TRUNK_ID=ST_...` into `.env`. It prints the **LiveKit
inbound SIP host** you need next (from `LIVEKIT_SIP_URI`).

> **Get `LIVEKIT_SIP_URI` from the LiveKit Cloud console → Settings → SIP URI**
> and put it in `.env`. It is **not** the media-URL subdomain — LiveKit Cloud's
> SIP host uses the *project-ID* subdomain, e.g. `sip:w75kzgln3ix.sip.livekit.cloud`.

## 3b. Plivo console — create the INBOUND (origination) trunk

Plivo console → **Zentrunk → Inbound Trunks → Create**:

- **Name**: `caseline-inbound`
- **Primary Origination URI**: your `LIVEKIT_SIP_URI`, e.g.
  `sip:w75kzgln3ix.sip.livekit.cloud` (LiveKit Cloud console → **Settings → SIP URI**).
- **Attach number**: add **+1 209 222 2430** to this inbound trunk.

Now a call to the number routes: Plivo → LiveKit inbound trunk → dispatch rule
→ room → agent.

## 4. SMS — already wired

The Plivo SMS adapter is in `api/messaging/__init__.py` and is auto-selected
when its credentials are present. Just fill the auth pair in `.env`:

```bash
PLIVO_AUTH_ID=...            # Plivo console > Account > Keys & Credentials
PLIVO_AUTH_TOKEN=...
PLIVO_FROM_NUMBER=+12092222430   # already set
```

Restart the backend; `make_sms_provider()` returns `PlivoSMSProvider` and the
agent's `send_sms` (booking confirmations) send from the Plivo number. Verify:

```bash
python -c "from dotenv import load_dotenv; load_dotenv(); \
  from api.messaging import make_sms_provider; print(make_sms_provider().name)"
# -> plivo
```

## 5. Run the workers and test end-to-end

```bash
# backend (serves /v1/calls/dial; picks up CASELINE_SIP_OUTBOUND_TRUNK_ID + Plivo SMS)
python -m uvicorn api.main:app --port 8000

# agent worker (joins the room and runs intake on both inbound + outbound)
python -m agent.agent dev
```

**Inbound:** call **+1 209 222 2430** from your phone — the agent greets you and
runs intake. The call, transcript, and per-turn latency show at
`/calls/<call_id>` in the dashboard.

**Outbound:** from the dashboard **Calls → Place a call**, or:

```bash
curl -s -X POST "$CASELINE_BACKEND_URL/v1/calls/dial" \
  -H "Authorization: Bearer $CASELINE_FIRM_TOKEN" -H "Content-Type: application/json" \
  -d '{"to_number":"+1YOURCELL","purpose":"plivo trunk smoke test"}'
# -> {"placed": true, "dialer": "livekit", ...}
```

## Production (Railway)

Set the same vars on the backend + agent services so it works off your machine:

```bash
railway variables --service backend --set CASELINE_SIP_OUTBOUND_TRUNK_ID=ST_... \
  --set PLIVO_AUTH_ID=... --set PLIVO_AUTH_TOKEN=... --set PLIVO_FROM_NUMBER=+12092222430
```

## Notes / gotchas

- **Not a LiveKit first-class provider.** LiveKit documents Twilio/Telnyx;
  Plivo works over generic SIP (this doc), but if inbound/outbound won't
  connect, the usual cause is the origination URI (3b) or the termination auth
  (IP-ACL vs credentials) not matching — check both sides.
- **Secrets:** the script writes temp trunk JSON under `.tmp/` (gitignored) and
  deletes it on exit; it holds the termination password. Never commit it.
- **Idempotency:** the script is not idempotent — re-running makes duplicate
  trunks. `lk sip inbound list` / `lk sip outbound list` then `... delete <id>`
  to clean up before re-running.
- **Region:** keep the agent worker + LiveKit in the same region (us-west) to
  hold per-turn latency inside the 800 ms budget.
- **TCPA:** outbound is operator-gated (firm token); the automated Lead Chaser
  still enforces consent + quiet hours (`api/compliance/outbound.py`).
