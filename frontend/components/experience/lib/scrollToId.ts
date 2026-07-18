"use client";

/**
 * Smoothly scroll a section into view by DOM id. Uses native smooth scroll,
 * which Lenis intercepts and eases when smooth scrolling is active, and which
 * degrades to an instant jump under reduced-motion (the browser honours the OS
 * setting for `scrollIntoView`).
 */
export function scrollToId(id: string) {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}
