// Route handler: list + create branded/cloned voice profiles server-side.
import { NextRequest, NextResponse } from "next/server";
import { createVoiceProfile, listVoiceProfiles } from "@/lib/api";

export async function GET() {
  try {
    return NextResponse.json(await listVoiceProfiles());
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body?.name || (!body?.sample_uri && !body?.sample_data)) {
      return NextResponse.json(
        { error: "name and one of sample_uri or sample_data required" },
        { status: 400 },
      );
    }
    return NextResponse.json(await createVoiceProfile(body));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
