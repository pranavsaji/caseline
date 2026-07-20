// Route handler: operator-initiated hang up of a live call. The firm token
// performs the authed teardown on the server; the credential never hits the client.
import { NextResponse } from "next/server";
import { hangupCall } from "@/lib/api";

export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    return NextResponse.json(await hangupCall(id));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
