// Clear the session cookie. The middleware will redirect to /login next request.
import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "../_shared";

export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  return res;
}
