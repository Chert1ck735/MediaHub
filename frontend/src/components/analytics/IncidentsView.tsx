import type { AgencyStat, Incident } from "../../api";
import { Card } from "./Card";
import { DataTable, type Column } from "./DataTable";
import { StatusPill, type PillTone } from "./StatusPill";

const STATUS: Record<string, { tone: PillTone; label: string }> = {
  overdue: { tone: "danger", label: "просрочен" },
  in_work: { tone: "info", label: "в работе" },
  new: { tone: "warn", label: "новый" },
};

function age(hours: number): string {
  return hours >= 48 ? `${Math.round(hours / 24)} дн` : `${hours} ч`;
}

function rateTone(rate: number): PillTone {
  return rate < 30 ? "danger" : rate < 50 ? "warn" : "ok";
}

const AGENCY_COLS: Column<AgencyStat>[] = [
  { key: "agency", title: "Организация" },
  { key: "incidents", title: "Инцидентов" },
  { key: "answered", title: "В работе" },
  { key: "overdue", title: "Просрочено" },
  { key: "response_rate", title: "Отклик", render: (a) => <StatusPill tone={rateTone(a.response_rate)}>{a.response_rate}%</StatusPill> },
];

const INCIDENT_COLS: Column<Incident>[] = [
  {
    key: "problem",
    title: "Проблема",
    render: (it) => (
      <>
        {it.problem}
        <div style={{ color: "var(--text-secondary)", fontSize: "var(--fs-micro)" }}>{it.category}</div>
      </>
    ),
  },
  { key: "agency", title: "Организация" },
  { key: "mentions", title: "Обращений" },
  { key: "status", title: "Статус", render: (it) => {
    const s = STATUS[it.status] ?? STATUS.new;
    return <StatusPill tone={s.tone}>{s.label}</StatusPill>;
  } },
  { key: "age_hours", title: "Открыт", align: "right", render: (it) => age(it.age_hours) },
];

export function IncidentsView({ incidents, agencyRanking }: {
  incidents: Incident[] | null;
  agencyRanking: AgencyStat[] | null;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
      {agencyRanking && agencyRanking.length > 0 && (
        <Card title="Рейтинг организаций" note="по доле отвеченных обращений · хуже всех сверху">
          <DataTable columns={AGENCY_COLS} rows={agencyRanking} rowKey={(a) => a.agency} />
        </Card>
      )}
      <Card
        title="Реестр инцидентов"
        note={incidents && incidents.length > 0
          ? `адресный кейс → организация · статус из ответа организации · ${incidents.length} инцидентов`
          : "адресный кейс → организация · статус из ответа организации"}
      >
        {incidents === null && <div className="muted">Загрузка…</div>}
        {incidents && incidents.length === 0 && <div className="muted">Инцидентов нет.</div>}
        {incidents && incidents.length > 0 && (
          <DataTable columns={INCIDENT_COLS} rows={incidents} collapsedRows={30} rowKey={(_, i) => i} />
        )}
      </Card>
    </div>
  );
}
