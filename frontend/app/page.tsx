import type { Metadata } from "next";
import { ExperienceRoot } from "../components/experience/ExperienceRoot";

export const metadata: Metadata = {
  title: "Caseline — The voice that answers",
  description:
    "Caseline is an AI intake employee for law firms. It answers every call in a natural voice, qualifies the lead against your rules, and books the consult — day or night.",
};

/**
 * The public landing page: the cinematic marketing experience. This is the only
 * unauthenticated surface besides the auth screens (see `middleware.ts`) — it
 * renders no firm data, so it is safe to serve to anyone. The dashboard proper
 * moved to `/dashboard`, which stays gated; every CTA here points at it.
 *
 * All interactive/WebGL work lives in the client <ExperienceRoot>; this server
 * page only carries route metadata.
 */
export default function LandingPage() {
  return <ExperienceRoot />;
}
