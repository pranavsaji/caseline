// Route handler: the config studio posts test-call previews here; the
// server-side firm token performs the authed call. The credential never
// reaches the client.
import { NextRequest, NextResponse } from "next/server";
import { previewTestCall } from "@/lib/api";

export async function POST(req: NextRequest) {
  try {
    const { agent_id, ...body } = await req.json();
    if (!agent_id) {
      return NextResponse.json({ error: "agent_id required" }, { status: 400 });
    }
    return NextResponse.json(await previewTestCall(agent_id, body));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
