// Who is signed in — reads the signed session cookie server-side (the cookie is
// httpOnly, so the client can't read it directly). Used by the shell to show the
// operator's email next to the sign-out button.
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { verifySessionToken, SESSION_COOKIE } from "@/lib/session";

export async function GET() {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const session = await verifySessionToken(token);
  if (!session) return NextResponse.json({ email: null }, { status: 401 });
  return NextResponse.json({ email: session.email });
}
