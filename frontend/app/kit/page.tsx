import { notFound } from "next/navigation";
import Gallery from "./Gallery";
import { DARK_VARS, LIGHT_VARS } from "./themeVars";

// Dev-only component gallery (uiplan.md §Phase 1). Not part of the product;
// blocked in production so it never ships as a route.
export const dynamic = "force-static";

const panel = {
  borderRadius: 18,
  padding: "28px 24px",
} as const;

const heading = {
  fontFamily: "var(--font-display)",
  fontSize: 13,
  fontWeight: 600,
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  opacity: 0.7,
  margin: "0 0 16px",
};

export default function KitPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div style={{ ...panel, ...LIGHT_VARS }}>
        <p style={heading}>Slate Light</p>
        <Gallery />
      </div>
      <div style={{ ...panel, ...DARK_VARS }}>
        <p style={heading}>Graphite Dark</p>
        <Gallery />
      </div>
    </main>
  );
}
