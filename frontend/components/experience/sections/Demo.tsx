"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "../experience.module.css";
import { Reveal } from "../ui/Reveal";
import { MagneticButton } from "../ui/MagneticButton";
import { experience } from "../lib/store";

type Turn = { who: "caller" | "agent"; text: string };

const SCRIPT: Turn[] = [
  { who: "agent", text: "Thanks for calling Harding & Cole, this is Caseline. How can I help?" },
  { who: "caller", text: "Hi — I was rear-ended on the freeway last week and I'm still in pain." },
  { who: "agent", text: "I'm sorry that happened. Were you treated by a doctor after the accident?" },
  { who: "caller", text: "Yeah, I went to the ER that night and I have a follow-up Thursday." },
  { who: "agent", text: "Good. That's exactly the kind of case our injury team handles. I can book you a free consult — does Thursday at 4pm work?" },
  { who: "caller", text: "That works." },
  { who: "agent", text: "Booked. You'll get a text confirmation and I've started your file. We'll take great care of you." },
];

/**
 * Section 4 — the interactive product demonstration. Pressing "Play the call"
 * types out a real intake conversation turn by turn; while the agent speaks,
 * it feeds the shared `speak` energy so the orb behind the panel churns in
 * sync, then settles when the caller talks. This is the section's hotspot: the
 * orb literally reacts to the demo.
 */
export function Demo() {
  const [turnIndex, setTurnIndex] = useState(-1);
  const [typed, setTyped] = useState("");
  const [playing, setPlaying] = useState(false);
  const timers = useRef<number[]>([]);
  const rafRef = useRef(0);

  const clearAll = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    cancelAnimationFrame(rafRef.current);
    experience.speak = 0;
  }, []);

  useEffect(() => () => clearAll(), [clearAll]);

  const play = useCallback(() => {
    clearAll();
    setPlaying(true);
    setTurnIndex(-1);
    setTyped("");

    let delay = 0;
    SCRIPT.forEach((turn, i) => {
      timers.current.push(
        window.setTimeout(() => {
          setTurnIndex(i);
          setTyped("");
          // Type the turn character by character.
          let ch = 0;
          const speed = turn.who === "agent" ? 26 : 22; // ms per char
          const step = () => {
            ch++;
            setTyped(turn.text.slice(0, ch));
            if (ch < turn.text.length) {
              timers.current.push(window.setTimeout(step, speed));
            } else if (i === SCRIPT.length - 1) {
              setPlaying(false);
            }
          };
          step();
        }, delay),
      );
      // Reserve time for this turn + a beat before the next.
      delay += turn.text.length * (turn.who === "agent" ? 26 : 22) + 700;
    });

    // Drive the orb's speaking energy: high while an agent turn is typing.
    const loop = () => {
      const current = SCRIPT[Math.max(0, turnIndexRef.current)];
      const isAgentTyping =
        playingRef.current && current?.who === "agent" && typedRef.current.length < current.text.length;
      // Oscillate for a lively, voice-like churn rather than a flat value.
      experience.speak = isAgentTyping ? 0.45 + 0.35 * Math.abs(Math.sin(performance.now() * 0.012)) : 0;
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
  }, [clearAll]);

  // Refs mirror state so the rAF loop reads fresh values without re-binding.
  const turnIndexRef = useRef(turnIndex);
  const typedRef = useRef(typed);
  const playingRef = useRef(playing);
  turnIndexRef.current = turnIndex;
  typedRef.current = typed;
  playingRef.current = playing;

  const started = turnIndex >= 0;

  return (
    <section id="demo" className={styles.section} aria-label="Hear a live call">
      <div className={`${styles.sectionInner} ${styles.wide}`}>
        <Reveal as="p" className={styles.eyebrow}>
          Listen in
        </Reveal>
        <h2 className={styles.h2}>A real intake, start to finish.</h2>
        <Reveal as="p" className={styles.lede} delay={0.2}>
          Press play. Watch Caseline qualify an injury lead and book the consult —
          the orb reacts as it speaks.
        </Reveal>

        <div className={styles.demoGrid}>
          <Reveal className={styles.transcript} delay={0.3}>
            <div className={styles.transcriptHead}>
              <span className={styles.liveDot} aria-hidden />
              {playing ? "Live call · in progress" : started ? "Call ended" : "Ready to dial"}
            </div>

            {!started && (
              <p className={styles.turn} style={{ color: "var(--muted)" }}>
                Inbound call from a prospective client. Hit play to hear how it goes.
              </p>
            )}

            {started &&
              SCRIPT.slice(0, turnIndex + 1).map((turn, i) => (
                <p className={styles.turn} key={i}>
                  <span
                    className={`${styles.turnWho} ${turn.who === "agent" ? styles.whoAgent : styles.whoCaller}`}
                  >
                    {turn.who === "agent" ? "Caseline" : "Caller"}
                  </span>
                  {i === turnIndex ? typed : turn.text}
                  {i === turnIndex && playing && <span className={styles.caret}>&nbsp;</span>}
                </p>
              ))}
          </Reveal>

          <div className={styles.ctaRow}>
            <MagneticButton onClick={play}>{started ? "Replay the call" : "Play the call"}</MagneticButton>
          </div>
        </div>
      </div>
    </section>
  );
}
