// Verify credentials against the backend, then set the signed session cookie.
import { NextResponse } from "next/server";
import { loginUser } from "@/lib/api";
import { createSessionToken } from "@/lib/session";
import { parseApiError, sessionCookieOptions, SESSION_COOKIE } from "../_shared";

export async function POST(req: Request) {
  let email: string, password: string;
  try {
    ({ email, password } = await req.json());
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
  if (!email || !password) {
    return NextResponse.json({ error: "Email and password are required" }, { status: 400 });
  }
  try {
    const { email: authed } = await loginUser(email, password);
    const res = NextResponse.json({ ok: true, email: authed });
    res.cookies.set(SESSION_COOKIE, await createSessionToken(authed), sessionCookieOptions);
    return res;
  } catch (err) {
    const { status, message } = parseApiError(err);
    return NextResponse.json({ error: message }, { status });
  }
}
