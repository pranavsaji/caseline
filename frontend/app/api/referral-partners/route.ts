// Route handler: register a new referral partner, server-side.
import { NextRequest, NextResponse } from "next/server";
import { createReferralPartner } from "@/lib/api";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body?.name) {
      return NextResponse.json({ error: "name required" }, { status: 400 });
    }
    return NextResponse.json(await createReferralPartner(body));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
