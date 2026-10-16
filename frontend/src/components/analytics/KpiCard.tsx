export type KpiDelta = { text: string; tone: "up" | "down" | "flat" };

export function KpiCard({ label, value, delta }: { label: string; value: string; delta?: KpiDelta }) {
  return (
    <div className="an-kpi">
      <div className="an-kpi-label">{label}</div>
      <div className="an-kpi-value">{value}</div>
      {delta && <div className={`an-kpi-delta an-delta-${delta.tone}`}>{delta.text}</div>}
    </div>
  );
}
