// Route handler: manual call-disposition override.
import { NextRequest, NextResponse } from "next/server";
import { setCallOutcome } from "@/lib/api";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    const { outcome, note } = await req.json();
    if (!outcome || !String(outcome).trim()) {
      return NextResponse.json({ error: "outcome required" }, { status: 400 });
    }
    return NextResponse.json(await setCallOutcome(id, String(outcome).trim(), note));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
