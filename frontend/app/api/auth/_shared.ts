// Helpers shared by the auth route handlers: turn the api() client's thrown
// error (message shaped like `POST /path -> 409: {"detail":"..."}`) back into a
// clean { status, message } for the browser, and standard session-cookie flags.
import { SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/session";

export function parseApiError(err: unknown): { status: number; message: string } {
  const raw = String((err as Error)?.message ?? err);
  const status = Number(raw.match(/->\s*(\d{3})/)?.[1]) || 502;
  let message = "Something went wrong. Please try again.";
  const bodyMatch = raw.match(/->\s*\d{3}:\s*(.*)$/s);
  if (bodyMatch) {
    try {
      message = JSON.parse(bodyMatch[1]).detail ?? message;
    } catch {
      message = bodyMatch[1] || message;
    }
  }
  return { status, message };
}

export const sessionCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  maxAge: SESSION_MAX_AGE,
  secure: process.env.NODE_ENV === "production",
};

export { SESSION_COOKIE };
