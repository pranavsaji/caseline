// Route handler: staff-authored follow-up message on an open thread.
import { NextRequest, NextResponse } from "next/server";
import { sendThreadMessage } from "@/lib/api";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    const { body } = await req.json();
    if (!body || !String(body).trim()) {
      return NextResponse.json({ error: "message body required" }, { status: 400 });
    }
    return NextResponse.json(await sendThreadMessage(id, String(body).trim()));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
