// Route handler: apply the engine's proposed qualification rules to the live
// intake agent. The firm token stays server-side.
import { NextRequest, NextResponse } from "next/server";
import { applyTuning } from "@/lib/api";

export async function POST(req: NextRequest) {
  try {
    const days = Number(new URL(req.url).searchParams.get("days")) || 90;
    return NextResponse.json(await applyTuning(days));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
