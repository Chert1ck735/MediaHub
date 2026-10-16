import type { ReactNode } from "react";

export function BarRow({ label, count, width, accent = "accent" }: {
  label: ReactNode;
  count: ReactNode;
  width: string;
  accent?: string;
}) {
  return (
    <div className="analytics-chart-row">
      <div className="analytics-chart-meta">
        <span>{label}</span>
        <strong>{count}</strong>
      </div>
      <div className="analytics-bar-track">
        <div className={`analytics-bar-fill analytics-bar-fill-${accent}`} style={{ width }} />
      </div>
    </div>
  );
}
