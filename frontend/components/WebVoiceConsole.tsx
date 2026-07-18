"use client";

// Browser voice test: talk to the intake agent live over WebRTC — no phone
// number, no SIP trunk, no telephony charge. Posts to /api/calls/web-session
// (firm token stays server-side) to get a LiveKit token, joins the room, and
// publishes the mic. The same agent worker that answers phone calls auto-joins
// the room and runs the firm's brain, so this exercises the full STT->LLM->TTS
// pipeline, guardrails, and tools end-to-end. Agent audio plays through the
// browser; live captions render from LiveKit transcription events.

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, PhoneOff, Radio } from "lucide-react";
import type { Room, RemoteTrack, TranscriptionSegment } from "livekit-client";
import Card from "@/components/Card";
import SoftButton from "@/components/SoftButton";
import Pill, { type PillTone } from "@/components/Pill";
import Notice from "@/components/Notice";
import TranscriptTurn, { TranscriptList } from "@/components/TranscriptTurn";

type Status = "idle" | "connecting" | "live" | "ended" | "error";

const STATUS_TONE: Record<Status, PillTone> = {
  idle: "muted",
  connecting: "warn",
  live: "ok",
  ended: "muted",
  error: "bad",
};

type Caption = { id: string; role: "agent" | "you"; text: string };

export default function WebVoiceConsole() {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [room, setRoom] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [captions, setCaptions] = useState<Caption[]>([]);

  const roomRef = useRef<Room | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Tear the session down if the component unmounts mid-call.
  useEffect(() => {
    return () => {
      roomRef.current?.disconnect();
      roomRef.current = null;
    };
  }, []);

  async function start() {
    setStatus("connecting");
    setError(null);
    setCaptions([]);
    try {
      const res = await fetch("/api/calls/web-session", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "could not start session");

      // Import client-side only: livekit-client touches browser WebRTC APIs.
      const { Room, RoomEvent, Track } = await import("livekit-client");
      const lkRoom = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = lkRoom;

      lkRoom
        .on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
          if (track.kind === Track.Kind.Audio && audioRef.current) {
            track.attach(audioRef.current);
          }
        })
        .on(
          RoomEvent.TranscriptionReceived,
          (segments: TranscriptionSegment[], participant) => {
            // The local participant's segments are the caller (you); everything
            // else is the agent. Keep only finalized segments to avoid flicker.
            const isYou = participant?.identity === lkRoom.localParticipant.identity;
            setCaptions((prev) => {
              const next = [...prev];
              for (const seg of segments) {
                if (!seg.final) continue;
                const existing = next.find((c) => c.id === seg.id);
                if (existing) existing.text = seg.text;
                else next.push({ id: seg.id, role: isYou ? "you" : "agent", text: seg.text });
              }
              return next;
            });
          },
        )
        .on(RoomEvent.Disconnected, () => {
          setStatus((s) => (s === "error" ? s : "ended"));
        });

      await lkRoom.connect(data.url, data.token);
      await lkRoom.localParticipant.setMicrophoneEnabled(true);
      setRoom(data.room);
      setStatus("live");
    } catch (err) {
      setError(String(err));
      setStatus("error");
      roomRef.current?.disconnect();
      roomRef.current = null;
    }
  }

  async function hangUp() {
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setStatus("ended");
  }

  function toggleMute() {
    const lp = roomRef.current?.localParticipant;
    if (!lp) return;
    const next = !muted;
    lp.setMicrophoneEnabled(!next);
    setMuted(next);
  }

  const live = status === "live";

  return (
    <Card
      title="Talk to the agent (browser)"
      actions={
        <Pill tone={STATUS_TONE[status]} dot={live}>
          {status === "idle" ? "ready" : status}
        </Pill>
      }
    >
      <p className="stackCard" style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
        Speak to the intake agent live in your browser — real voice, no phone
        number and no telephony charge. Runs the exact same brain as a phone
        call. Needs mic permission and the agent worker running.
      </p>

      <div className="formRow" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {!live ? (
          <SoftButton variant="primary" onClick={start} disabled={status === "connecting"}>
            <Radio size={16} /> {status === "connecting" ? "Connecting…" : "Start conversation"}
          </SoftButton>
        ) : (
          <>
            <SoftButton variant="danger" onClick={hangUp}>
              <PhoneOff size={16} /> End
            </SoftButton>
            <SoftButton onClick={toggleMute}>
              {muted ? <MicOff size={16} /> : <Mic size={16} />} {muted ? "Unmute" : "Mute"}
            </SoftButton>
          </>
        )}
      </div>

      {room ? (
        <p style={{ color: "var(--muted)", fontSize: 12, margin: "6px 0 0" }}>
          Session <code>{room}</code>
        </p>
      ) : null}

      {error ? (
        <Notice tone="bad" title="Could not connect">
          {error}
        </Notice>
      ) : null}

      {captions.length > 0 ? (
        <TranscriptList>
          {captions.map((c) => (
            <TranscriptTurn key={c.id} role={c.role === "you" ? "you" : "agent"}>
              {c.text}
            </TranscriptTurn>
          ))}
        </TranscriptList>
      ) : null}

      {/* Agent voice plays here. */}
      <audio ref={audioRef} autoPlay />
    </Card>
  );
}
