import type { ReactNode } from "react";
import styles from "./kit.module.css";

export type Column<T> = {
  /** Stable key for the column. */
  key: string;
  header: ReactNode;
  /** Cell renderer. Defaults to `String(row[key])` when omitted. */
  render?: (row: T, index: number) => ReactNode;
  align?: "left" | "right" | "center";
  /** Extra class on both the <th> and <td> (e.g. width helpers). */
  className?: string;
};

/**
 * Table shell inside an inset "well" (§9): sticky header, zebra via a faint
 * surface shift (not borders), row hover lift, horizontal scroll on overflow.
 * Generic over the row type; keeps the existing per-page column markup. Renders
 * `empty` (typically an <EmptyState>) when there are no rows.
 */
export default function DataTable<T>({
  columns,
  rows,
  getRowKey,
  empty,
}: {
  columns: Column<T>[];
  rows: T[];
  getRowKey: (row: T, index: number) => string;
  empty?: ReactNode;
}) {
  if (rows.length === 0 && empty) {
    return <div className={styles.tableEmpty}>{empty}</div>;
  }

  function alignClass(align?: Column<T>["align"]) {
    if (align === "right") return styles.alignRight;
    if (align === "center") return styles.alignCenter;
    return "";
  }

  return (
    <div className={styles.tableWell}>
      <table className={styles.table}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={[alignClass(col.align), col.className ?? ""].filter(Boolean).join(" ")}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={getRowKey(row, index)}>
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={[alignClass(col.align), col.className ?? ""].filter(Boolean).join(" ")}
                >
                  {col.render
                    ? col.render(row, index)
                    : String((row as Record<string, unknown>)[col.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
