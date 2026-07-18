// Route handler: resolve a referral (accepted / declined).
import { NextRequest, NextResponse } from "next/server";
import { setReferralStatus } from "@/lib/api";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await ctx.params;
    const { status } = await req.json();
    if (!status) {
      return NextResponse.json({ error: "status required" }, { status: 400 });
    }
    return NextResponse.json(await setReferralStatus(id, status));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
