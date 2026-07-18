// Route handler: list selectable LLM providers/models server-side. The firm
// token stays server-side; the client only sees the provider catalog.
import { NextResponse } from "next/server";
import { getLlmProviders } from "@/lib/api";

export async function GET() {
  try {
    return NextResponse.json(await getLlmProviders());
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
