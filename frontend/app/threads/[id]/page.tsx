import { getThread } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ThreadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const thread = await getThread(id);

  return (
    <main>
      <h1>
        Thread {thread.id.slice(0, 8)} <span className="pill">{thread.channel}</span>{" "}
        <span className="pill muted">{thread.goal}</span>{" "}
        <span className={`pill ${thread.status === "open" ? "ok" : "muted"}`}>
          {thread.status === "open" ? "open" : thread.closed_reason ?? "closed"}
        </span>
      </h1>

      <h2>Conversation</h2>
      {thread.messages.length === 0 ? (
        <div className="empty">No messages.</div>
      ) : (
        thread.messages.map((m, i) => (
          <div key={i} className={`turn ${m.direction === "out" ? "assistant" : ""}`}>
            <div className="role">
              {m.direction === "out" ? "agent" : "caller"} · {m.ts.slice(0, 19)}
            </div>
            {m.body}
          </div>
        ))
      )}

      <h2>State</h2>
      <div className="notice" style={{ whiteSpace: "pre-wrap", fontFamily: "ui-monospace, Menlo, monospace" }}>
        {JSON.stringify(thread.state, null, 2)}
      </div>
    </main>
  );
}
