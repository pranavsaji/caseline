// Route handler: list provider preset/library voices server-side (firm token
// stays on the server). Feeds the agent voice picker alongside cloned voices.
import { NextResponse } from "next/server";
import { listVoiceLibrary } from "@/lib/api";

export async function GET() {
  try {
    return NextResponse.json(await listVoiceLibrary());
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
