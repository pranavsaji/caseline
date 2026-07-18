// Route handler: the Calls hub posts outbound-call requests here; the firm
// token performs the authed dial on the server. Credential never hits the client.
import { NextRequest, NextResponse } from "next/server";
import { dialCall } from "@/lib/api";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body?.to_number) {
      return NextResponse.json({ error: "to_number required" }, { status: 400 });
    }
    return NextResponse.json(await dialCall(body));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
