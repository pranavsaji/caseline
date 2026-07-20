// Route handler: delete a cloned voice profile server-side (firm token stays
// on the server). The backend clears the agent's voice first if it was in use.
import { NextResponse } from "next/server";
import { deleteVoiceProfile } from "@/lib/api";

export async function DELETE(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    return NextResponse.json(await deleteVoiceProfile(id));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
