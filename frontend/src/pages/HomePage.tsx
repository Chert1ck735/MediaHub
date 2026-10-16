import { useState } from "react";
import { motion } from "framer-motion";

import { formatMetricValue } from "../app/utils";
import { REPORT_PERIOD } from "../constants";
import { useAlerts } from "../hooks/useAlerts";
import { useAnalyticsSummary } from "../hooks/useAnalyticsSummary";

export type HomePageProps = {
  authToken: string;
  reportSourceId: string | null;
  navigateToTab: (tab: "calendar" | "content" | "analytics") => void;
  openAuth: (mode: "login") => void;
};

type HomeHistogramPeriod = "today" | "3days" | "week" | "month" | "all";

const HOME_PERIOD_OPTIONS: Array<{ value: HomeHistogramPeriod; label: string }> = [
  { value: "today", label: "сегодня" },
  { value: "3days", label: "3 дня" },
  { value: REPORT_PERIOD.WEEK, label: "неделю" },
  { value: REPORT_PERIOD.MONTH, label: "месяц" },
  { value: REPORT_PERIOD.ALL, label: "все время" },
];

export function HomePage({
  authToken,
  reportSourceId,
  navigateToTab,
  openAuth,
}: HomePageProps) {
  const [homePeriod, setHomePeriod] = useState<HomeHistogramPeriod>(REPORT_PERIOD.WEEK);
  // тот же фильтр площадки, что у воронки рядом, иначе числа блоков расходятся
  const alertsQuery = useAlerts(authToken, reportSourceId);
  const analyticsSummaryQuery = useAnalyticsSummary(authToken, homePeriod, reportSourceId);
  const analyticsSummary = authToken ? analyticsSummaryQuery.data ?? null : null;
  const sla = analyticsSummary?.sla;

  // Обращение = жалоба или просьба. Благодарности и оффтоп сюда не входят:
  // они не требуют реакции, ради которой сервис и считает эту цифру.
  const appealCount = analyticsSummary?.appeal_count ?? null;

  const classified = analyticsSummary?.classified_comment_count ?? null;
  const totalComments = analyticsSummary?.total_comment_count ?? null;

  // Воронка: каждая следующая стадия — подмножество предыдущей, поэтому высоты
  // считаем от самой первой, а не от максимума — так падение видно честно.
  const funnelStages = [
    {
      key: "collected",
      label: "Собрано",
      value: totalComments,
      caption: "Комментарии, выгруженные из сообществ.",
    },
    {
      key: "classified",
      label: "Проанализировано",
      value: classified,
      caption: "Прошли классификацию.",
    },
    {
      key: "appeals",
      label: "Выделено обращений",
      value: appealCount,
      caption: "Жалобы и просьбы, требующие реакции.",
    },
    {
      key: "answered",
      label: "Обработано организациями",
      value: sla?.answered ?? null,
      caption:
        sla?.median_hours != null
          ? `Получили официальный ответ, медиана — ${formatMetricValue(sla.median_hours)} ч.`
          : "Получили официальный ответ.",
    },
  ];

  const funnelBase = funnelStages[0].value ?? 0;
  const hasFunnelData = funnelStages.some((stage) => stage.value != null);

  // На главную — только категории, где обращений стало заметно больше.
  const growingAlerts = (alertsQuery.data ?? [])
    .filter((alert) => alert.growth_pct != null && alert.growth_pct > 0)
    .sort((a, b) => (b.growth_pct ?? 0) - (a.growth_pct ?? 0))
    .slice(0, 4);

  const snapshotDate = analyticsSummary
    ? new Date(analyticsSummary.generated_at).toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "long",
      })
    : null;

  return (
    <motion.div
      key="home"
      className="home-workspace"
      initial={{ opacity: 0, y: 18, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -14, filter: "blur(3px)" }}
      transition={{ duration: 0.45 }}
    >
      <motion.section
        className="hero home-hero"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55 }}
      >
        <p className="eyebrow">СИГМА · Центр медиааналитики</p>
        <motion.h1
          className="home-hero-title"
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.8 }}
        >
          Всё важное — в поле зрения
        </motion.h1>
        <p className="subtitle">
          Следите за сообществами, замечайте обращения и планируйте публикации.
        </p>
        {!authToken && (
          <div className="hero-actions">
            <button className="btn btn-primary" type="button" onClick={() => openAuth("login")}>
              Войти в систему
            </button>
          </div>
        )}
        {authToken && <div className="hero-actions">
          <button className="btn btn-primary" onClick={() => navigateToTab("content")}>＋ Создать публикацию</button>
          <button className="btn btn-outline" onClick={() => navigateToTab("calendar")}>Открыть календарь <span aria-hidden="true">↗</span></button>
        </div>}
      </motion.section>

      <div className="home-shortcuts" aria-label="Быстрый переход">
        {([
          { tab: "calendar", icon: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2", title: "Календарь публикаций", text: "Вся история и планы сообществ", label: "Контент под контролем" },
          { tab: "analytics", icon: "M4 20V10M10 20V4M16 20v-7M22 20H2", title: "Аналитика и обращения", text: "Сигналы, которым нужно внимание", label: "От наблюдений к действиям" },
          { tab: "content", icon: "M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z", title: "Студия контента", text: "От идеи до готовой публикации", label: "Создавайте с помощью ИИ" },
        ] as const).map(item => <button key={item.tab} className="home-shortcut" onClick={() => navigateToTab(item.tab)}>
          <span className="home-shortcut-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={item.icon} /></svg></span>
          <span className="home-shortcut-label">{item.label}</span><strong>{item.title}</strong><span>{item.text}</span><span className="home-shortcut-arrow" aria-hidden="true">↗</span>
        </button>)}
      </div>

      {authToken && analyticsSummaryQuery.isLoading && <div className="home-data-loading" role="status"><div className="calendar-cell-skeleton" /><p>Собираем обзор сообществ…</p></div>}
      {authToken && analyticsSummaryQuery.isError && <div className="workspace-error" role="alert"><span>Не удалось загрузить обзор сообществ.</span><button className="btn btn-outline" onClick={() => { void analyticsSummaryQuery.refetch(); }}>Повторить</button></div>}

      {hasFunnelData && (
        <motion.section
          className="home-funnel-section"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4 }}
          aria-label="Путь комментария за выбранный период: от сбора до ответа организации"
        >
          <h2 className="home-funnel-title">
            <span>От комментария к решению</span>
            <span className="home-period-combobox">
              <select
                aria-label="Период гистограммы"
                value={homePeriod}
                onChange={(event) => setHomePeriod(event.target.value as HomeHistogramPeriod)}
              >
                {HOME_PERIOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </span>
          </h2>
          <div className="home-funnel">
            {funnelStages.map((stage, index) => {
              const share = funnelBase > 0 && stage.value != null ? stage.value / funnelBase : 0;
              return (
                <motion.article
                  key={stage.key}
                  className="home-funnel-stage"
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.03 + index * 0.08 }}
                >
                  <p className="home-funnel-value">{formatMetricValue(stage.value)}</p>
                  <div className="home-funnel-track">
                    <motion.div
                      className="home-funnel-bar"
                      initial={{ height: 0 }}
                      animate={{ height: `${Math.max(share * 100, stage.value ? 2 : 0)}%` }}
                      transition={{ delay: 0.12 + index * 0.08, duration: 0.5, ease: "easeOut" }}
                      title={`${stage.label}: ${formatMetricValue(stage.value)}${
                        share > 0 ? ` — ${formatMetricValue(share * 100)}% от собранного` : ""
                      }`}
                    />
                  </div>
                  <h3 className="home-funnel-label">{stage.label}</h3>
                  <p className="home-funnel-caption">{stage.caption}</p>
                </motion.article>
              );
            })}
          </div>
        </motion.section>
      )}

      {hasFunnelData && (
        <div className="home-funnel-actions">
          {snapshotDate && (
            <p className="home-data-note">
              Данные на {snapshotDate}, источник: {analyticsSummary?.source_label}
            </p>
          )}
          <button className="btn home-analytics-link" type="button" onClick={() => navigateToTab("analytics")}>
            К аналитике
          </button>
        </div>
      )}

      {growingAlerts.length > 0 && (
        <section className="home-alerts">
          <div className="home-alerts-head">
            <h2>Требуют внимания</h2>
            <button className="btn btn-outline" type="button" onClick={() => navigateToTab("analytics")}>
              К аналитике
            </button>
          </div>
          <div className="home-alerts-list">
            {growingAlerts.map((alert) => (
              <div key={alert.category} className="home-alert-row">
                <strong>{alert.category}</strong>
                <span className="home-alert-growth">+{formatMetricValue(alert.growth_pct)}%</span>
                <span className="muted">
                  {formatMetricValue(alert.recent)} обращений за {alert.window_days} дн. против{" "}
                  {formatMetricValue(alert.prior)} в прошлом периоде
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

    </motion.div>
  );
}
