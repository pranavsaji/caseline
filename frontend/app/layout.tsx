import "./globals.css";
import type { ReactNode } from "react";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import ShellGate from "../components/ShellGate";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-space-grotesk",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata = {
  title: "Caseline Dashboard",
  description: "Calls, leads, transcripts, and agent config for your firm",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const fontVars = `${spaceGrotesk.variable} ${inter.variable} ${jetbrainsMono.variable}`;
  // Dark-only: the palette lives in the CSS :root; no theme bootstrap needed.
  return (
    <html lang="en" className={fontVars} data-theme="dark">
      <body>
        <ShellGate>{children}</ShellGate>
      </body>
    </html>
  );
}
