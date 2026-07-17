// Tiny shared helper for the config editors: returns a human-readable parse
// error for a JSON string, or null when it's valid. Empty/whitespace counts as
// valid (treated as `{}` on save), so the field doesn't flag while being typed.

export function getConfigError(value: string | undefined): string | null {
  if (value == null || value.trim() === "") return null;
  try {
    JSON.parse(value);
    return null;
  } catch (e) {
    return e instanceof Error ? `Invalid JSON — ${e.message}` : "Invalid JSON";
  }
}
