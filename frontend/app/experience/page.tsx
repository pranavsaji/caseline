import { redirect } from "next/navigation";

/**
 * The experience is now the site's landing page at `/`. This route is kept so
 * existing links to `/experience` don't 404 — it just forwards.
 */
export default function ExperiencePage() {
  redirect("/");
}
