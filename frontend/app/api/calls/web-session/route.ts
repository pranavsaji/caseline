// Route handler: the Calls hub posts here to start a browser voice test. The
// server-side firm token authenticates; the backend mints a short-lived
// LiveKit token that the browser uses to join the room and talk to the agent.
// The firm credential never reaches the client.
import { NextResponse } from "next/server";
import { startWebSession } from "@/lib/api";

export async function POST() {
  try {
    return NextResponse.json(await startWebSession());
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
