// Dashboard session: a stateless, HMAC-signed cookie so both the Edge
// middleware and Node route handlers can verify a login without a shared
// session store. Token format: `<base64url(payload)>.<base64url(hmac)>` where
// payload is `{ email, exp }`. Signed + verified with the Web Crypto API, which
// exists in both the Edge (middleware) and Node (route handler) runtimes.
//
// SESSION_SECRET must be set in production — a rotated secret invalidates all
// sessions. The dev fallback keeps local `next dev` working out of the box.

const SECRET = process.env.SESSION_SECRET ?? "caseline-dev-session-secret-change-me";
export const SESSION_COOKIE = "caseline_session";
export const SESSION_MAX_AGE = 60 * 60 * 24 * 7; // 7 days, in seconds

const encoder = new TextEncoder();

function toB64Url(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromB64Url(s: string): Uint8Array {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function sign(payloadB64: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(payloadB64));
  return toB64Url(new Uint8Array(sig));
}

// Constant-time string compare so signature checks don't leak via timing.
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export type Session = { email: string; firmId: string | null };

// firmId rides in the payload so every server-side request can scope itself to
// the signed-in operator's tenant without a per-request database lookup. The
// payload is signed but NOT encrypted — readable by anyone holding the cookie —
// so this must stay a plain tenant id and never a credential. Acting as the
// firm still requires the admin token, which lives only on the server.
export async function createSessionToken(
  email: string,
  firmId: string | null = null,
): Promise<string> {
  const payload = JSON.stringify({ email, firmId, exp: Date.now() + SESSION_MAX_AGE * 1000 });
  const payloadB64 = toB64Url(encoder.encode(payload));
  const sig = await sign(payloadB64);
  return `${payloadB64}.${sig}`;
}

export async function verifySessionToken(
  token: string | undefined | null,
): Promise<Session | null> {
  if (!token) return null;
  const [payloadB64, sig] = token.split(".");
  if (!payloadB64 || !sig) return null;
  const expected = await sign(payloadB64);
  if (!safeEqual(sig, expected)) return null;
  try {
    const { email, firmId, exp } = JSON.parse(
      new TextDecoder().decode(fromB64Url(payloadB64)),
    );
    if (!email || typeof exp !== "number" || Date.now() > exp) return null;
    // Sessions minted before firmId existed simply carry none — they fall back
    // to the deploy's default firm rather than being forced to re-authenticate.
    return { email, firmId: typeof firmId === "string" ? firmId : null };
  } catch {
    return null;
  }
}
