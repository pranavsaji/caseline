// Route handler: browser posts config edits here; the server-side firm token
// performs the authed PUT. The credential never reaches the client.
import { NextRequest, NextResponse } from "next/server";
import { getAgentConfig, putAgentConfig } from "@/lib/api";

export async function GET() {
  try {
    return NextResponse.json(await getAgentConfig());
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}

export async function PUT(req: NextRequest) {
  try {
    const { agent_id, ...body } = await req.json();
    if (!agent_id) {
      return NextResponse.json({ error: "agent_id required" }, { status: 400 });
    }
    return NextResponse.json(await putAgentConfig(agent_id, body));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
