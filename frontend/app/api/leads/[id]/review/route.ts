// Route handler: attorney verdict on a lead (qualification-tuning signal).
import { NextRequest, NextResponse } from "next/server";
import { reviewLead } from "@/lib/api";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    const body = await req.json();
    if (!body?.verdict) {
      return NextResponse.json({ error: "verdict required" }, { status: 400 });
    }
    return NextResponse.json(await reviewLead(id, body));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
