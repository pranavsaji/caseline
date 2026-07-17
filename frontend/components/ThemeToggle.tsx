"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";

const STORAGE_KEY = "caseline-theme";

/**
 * Soft theme switch. Reads the theme the pre-hydration script already applied
 * to <html data-theme>, so there is no flash and no mismatch on first paint.
 */
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // No data-theme attribute means no stored preference → the CSS default,
    // which is now the Blue & White (light) theme regardless of OS setting.
    const stored = document.documentElement.getAttribute("data-theme") as Theme | null;
    setTheme(stored ?? "light");
    setMounted(true);
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage blocked (private mode) — theme still applies for this session */
    }
  }

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      className="theme-toggle"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      aria-pressed={isDark}
      title={isDark ? "Light theme" : "Dark theme"}
    >
      {/* Render both icons only after mount to avoid a hydration mismatch. */}
      {mounted ? (isDark ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />) : null}
      <span className="theme-toggle__label">{isDark ? "Light" : "Dark"}</span>
    </button>
  );
}
