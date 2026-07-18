// Route handler: send a referral to a partner (PII leaves only with consent).
import { NextRequest, NextResponse } from "next/server";
import { sendReferral } from "@/lib/api";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    const { client_consent } = await req.json();
    return NextResponse.json(await sendReferral(id, Boolean(client_consent)));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
