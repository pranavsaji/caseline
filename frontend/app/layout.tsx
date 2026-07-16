import "./globals.css";
import Link from "next/link";
import type { ReactNode } from "react";

export const metadata = {
  title: "Caseline Dashboard",
  description: "Calls, leads, transcripts, and agent config for your firm",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <nav className="nav">
            <span className="brand">Caseline</span>
            <Link href="/">Calls &amp; Leads</Link>
            <Link href="/analytics">Analytics</Link>
            <Link href="/config">Agent Config</Link>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
