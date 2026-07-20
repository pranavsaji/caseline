// Access gate: EVERYTHING requires a valid signed session cookie. Unauthenticated
// page requests redirect to /login (preserving where they were headed via
// ?next=); unauthenticated /api requests get a 401 JSON so client fetches fail
// cleanly instead of receiving redirected HTML.
//
// The public surface is the marketing landing page plus what's needed to sign
// in. Self-serve signup is disabled, so /signup only 307s to /login.
//
// `/` is the cinematic marketing experience (and `/experience` forwards to it).
// Both are static marketing content that renders NO firm data, so they are safe
// to serve unauthenticated — that is the whole point, since prospects need to
// see it. Everything that touches tenant data — /dashboard, /calls, /threads,
// /analytics, /config, and every /api route except auth — stays gated.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { verifySessionToken, SESSION_COOKIE } from "./lib/session";

const PUBLIC_PATHS = ["/", "/experience", "/login", "/signup"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.includes(pathname) || pathname.startsWith("/api/auth/");
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (isPublic(pathname)) return NextResponse.next();

  const session = await verifySessionToken(req.cookies.get(SESSION_COOKIE)?.value);
  if (session) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname);
  return NextResponse.redirect(url);
}

export const config = {
  // Run on everything except Next internals and common static assets.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
