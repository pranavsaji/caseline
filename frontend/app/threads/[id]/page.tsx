import { getThread } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Card from "@/components/Card";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";
import EmptyState from "@/components/EmptyState";
import TranscriptTurn, { TranscriptList } from "@/components/TranscriptTurn";
import ThreadReply from "@/components/ThreadReply";

export const dynamic = "force-dynamic";

export default async function ThreadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const thread = await getThread(id);
  const open = thread.status === "open";

  return (
    <>
      <PageHeader
        title={`Thread ${thread.id.slice(0, 8)}`}
        subtitle={thread.address ? `${thread.channel} · ${thread.address}` : thread.channel}
        actions={
          <>
            <Pill tone="info">{thread.channel}</Pill>
            <Pill tone="muted">{thread.goal}</Pill>
            <Pill tone={open ? "ok" : "muted"}>
              {open ? "open" : thread.closed_reason ?? "closed"}
            </Pill>
          </>
        }
      />

      <Card title="Conversation">
        {thread.messages.length === 0 ? (
          <EmptyState title="No messages">This thread has no messages yet.</EmptyState>
        ) : (
          <TranscriptList>
            {thread.messages.map((m, i) => (
              <TranscriptTurn
                key={i}
                role={m.direction === "out" ? "agent" : "caller"}
                speaker={m.direction === "out" ? "agent" : "caller"}
                meta={m.ts ? m.ts.slice(0, 19) : undefined}
              >
                {m.body}
              </TranscriptTurn>
            ))}
          </TranscriptList>
        )}
      </Card>

      {open ? (
        <Card title="Manual follow-up" className="stackCard">
          <ThreadReply threadId={thread.id} />
        </Card>
      ) : (
        <div className="stackCard">
          <Notice tone="warn" title="Thread closed">
            This thread is {thread.closed_reason ?? "closed"} — manual follow-ups
            are only allowed on open threads.
          </Notice>
        </div>
      )}

      <Card title="State" className="stackCard">
        <Notice tone="info" icon={false}>
          <pre>{JSON.stringify(thread.state, null, 2)}</pre>
        </Notice>
      </Card>
    </>
  );
}
