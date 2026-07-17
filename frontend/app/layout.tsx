import "./globals.css";
import type { ReactNode } from "react";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import AppShell from "../components/AppShell";

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

// Applies the saved theme before first paint so there is no flash of the
// wrong palette. Falls back to the OS preference when nothing is stored.
const themeBootstrap = `(function(){try{var t=localStorage.getItem("caseline-theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);}}catch(e){}})();`;

export default function RootLayout({ children }: { children: ReactNode }) {
  const fontVars = `${spaceGrotesk.variable} ${inter.variable} ${jetbrainsMono.variable}`;
  return (
    <html lang="en" className={fontVars}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
