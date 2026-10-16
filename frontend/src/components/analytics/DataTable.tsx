import { useState } from "react";
import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  title: string;
  align?: "left" | "right";
  render?: (row: T) => ReactNode;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  collapsedRows?: number;
  rowKey?: (row: T, i: number) => string | number;
};

export function DataTable<T extends Record<string, any>>({ columns, rows, collapsedRows, rowKey }: Props<T>) {
  const [expanded, setExpanded] = useState(false);
  const collapsed = collapsedRows != null && !expanded && rows.length > collapsedRows;
  const shown = collapsed ? rows.slice(0, collapsedRows) : rows;

  return (
    <>
      <table className="an-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={c.align === "right" ? { textAlign: "right" } : undefined}>{c.title}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={rowKey ? rowKey(row, i) : i}>
              {columns.map((c) => (
                <td key={c.key} style={c.align === "right" ? { textAlign: "right" } : undefined}>
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {collapsedRows != null && rows.length > collapsedRows && (
        <button type="button" className="an-table-more" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Свернуть" : `Показать все (${rows.length})`}
        </button>
      )}
    </>
  );
}
