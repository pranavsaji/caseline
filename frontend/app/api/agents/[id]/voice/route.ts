// Route handler: assign a voice to an agent, server-side. Accepts either a
// ready cloned profile (voice_profile_id) or a provider preset (voice_id).
import { NextRequest, NextResponse } from "next/server";
import { assignAgentVoice } from "@/lib/api";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    const { voice_profile_id, voice_id } = await req.json();
    if (voice_id) return NextResponse.json(await assignAgentVoice(id, { voice_id }));
    if (voice_profile_id)
      return NextResponse.json(await assignAgentVoice(id, { voice_profile_id }));
    return NextResponse.json(
      { error: "voice_profile_id or voice_id required" },
      { status: 400 },
    );
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
