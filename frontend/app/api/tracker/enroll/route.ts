// Route handler: enroll a signed client in the treatment tracker.
import { NextRequest, NextResponse } from "next/server";
import { enrollTracker } from "@/lib/api";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body?.name?.trim() || !body?.phone?.trim()) {
      return NextResponse.json({ error: "name and phone required" }, { status: 400 });
    }
    return NextResponse.json(
      await enrollTracker({
        name: String(body.name).trim(),
        phone: String(body.phone).trim(),
        matter_description: body.matter_description?.trim() || undefined,
        cadence_days: body.cadence_days ? Number(body.cadence_days) : undefined,
      }),
    );
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
