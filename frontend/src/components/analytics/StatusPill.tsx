import type { ReactNode } from "react";

export type PillTone = "ok" | "warn" | "high" | "danger" | "info";

export function StatusPill({ tone, children }: { tone: PillTone; children: ReactNode }) {
  return <span className={`an-pill an-pill--${tone}`}>{children}</span>;
}
