export type SeverityLevel = "low" | "medium" | "high" | "critical";

const TONE: Record<SeverityLevel, string> = {
  low: "ok",
  medium: "warn",
  high: "high",
  critical: "danger",
};

export function SeverityBadge({ level, label }: { level: SeverityLevel; label?: string }) {
  return <span className={`an-pill an-pill--${TONE[level] ?? "warn"}`}>{label ?? level}</span>;
}
