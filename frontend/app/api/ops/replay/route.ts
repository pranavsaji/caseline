// Route handler: replay a dead-letter event (admin-token scoped, server-side).
import { NextRequest, NextResponse } from "next/server";
import { replayEvent, adminEnabled } from "@/lib/api";

export async function POST(req: NextRequest) {
  try {
    if (!adminEnabled) {
      return NextResponse.json({ error: "admin token not configured" }, { status: 403 });
    }
    const { event_id } = await req.json();
    if (!event_id) {
      return NextResponse.json({ error: "event_id required" }, { status: 400 });
    }
    return NextResponse.json(await replayEvent(event_id));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
