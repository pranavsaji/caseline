import type { Metadata } from "next";
import { ExperienceRoot } from "../../components/experience/ExperienceRoot";

export const metadata: Metadata = {
  title: "Caseline — The voice that answers",
  description:
    "Caseline is an AI intake employee for law firms. It answers every call in a natural voice, qualifies the lead against your rules, and books the consult — day or night.",
};

/**
 * The cinematic marketing experience. Rendered full-bleed (ShellGate strips the
 * dashboard chrome for `/experience`). All interactive/WebGL work lives in the
 * client <ExperienceRoot>; this server page only carries route metadata.
 */
export default function ExperiencePage() {
  return <ExperienceRoot />;
}
