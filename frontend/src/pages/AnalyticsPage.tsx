import { useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  apiCancelJob,
  apiGetAlerts,
  apiGetIncidents,
  apiGetAgencyRanking,
  apiRegeneratePainStrategy,
  apiSkipPublicQueue,
  type Alert,
  type Incident,
  type AgencyStat,
} from "../api";
import {
  painPriorityLabel,
} from "../app/constants";
import { PublicationPainsToggle } from "../components/PublicationPainsToggle";
import { RefreshIcon } from "../components/icons";
import {
  cropText,
  formatChartDate,
  formatMetricValue,
  stripVkMentions,
} from "../app/utils";
import {
  ANALYTICS_VIEW,
  PAIN_SEVERITY_FILTER,
  REPORT_PERIOD,
  REPORT_PLATFORM,
} from "../constants";
import { KRASNOYARSK_MUNICIPALITIES } from "../app/krasnoyarskMunicipalities";
import { queryKeys } from "../hooks/queryKeys";
import { useClassificationQueue } from "../hooks/useClassificationQueue";
import { useReportRecommendations } from "../hooks/useReportRecommendations";
import PainMap from "../components/PainMap";
import { IncidentsView } from "../components/analytics/IncidentsView";
import { KpiCard } from "../components/analytics/KpiCard";
import { Card } from "../components/analytics/Card";
import { BarRow } from "../components/analytics/BarRow";
import { SeverityBadge } from "../components/analytics/SeverityBadge";

type AnalyticsPageProps = any;

const POST_PLATFORM_OPTIONS = [
  { code: REPORT_PLATFORM.VK, label: "VK" },
  { code: REPORT_PLATFORM.TELEGRAM, label: "TG" },
  { code: REPORT_PLATFORM.OK, label: "Одноклассники" },
];
const FALLBACK_PLATFORM_OPTIONS = [{ code: REPORT_PLATFORM.VK, label: "VK" }];
const PAIN_TREND_PERIOD_LABELS: Record<string, string> = {
  [REPORT_PERIOD.WEEK]: "за неделю",
  [REPORT_PERIOD.MONTH]: "за месяц",
  [REPORT_PERIOD.THREE_MONTHS]: "за 3 месяца",
  [REPORT_PERIOD.SIX_MONTHS]: "за полгода",
  [REPORT_PERIOD.YEAR]: "за год",
  [REPORT_PERIOD.ALL]: "за месяц",
};

function CommentMessageIcon() {
  return (
    <span className="analytics-comment-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" focusable="false">
        <circle cx="12" cy="8" r="3.2" />
        <path d="M5.5 19c.8-4 3.1-6 6.5-6s5.7 2 6.5 6" />
      </svg>
    </span>
  );
}

function CaseLocationIcon() {
  return (
    <span className="analytics-case-location-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" focusable="false">
        <path d="M12 21s6-5.3 6-11a6 6 0 0 0-12 0c0 5.7 6 11 6 11Z" />
        <circle cx="12" cy="10" r="2.4" />
      </svg>
    </span>
  );
}

function commentUrl(item: any): string | null {
  return item.url || item.publication_url || null;
}

function commentSnippet(text: string | undefined, limit = 86): string {
  const value = stripVkMentions(text || "");
  if (value.length <= limit) return value;
  return `${value.slice(0, limit).trim()}...`;
}

function formatCommentTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const raw = String(value);
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})/);
  if (match) {
    const [, year, month, day, hours, minutes] = match;
    return `${day}.${month}.${year}  ${hours}:${minutes}`;
  }

  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "";
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = date.getFullYear();
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${day}.${month}.${year}  ${hours}:${minutes}`;
}

function CommentMessage({ item, limit, variant = "card", expandable = false }: { item: any; limit: number; variant?: "card" | "plain"; expandable?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const className = `analytics-comment-message ${variant === "plain" ? "analytics-comment-message-plain" : ""}`;
  const href = commentUrl(item);
  const responseLabel = item.has_official_response ? "ЕСТЬ ОТВЕТ ОРГАНИЗАЦИИ" : "НЕТ ОТВЕТА ОРГАНИЗАЦИИ";
  const timestamp = formatCommentTimestamp(item.comment_date || item.date);
  const fullText = String(item.text ?? "");
  const canExpand = expandable && fullText.length > limit;
  const text = canExpand && !expanded ? cropText(fullText, limit) : fullText;
  const content = (
    <>
      <CommentMessageIcon />
      <span className="analytics-comment-bubble">
        {href ? (
          <a className="analytics-comment-text analytics-comment-text-link" href={href} target="_blank" rel="noopener noreferrer">
            {text}
          </a>
        ) : (
          <span className="analytics-comment-text">
            {text}
          </span>
        )}
        <span className="analytics-comment-footer">
          {canExpand && (
            <button
              type="button"
              className="analytics-comment-expand"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "Свернуть" : "Показать полностью"}
            </button>
          )}
          {item.has_official_response && item.official_response_url ? (
            <a
              className="analytics-comment-response analytics-comment-response-present"
              href={item.official_response_url}
              target="_blank"
              rel="noopener noreferrer"
              title={item.official_response_text || responseLabel}
            >
              {responseLabel}
            </a>
          ) : (
            <span className="analytics-comment-response analytics-comment-response-empty">
              {responseLabel}
            </span>
          )}
          {timestamp ? (
            <span className="analytics-comment-timestamp">{timestamp}</span>
          ) : null}
        </span>
      </span>
    </>
  );
  return <span className={`${className}${href ? "" : " analytics-comment-message-disabled"}`}>{content}</span>;
}

export function AnalyticsPage(props: AnalyticsPageProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    authToken,
    dataLoading,
    analyticsLoading,
    analyticsView,
    setAnalyticsView,
    reportPlatform,
    setReportPlatform,
    reportSourceId,
    setReportSourceId,
    reportMunicipalityName,
    setReportMunicipalityName,
    reportSourcesLoading,
    reportSourceOptions,
    reportPlatformOptions,
    reportPeriod,
    setReportPeriod,
    reportLoading,
    handleGenerate,
    downloadReportPdf,
    reportPdfLoading,
    analyticsJob,
    analyticsSummary,
    painItems,
    analyticsSentimentBars,
    analyticsMessageTypeBars,
    analyticsCategoryBars,
    painSeverityFilter,
    setPainSeverityFilter,
    selectedPainId,
    setSelectedPainId,
    painTrends,
    selectedPainDetail,
    selectedSubproblem,
    setSelectedSubproblemTitle,
    paginatedComments,
    paginatedLoading,
    paginatedTotal,
    loadMorePainComments,
    strategyRegenLoading,
    strategyRegenError,
    setStrategyRegenError,
    setStrategyRegenLoading,
    reportPreview,
    reportOverviewCards,
    renderDetailedMetricChart,
    selectedChartRange,
    setSelectedChartRange,
    reportDateRange,
    reportTrend,
    chartRangePosts,
    reportAllPostsSorted,
    reportPreviewFetching,
    refetchReportPreview,
    chartPostsLimit,
    setChartPostsLimit,
    chartPostsSort,
    setChartPostsSort,
    reportMessageType,
    reportMessage,
  } = props;

  // Сколько комментов уйдёт в классификацию для выбранного периода — считаем
  // лениво, только когда включена глубокая аналитика.
  // Очередь берём из общего хука: тот же react-query кеш, что и у индикатора
  // в сайдбаре, поэтому поллер остаётся один на приложение.
  const { queue: classQueue, setQueue: setClassQueue } = useClassificationQueue(authToken);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [agencyRanking, setAgencyRanking] = useState<AgencyStat[] | null>(null);
  const [caseListShown, setCaseListShown] = useState(5);
  const [commentsShown, setCommentsShown] = useState(5);
  const [expandedCasePains, setExpandedCasePains] = useState<Set<string>>(new Set());
  const [sourcePickerOpen, setSourcePickerOpen] = useState(false);
  const [municipalityPickerOpen, setMunicipalityPickerOpen] = useState(false);
  const reportRecommendationsQuery = useReportRecommendations(
    authToken,
    reportPlatform,
    reportSourceId,
    reportPeriod,
    reportMunicipalityName,
    analyticsView === ANALYTICS_VIEW.POSTS && Boolean(reportPreview),
  );
  const mapCaseName = new URLSearchParams(location.search).get("case");

  useEffect(() => {
    if (new URLSearchParams(location.search).get("view") === "map") {
      setAnalyticsView(ANALYTICS_VIEW.MAP);
    }
  }, [location.search, setAnalyticsView]);

  function handleAnalyticsViewChange(view: string) {
    setAnalyticsView(view);
    if (location.search) {
      navigate({ pathname: location.pathname, search: "" }, { replace: true });
    }
  }

  useEffect(() => {
    if (!authToken) return;
    apiGetAlerts(authToken, reportSourceId, reportMunicipalityName).then(setAlerts).catch(() => {});
  }, [authToken, reportSourceId, reportMunicipalityName]);

  useEffect(() => {
    if (!authToken || analyticsView !== ANALYTICS_VIEW.INCIDENTS) return;
    apiGetIncidents(authToken, reportSourceId, reportMunicipalityName).then(setIncidents).catch(() => setIncidents([]));
    apiGetAgencyRanking(authToken, reportSourceId, reportMunicipalityName).then(setAgencyRanking).catch(() => setAgencyRanking([]));
  }, [authToken, analyticsView, reportSourceId, reportMunicipalityName]);

  const handleSkipPublic = (publicId: string) => {
    if (!authToken) return;
    setClassQueue((prev) => {
      if (!prev) return prev;
      const dropped = prev.by_public.find((p) => p.public_id === publicId);
      const drop = dropped ? dropped.pending : 0;
      return {
        ...prev,
        pending: Math.max(0, prev.pending - drop),
        in_progress: Math.max(0, prev.in_progress - drop),
        by_public: prev.by_public
          .map((p) => (p.public_id === publicId ? { ...p, pending: 0 } : p))
          .filter((p) => p.pending + p.processing > 0),
      };
    });
    apiSkipPublicQueue(authToken, publicId).catch(() => {});
  };

  const dbPlatformOptions =
    reportPlatformOptions && reportPlatformOptions.length > 0
      ? reportPlatformOptions
      : FALLBACK_PLATFORM_OPTIONS;
  const platformOptions =
    analyticsView === ANALYTICS_VIEW.POSTS ? POST_PLATFORM_OPTIONS : dbPlatformOptions;
  const selectedPlatformExists = platformOptions.some((option: any) => option.code === reportPlatform);
  const currentPlatform = selectedPlatformExists ? reportPlatform : platformOptions[0]?.code ?? REPORT_PLATFORM.VK;
  const sourceOptions =
    reportSourceOptions.filter((option: any) => option.platform === currentPlatform);
  const sourceSelectDisabled =
    reportSourcesLoading ||
    sourceOptions.length === 0;
  const selectedSourceIds = (reportSourceId || "").split(",").filter(Boolean);
  const selectedSources = sourceOptions.filter((option: any) => selectedSourceIds.includes(option.id));
  const setSelectedSourceIds = (ids: string[]) => {
    const selected = new Set(ids);
    const canonicalIds = sourceOptions
      .map((option: any) => option.id)
      .filter((id: string) => selected.has(id));
    setReportSourceId(canonicalIds.join(",") || null);
  };
  const toggleSource = (id: string) => {
    setSelectedSourceIds(selectedSourceIds.includes(id)
      ? selectedSourceIds.filter((value: string) => value !== id)
      : [...selectedSourceIds, id]);
  };
  // Муниципалитет — одиночный фильтр: одна активная территория на всех
  // аналитических представлениях, включая карту.
  const selectedMunicipalities = (reportMunicipalityName || "").split(",").map((name: string) => name.trim()).filter(Boolean);
  const toggleMunicipality = (label: string) => {
    setReportMunicipalityName(selectedMunicipalities.includes(label) ? null : label);
  };
  const painTrendPeriodLabel = PAIN_TREND_PERIOD_LABELS[reportPeriod] ?? PAIN_TREND_PERIOD_LABELS[REPORT_PERIOD.WEEK];

  useEffect(() => {
    if (selectedPlatformExists || platformOptions.length === 0) return;
    setReportPlatform(platformOptions[0].code);
    setReportSourceId(null);
  }, [platformOptions, selectedPlatformExists, setReportPlatform, setReportSourceId]);

  return (
    <motion.section
      key="analytics"
      className="content-page analytics-page"
      initial={{ opacity: 0, y: 18, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -14, filter: "blur(3px)" }}
      transition={{ duration: 0.45 }}
    >
      <div className="content-page-head">
        <div>
          <h2 className="content-page-title">
            Аналитика
            {(dataLoading || analyticsLoading) && (
              <span
                className="muted"
                style={{
                  marginLeft: 10,
                  fontSize: "0.7em",
                  fontWeight: 400,
                  opacity: 0.7,
                }}
              >
                обновляется…
              </span>
            )}
          </h2>
          {/* Сам индикатор очереди переехал в сайдбар — здесь остаётся только
              разбивка по пабликам с возможностью снять паблик с очереди. */}
          {classQueue && (
            <>
              {classQueue.in_progress > 0 && classQueue.by_public.length > 0 && (
                <span className="muted" style={{ display: "block", fontSize: 12, opacity: 0.75, marginTop: 2 }}>
                  {classQueue.by_public.slice(0, 5).map((p, i) => (
                    <span key={p.public_id}>
                      {i > 0 ? " · " : ""}
                      {p.name} {(p.pending + p.processing).toLocaleString("ru-RU")}
                      <button
                        type="button"
                        title={p.pending > 0 ? "Снять ожидающие комментарии паблика с очереди" : "Комментарий уже в работе"}
                        onClick={() => handleSkipPublic(p.public_id)}
                        disabled={p.pending === 0}
                        style={{ marginLeft: 3, border: "none", background: "none", cursor: p.pending > 0 ? "pointer" : "default", color: "inherit", opacity: p.pending > 0 ? 0.55 : 0.28 }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {classQueue.by_public.length > 5 ? ` · +ещё ${classQueue.by_public.length - 5}` : ""}
                </span>
              )}
            </>
          )}
        </div>
      </div>

      {/* Добавление площадок переехало в раздел «Организация»: это
          управление организацией, а не аналитика. */}

      <div className="analytics-report-toolbar analytics-platform-filter" style={{ display: analyticsView === ANALYTICS_VIEW.INCIDENTS ? "none" : undefined }}>
        <div className="analytics-report-head">
          <h3>Фильтр по площадкам</h3>
          <Link className="analytics-platform-manage-link" to="/organization?section=communities">
            Управление площадками
          </Link>
        </div>
        <div className="report-head-actions">
          <select
            className="analytics-platform-select"
            value={currentPlatform}
            onChange={(e) => {
              setReportPlatform(e.target.value);
              setReportSourceId(null);
            }}
          >
            {platformOptions.map((option: any) => (
              <option key={option.code} value={option.code}>
                {option.label}
              </option>
            ))}
          </select>
          <div className="analytics-source-picker">
            <button
              type="button"
              className="analytics-source-select"
              onClick={() => setSourcePickerOpen((value) => !value)}
              disabled={sourceSelectDisabled}
              aria-expanded={sourcePickerOpen}
            >
              <span className="analytics-source-select-label">
                {selectedSources.length ? `Выбрано площадок: ${selectedSources.length}` : "Все источники"}
              </span>
              <span className="analytics-source-select-arrow" aria-hidden="true" />
            </button>
            {sourcePickerOpen && !sourceSelectDisabled && (
              <div className="analytics-source-picker-menu" role="listbox" aria-multiselectable="true">
                {sourceOptions.map((option: any) => {
                  const selected = selectedSourceIds.includes(option.id);
                  return (
                    <button
                      key={option.id}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      className={`analytics-source-picker-option ${selected ? "selected" : ""}`}
                      onClick={() => toggleSource(option.id)}
                    >
                      <span className="analytics-source-picker-check">{selected ? "✓" : ""}</span>
                      <span className="analytics-source-picker-option-label" title={option.label}>{option.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
            {selectedSources.length > 0 && (
              <div className="analytics-source-chips">
                {selectedSources.map((option: any) => (
                  <span className="analytics-source-chip" key={option.id}>
                    <span className="analytics-source-chip-label" title={option.label}>{option.label}</span>
                    <button type="button" aria-label={`Убрать ${option.label}`} onClick={() => toggleSource(option.id)}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <select
            className="analytics-period-select"
            value={reportPeriod}
            onChange={(e) => {
              setReportPeriod(e.target.value);
            }}
          >
            <option value={REPORT_PERIOD.WEEK}>За неделю</option>
            <option value={REPORT_PERIOD.MONTH}>За месяц</option>
            <option value={REPORT_PERIOD.THREE_MONTHS}>За 3 месяца</option>
            <option value={REPORT_PERIOD.SIX_MONTHS}>За полгода</option>
            <option value={REPORT_PERIOD.YEAR}>За год</option>
            <option value={REPORT_PERIOD.ALL}>За все время</option>
          </select>
          <div className="analytics-source-picker">
            <button
              type="button"
              className="analytics-source-select"
              onClick={() => setMunicipalityPickerOpen((value) => !value)}
              aria-expanded={municipalityPickerOpen}
            >
              <span className="analytics-source-select-label">
                {selectedMunicipalities.length === 1
                  ? selectedMunicipalities[0]
                  : selectedMunicipalities.length
                    ? `Выбрано территорий: ${selectedMunicipalities.length}`
                    : "Все муниципалитеты"}
              </span>
              <span className="analytics-source-select-arrow" aria-hidden="true" />
            </button>
            {municipalityPickerOpen && (
              <div className="analytics-source-picker-menu" role="listbox" aria-multiselectable="true">
                {KRASNOYARSK_MUNICIPALITIES.map((municipality) => {
                  const selected = selectedMunicipalities.includes(municipality.label);
                  return (
                    <button
                      key={municipality.label}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      className={`analytics-source-picker-option ${selected ? "selected" : ""}`}
                      onClick={() => toggleMunicipality(municipality.label)}
                    >
                      <span className="analytics-source-picker-check">{selected ? "✓" : ""}</span>
                      <span className="analytics-source-picker-option-label" title={municipality.label}>
                        {municipality.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            {selectedMunicipalities.length > 0 && (
              <div className="analytics-source-chips">
                {selectedMunicipalities.map((label: string) => (
                  <span className="analytics-source-chip" key={label}>
                    <span className="analytics-source-chip-label" title={label}>{label}</span>
                    <button type="button" aria-label={`Убрать ${label}`} onClick={() => toggleMunicipality(label)}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <button className="btn btn-outline" type="button" onClick={downloadReportPdf} disabled={reportPdfLoading}>
            {reportPdfLoading ? "Формирование отчёта…" : "Скачать PDF-отчет"}
          </button>
        </div>
      </div>

      <div className="analytics-subnav analytics-tab-switch">
        <button
          type="button"
          className={`analytics-subnav-btn ${analyticsView === ANALYTICS_VIEW.PAINS ? "active" : ""}`}
          onClick={() => handleAnalyticsViewChange(ANALYTICS_VIEW.PAINS)}
        >
          Темы обсуждений
        </button>
        <button
          type="button"
          className={`analytics-subnav-btn ${analyticsView === ANALYTICS_VIEW.MAP ? "active" : ""}`}
          onClick={() => handleAnalyticsViewChange(ANALYTICS_VIEW.MAP)}
        >
          Карта болей
        </button>
        <button
          type="button"
          className={`analytics-subnav-btn ${analyticsView === ANALYTICS_VIEW.POSTS ? "active" : ""}`}
          onClick={() => handleAnalyticsViewChange(ANALYTICS_VIEW.POSTS)}
        >
          Статистика
        </button>
      </div>

      {analyticsView === ANALYTICS_VIEW.PAINS && alerts.length > 0 && (
        <div className="analytics-report-toolbar" style={{ display: "block", borderLeft: "3px solid #d9772b" }}>
          <strong style={{ fontSize: 13 }}>⚠ Всплески за неделю</strong>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
            {alerts.map((a, i) => (
              <span key={i} style={{ fontSize: 13, background: "rgba(217,119,43,.12)", color: "#d9772b", padding: "4px 10px", borderRadius: 14 }}>
                {a.category}: {a.recent} за неделю{a.growth_pct != null ? ` (+${a.growth_pct}%)` : ""}
              </span>
            ))}
          </div>
        </div>
      )}

      {analyticsView === ANALYTICS_VIEW.INCIDENTS && (
        <div className="analytics-report-toolbar" style={{ display: "block" }}>
          <IncidentsView incidents={incidents} agencyRanking={agencyRanking} />
        </div>
      )}

      {analyticsView === ANALYTICS_VIEW.MAP && (
        <div className="analytics-report-toolbar" style={{ display: "block" }}>
          <h3 style={{ marginTop: 0 }}>Карта болей</h3>
          <PainMap
            token={authToken}
            period={reportPeriod}
            publicSocialLinkId={reportSourceId}
            municipalityName={reportMunicipalityName}
            targetCaseName={mapCaseName}
            onMunicipalityToggle={toggleMunicipality}
          />
        </div>
      )}

      {analyticsJob && (analyticsJob.status === "running" || analyticsJob.status === "pending") && (
        <div
          style={{
            margin: "12px 0",
            padding: "12px 14px",
            borderRadius: 10,
            background: "rgba(120, 160, 255, 0.08)",
            border: "1px solid rgba(120, 160, 255, 0.25)",
          }}
        >
          <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                fontSize: 13,
                alignItems: "center",
              }}
            >
              <span>{analyticsJob.message || "Пересборка аналитики…"}</span>

              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span className="muted">
                  {analyticsJob.total != null
                    ? `Комментарии паблика: ${analyticsJob.total}`
                    : ""}
                </span>

                <button
                  type="button"
                  className="btn btn-outline btn-compact"
                  disabled={!authToken || analyticsJob.cancel_requested}
                  onClick={() => {
                    if (!authToken || !analyticsJob?.id) return;
                    void apiCancelJob(authToken, analyticsJob.id).catch(() => {});
                  }}
                >
                  {analyticsJob.cancel_requested ? "Отменяем…" : "Отменить"}
                </button>
              </div>
            </div>
          <div
            style={{
              marginTop: 8,
              height: 6,
              borderRadius: 4,
              background: "rgba(255,255,255,0.08)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width:
                  analyticsJob.total && analyticsJob.total > 0
                    ? `${Math.min(100, (analyticsJob.done / analyticsJob.total) * 100)}%`
                    : "30%",
                height: "100%",
                background: "linear-gradient(90deg, #6aa9ff, #b58dff)",
                transition: "width 0.4s ease",
              }}
            />
          </div>
        </div>
      )}

      <div id="analytics-pains" />

      {analyticsView === ANALYTICS_VIEW.PAINS && !analyticsSummary && painItems.length === 0 && (
        <div className="analytics-empty">
          <h3>Snapshot пока не загружен</h3>
          <p className="muted">
            Сначала загрузите паблики из VK или Одноклассников либо запустите пересборку аналитики.
          </p>
        </div>
      )}

      {analyticsView === ANALYTICS_VIEW.PAINS && (analyticsSummary || painItems.length > 0) && (
        <>
          <section className="analytics-panel analytics-charts-panel analytics-charts-shell">
            <div className="analytics-charts-panel-head">
              <div>
                <h3 className="analytics-hero-title">Темы обсуждений</h3>
                <p className="muted analytics-hero-meta">
                  <span title="В «Статистике» — счётчики площадок, поэтому числа могут отличаться">
                    По собранным комментариям
                  </span>
                </p>
              </div>
              <button
                type="button"
                className={`btn-icon-refresh ${reportLoading ? "spinning" : ""}`}
                title={reportLoading ? "Обновляем…" : "Обновить данные из базы"}
                aria-label="Обновить данные из базы"
                onClick={handleGenerate}
                disabled={reportLoading}
              >
                <RefreshIcon />
              </button>
            </div>
            {analyticsSummary && (analyticsSummary.classified_comment_count ?? 0) === 0 && (
              <p className="message" style={{ margin: "0 0 12px" }}>
                За выбранный период нет разобранных комментариев, поэтому карточки пустые.
                Собрано {analyticsSummary.total_comment_count ?? 0}
                {classQueue && classQueue.pending > 0
                  ? `, в очереди на классификацию ${classQueue.pending}`
                  : ""}. Выберите период побольше или дождитесь классификации.
              </p>
            )}
            <div className="analytics-chart-grid analytics-chart-grid-top">
              <Card title="Тональность комментариев">
                <div className="analytics-chart-list">
                  {analyticsSentimentBars.map((item: any) => (
                    <BarRow key={item.key} label={item.label} count={item.count} width={item.width} accent={item.accent ?? "accent"} />
                  ))}
                </div>
              </Card>

              <Card title="Типы сообщений">
                <div className="analytics-chart-list">
                  {analyticsMessageTypeBars.map((item: any) => (
                    <BarRow key={item.key} label={item.label} count={item.count} width={item.width} accent={item.accent ?? "accent"} />
                  ))}
                </div>
              </Card>

              {analyticsSummary?.sla && analyticsSummary.sla.appeals > 0 && (
                <Card title="Ответ организации" note="SLA">
                  <div className="analytics-chart-list">
                    <div className="analytics-chart-row"><div className="analytics-chart-meta"><span>Ответили на обращения</span><strong>{analyticsSummary.sla.response_rate}% ({analyticsSummary.sla.answered} из {analyticsSummary.sla.appeals})</strong></div></div>
                    <div className="analytics-chart-row"><div className="analytics-chart-meta"><span>Медиана ответа</span><strong>{analyticsSummary.sla.median_hours != null ? `${analyticsSummary.sla.median_hours} ч` : "—"}</strong></div></div>
                    <div className="analytics-chart-row"><div className="analytics-chart-meta"><span>В срок (48 ч)</span><strong>{analyticsSummary.sla.within_sla_rate}%</strong></div></div>
                  </div>
                </Card>
              )}

              <Card title="Топ категорий">
                <div className="analytics-chart-list">
                  {analyticsCategoryBars.map((item: any) => (
                    <BarRow
                      key={item.key}
                      label={item.label}
                      count={item.count}
                      width={`${item.widthPct}%`}
                      accent="neutral"
                    />
                  ))}
                </div>
              </Card>
            </div>
          </section>

          <div className="analytics-pains-workspace">
            <div className="analytics-pain-list">
              <div className="analytics-pain-list-filter">
                <span className="muted">Приоритет:</span>
                {([PAIN_SEVERITY_FILTER.ALL, PAIN_SEVERITY_FILTER.CRITICAL, PAIN_SEVERITY_FILTER.HIGH, PAIN_SEVERITY_FILTER.MEDIUM, PAIN_SEVERITY_FILTER.LOW] as const).map((sev) => (
                  <button
                    key={sev}
                    type="button"
                    className={`btn-chip btn-chip--${sev} ${painSeverityFilter === sev ? "btn-chip-active" : ""}`}
                    onClick={() => setPainSeverityFilter(sev)}
                  >
                    {sev === PAIN_SEVERITY_FILTER.ALL ? "Все" : painPriorityLabel[sev] ?? sev}
                    {sev !== PAIN_SEVERITY_FILTER.ALL && (
                      <span className="btn-chip-count">
                        {painItems.filter((p: any) => p.severity_level === sev).length}
                      </span>
                    )}
                  </button>
                ))}
              </div>
              {painItems
                .filter((pain: any) => painSeverityFilter === PAIN_SEVERITY_FILTER.ALL || pain.severity_level === painSeverityFilter)
                .map((pain: any) => (
                  <button
                    key={pain.id}
                    type="button"
                    className={`analytics-pain-card ${selectedPainId === pain.id ? "active" : ""}`}
                    onClick={() => setSelectedPainId(pain.id)}
                  >
                    <div className="analytics-pain-head">
                      <h3>{pain.title}</h3>
                      <SeverityBadge level={pain.severity_level} label={`Приоритет: ${painPriorityLabel[pain.severity_level] ?? pain.severity_level}`} />
                    </div>
                    <div className="analytics-pain-meta">
                      <span>{pain.mentions_count} упоминаний</span>
                      <span>{pain.publications_count} публикаций</span>
                      <span>{pain.subproblem_count} подпроблем</span>
                      {(pain.cases_count ?? 0) > 0 && <span>{pain.cases_count} адресов</span>}
                    </div>
                    {pain.top_cases && pain.top_cases.length > 0 && (() => {
                      const expanded = expandedCasePains.has(pain.id);
                      const shown = expanded ? pain.top_cases : pain.top_cases.slice(0, 4);
                      const hidden = pain.top_cases.length - 4;
                      const toggle = (e: React.MouseEvent) => {
                        e.stopPropagation();
                        setExpandedCasePains((prev) => {
                          const next = new Set(prev);
                          if (next.has(pain.id)) next.delete(pain.id); else next.add(pain.id);
                          return next;
                        });
                      };
                      return (
                        <div className="analytics-pain-cases">
                          <span className="analytics-pain-cases-label">Адреса:</span>
                          {shown.map((c: any, i: number) => (
                            <span key={`${c.title}-${i}`} className="analytics-pain-case-chip">
                              {c.title}
                              {c.mentions_count > 1 && <em> · {c.mentions_count}</em>}
                            </span>
                          ))}
                          {hidden > 0 && (
                            <span
                              role="button"
                              tabIndex={0}
                              className="analytics-pain-case-chip analytics-pain-case-chip-more"
                              onClick={toggle}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") toggle(e as any); }}
                            >
                              {expanded ? "свернуть" : `+ ещё ${hidden}`}
                            </span>
                          )}
                        </div>
                      );
                    })()}
                    {(() => {
                      const series = painTrends[pain.id];
                      if (!series || series.length < 2) return null;
                      const maxVal = Math.max(1, ...series);
                      const w = 110;
                      const h = 22;
                      const stepX = w / (series.length - 1);
                      const points = series
                        .map((v: number, i: number) => `${(i * stepX).toFixed(1)},${(h - (v / maxVal) * h).toFixed(1)}`)
                        .join(" ");
                      const last = series[series.length - 1];
                      const prev = series[series.length - 2] ?? last;
                      const delta = last - prev;
                      const deltaStr = delta > 0 ? `+${delta}` : `${delta}`;
                      const arrow = last > prev ? "↗" : last < prev ? "↘" : "→";
                      const trendClass = last > prev ? "trend-up" : last < prev ? "trend-down" : "trend-flat";
                      return (
                        <div className="analytics-pain-trend" title={`Упоминаний ${painTrendPeriodLabel}: ${series.join(", ")}`}>
                          <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
                            <polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={points} />
                          </svg>
                          <span className={`analytics-pain-trend-arrow ${trendClass}`}>{arrow} {deltaStr}</span>
                          <span className="muted analytics-pain-trend-label">{painTrendPeriodLabel}</span>
                        </div>
                      );
                    })()}
                  </button>
                ))}
            </div>

            {selectedPainDetail && (
              <div className="analytics-detail-card">
                <div className="analytics-pain-head">
                  <h3>{selectedPainDetail.title}</h3>
                  <SeverityBadge level={selectedPainDetail.severity_level} label={`Приоритет: ${painPriorityLabel[selectedPainDetail.severity_level] ?? selectedPainDetail.severity_level}`} />
                </div>
                <div className="analytics-detail-content">
                  <section className="analytics-detail-section">
                    {selectedPainDetail.subproblem_items.length === 0 ? (
                      <p className="muted">Подпроблемы для этой темы пока не выделены.</p>
                    ) : (
                      <div className="analytics-chip-grid">
                        <button
                          type="button"
                          className={`analytics-chip ${selectedSubproblem ? "" : "active"}`}
                          onClick={() => setSelectedSubproblemTitle(null)}
                        >
                          <span>Все</span>
                          <strong>{selectedPainDetail.mentions_count}</strong>
                        </button>
                        {selectedPainDetail.subproblem_items.map((item: any) => (
                          <button
                            key={item.title}
                            type="button"
                            className={`analytics-chip ${selectedSubproblem?.title === item.title ? "active" : ""}`}
                            onClick={() => setSelectedSubproblemTitle(item.title)}
                          >
                            <span>{item.title}</span>
                            <strong>{item.mentions_count}</strong>
                          </button>
                        ))}
                      </div>
                    )}

                    <div className="analytics-comments-section">
                      <h4>Комментарии:</h4>
                      {paginatedComments.length > 0 ? (
                        <ul className="analytics-comment-list">
                          {paginatedComments.slice(0, commentsShown).map((item: any, index: number) => (
                            <li key={`${selectedPainDetail.id}-${item.comment_id}-${index}`}>
                              <CommentMessage item={item} limit={220} variant="plain" expandable />
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">
                          {paginatedLoading
                            ? "Загрузка…"
                            : selectedSubproblem
                              ? "Нет привязанных комментариев у этой подпроблемы."
                              : "По этой боли пока нет выделенных комментариев."}
                        </p>
                      )}
                      <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                        {commentsShown < paginatedTotal && (
                          <button
                            type="button"
                            className="btn btn-outline btn-compact"
                            onClick={() => { setCommentsShown((n) => n + 5); if (paginatedComments.length < commentsShown + 5) void loadMorePainComments(); }}
                            disabled={paginatedLoading}
                          >
                            {paginatedLoading ? "Загрузка…" : `Показать ещё (${Math.min(5, paginatedTotal - commentsShown)})`}
                          </button>
                        )}
                        {commentsShown > 5 && (
                          <button type="button" className="btn btn-outline btn-compact" onClick={() => setCommentsShown(5)}>
                            Свернуть
                          </button>
                        )}
                      </div>
                      {!selectedSubproblem && selectedPainDetail.top_cases.length > 0 && (
                        <div className="analytics-case-section">
                          <h4>Адреса по теме ({selectedPainDetail.cases_count})</h4>
                          <div className="analytics-case-list">
                            {selectedPainDetail.top_cases.slice(0, caseListShown).map((item: any) => {
                              const rawCaseTitle = item.raw_title || item.title;
                              return (
                                <article key={rawCaseTitle} className="analytics-case-card">
                                  <div className="analytics-case-card-main">
                                    <CaseLocationIcon />
                                    <div className="analytics-case-card-body">
                                      <div className="analytics-case-head">
                                        <strong>{item.title}</strong>
                                        <span>{item.mentions_count} упоминаний</span>
                                      </div>
                                      <Link
                                        className="analytics-case-detail-link"
                                        to={`/analytics?view=map&case=${encodeURIComponent(rawCaseTitle)}`}
                                        onClick={() => setAnalyticsView(ANALYTICS_VIEW.MAP)}
                                      >
                                        Посмотреть детали
                                      </Link>
                                    </div>
                                  </div>
                                </article>
                              );
                            })}
                            <div style={{ display: "flex", gap: 10 }}>
                              {selectedPainDetail.top_cases.length > caseListShown && (
                                <button
                                  type="button"
                                  className="btn btn-outline btn-compact"
                                  onClick={() => setCaseListShown((n) => n + 5)}
                                >
                                  Показать ещё ({Math.min(5, selectedPainDetail.top_cases.length - caseListShown)})
                                </button>
                              )}
                              {caseListShown > 5 && (
                                <button type="button" className="btn btn-outline btn-compact" onClick={() => setCaseListShown(5)}>
                                  Свернуть
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                      {selectedSubproblem && selectedSubproblem.cases.length > 0 && (
                        <div className="analytics-case-section">
                          <h4>Адреса в подпроблеме &quot;{selectedSubproblem.title}&quot;</h4>
                          <div className="analytics-case-list">
                            {selectedSubproblem.cases.slice(0, caseListShown).map((item: any) => {
                              const rawCaseTitle = item.raw_title || item.title;
                              const examples = item.comment_examples.slice(0, 3);
                              const snippets = examples
                                .map((example: any) => commentSnippet(example.text, examples.length === 1 ? 260 : 68))
                                .filter(Boolean);
                              const detailHref = `/analytics?view=map&case=${encodeURIComponent(rawCaseTitle)}`;
                              return (
                                <article key={rawCaseTitle} className="analytics-case-card">
                                  <div className="analytics-case-card-main">
                                    <CaseLocationIcon />
                                    <div className="analytics-case-card-body">
                                      <div className="analytics-case-head">
                                        <strong>{item.title}</strong>
                                        <span>{item.mentions_count} упоминаний</span>
                                      </div>
                                      {snippets.length > 0 && (
                                        <div className={`analytics-case-snippets ${snippets.length === 1 ? "single" : ""}`}>
                                          {snippets.map((snippet: string, index: number) => (
                                            <span key={`${rawCaseTitle}-${index}`}>&quot;{snippet}&quot;</span>
                                          ))}
                                        </div>
                                      )}
                                      <Link
                                        className="analytics-case-detail-link"
                                        to={detailHref}
                                        onClick={() => setAnalyticsView(ANALYTICS_VIEW.MAP)}
                                      >
                                        Посмотреть детали
                                      </Link>
                                    </div>
                                  </div>
                                </article>
                              );
                            })}
                            <div style={{ display: "flex", gap: 10 }}>
                              {selectedSubproblem.cases.length > caseListShown && (
                                <button
                                  type="button"
                                  className="btn btn-outline btn-compact"
                                  onClick={() => setCaseListShown((n) => n + 5)}
                                >
                                  Показать ещё ({Math.min(5, selectedSubproblem.cases.length - caseListShown)})
                                </button>
                              )}
                              {caseListShown > 5 && (
                                <button
                                  type="button"
                                  className="btn btn-outline btn-compact"
                                  onClick={() => setCaseListShown(5)}
                                >
                                  Свернуть
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </section>
                </div>

                <section className="analytics-panel analytics-panel-wide analytics-plan-panel">
                    <div className="analytics-events-head">
                      <h4>Управленческий план</h4>
                      <button
                        type="button"
                        className="btn btn-outline btn-compact"
                        disabled={!authToken || strategyRegenLoading === selectedPainDetail.id}
                        onClick={async () => {
                          if (!authToken) return;
                          setStrategyRegenError(null);
                          setStrategyRegenLoading(selectedPainDetail.id);
                          try {
                            const res = await apiRegeneratePainStrategy(authToken, selectedPainDetail.id);
                            queryClient.setQueryData(
                              queryKeys.painDetail(
                                authToken,
                                selectedPainDetail.id,
                                reportSourceId,
                                reportPeriod,
                                reportMunicipalityName,
                              ),
                              (prev: any) =>
                                prev && prev.id === res.pain_id
                                  ? { ...prev, communication_strategy: res.description }
                                  : prev,
                            );
                          } catch (e) {
                            setStrategyRegenError(e instanceof Error ? e.message : "LLM-сервис недоступен");
                          } finally {
                            setStrategyRegenLoading(null);
                          }
                        }}
                      >
                        {strategyRegenLoading === selectedPainDetail.id ? "Генерация…" : "Сгенерировать персональный план"}
                      </button>
                    </div>
                    {strategyRegenError && (
                      <p className="message error" style={{ fontSize: "0.82rem" }}>{strategyRegenError}</p>
                    )}
                    {!selectedPainDetail.communication_strategy ? (
                      <p className="muted">План работы по этой боли пока не задан.</p>
                    ) : (
                      <pre className="analytics-pre">{stripVkMentions(selectedPainDetail.communication_strategy)}</pre>
                    )}
                </section>
              </div>
            )}
          </div>
        </>
      )}

      {analyticsView === ANALYTICS_VIEW.POSTS && (
        <section id="analytics-posts" className="analytics-addon-section analytics-tab-content-panel">
          <div className="analytics-addon-head">
            <div>
              <h3 className="analytics-hero-title">Статистика</h3>
              <p className="muted analytics-hero-meta">
                <span>Период: {reportDateRange}</span>
                {reportTrend && (
                  <span>
                    Рост охвата: {reportTrend.label}
                    {reportTrend.pct != null ? ` (${reportTrend.pct > 0 ? "+" : ""}${reportTrend.pct}%)` : ""}
                  </span>
                )}
                <span title="В «Темах обсуждений» считаются собранные и обработанные комментарии, поэтому числа могут отличаться">
                  По счётчикам площадок
                </span>
              </p>
            </div>
            <button
              className={`btn-icon-refresh ${reportPreviewFetching ? "spinning" : ""}`}
              type="button"
              title={reportPreviewFetching ? "Обновление…" : "Обновить данные отчёта"}
              aria-label="Обновить данные отчёта"
              onClick={() => refetchReportPreview()}
              disabled={reportPreviewFetching}
            >
              <RefreshIcon />
            </button>
          </div>

          {!reportPreview ? (
            <div className="analytics-empty analytics-addon-empty">
              <h3>{reportPreviewFetching ? "Загружается…" : "Данных за период нет"}</h3>
              <p className="muted">
                {reportPreviewFetching
                  ? "Собираем метрики по выбранному периоду."
                  : "Импортируйте площадку или смените период/источник, затем нажмите «Обновить»."}
              </p>
            </div>
          ) : (
            <>
              <div className="an-kpi-grid">
                {reportOverviewCards.map((card: any) => (
                  <KpiCard key={card.label} label={card.label} value={String(card.value)} />
                ))}
              </div>

              {reportPreview.activity_heatmap && (
                <article className="analytics-chart-card analytics-heatmap-card">
                  <div className="analytics-heatmap-head">
                    <h5>Активность аудитории по часам и дням</h5>
                    {reportPreview.recommended_post_window && (
                      <span className="muted">Пик: {reportPreview.recommended_post_window}</span>
                    )}
                  </div>
                  {(() => {
                    // Строки бэка — по Postgres dow (0=вс…6=сб); показываем с понедельника.
                    const days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
                    const order = [1, 2, 3, 4, 5, 6, 0];
                    const hm = reportPreview.activity_heatmap;
                    const maxVal = Math.max(1, ...hm.flat());
                    return (
                      <div className="analytics-heatmap">
                        <div className="analytics-heatmap-row analytics-heatmap-row-head">
                          <div className="analytics-heatmap-day"></div>
                          {Array.from({ length: 24 }, (_, h) => (
                            <div key={h} className="analytics-heatmap-hour-label">{h % 3 === 0 ? h : ""}</div>
                          ))}
                        </div>
                        {order.map((di: number, i: number) => (
                          <div key={di} className="analytics-heatmap-row">
                            <div className="analytics-heatmap-day">{days[i]}</div>
                            {(hm[di] || []).map((v: number, hi: number) => {
                              const intensity = v / maxVal;
                              const bg = `rgba(120, 160, 220, ${0.06 + intensity * 0.85})`;
                              return (
                                <div
                                  key={hi}
                                  className="analytics-heatmap-cell"
                                  title={`${days[i]} ${hi}:00 — ${v} комм.`}
                                  style={{ background: bg }}
                                >{v > 0 && intensity > 0.45 ? v : ""}</div>
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </article>
              )}

              <div className="analytics-chart-grid analytics-post-chart-grid">
                <article className="analytics-chart-card">
                  <h5>Просмотры по датам</h5>
                  {renderDetailedMetricChart(reportPreview.points, "views", "#e6704d", "Просмотры", (b: any) => setSelectedChartRange({ from: b.date, to: b.endDate }))}
                </article>
                <article className="analytics-chart-card">
                  <h5>Лайки по датам</h5>
                  {renderDetailedMetricChart(reportPreview.points, "likes", "#4caf50", "Лайки", (b: any) => setSelectedChartRange({ from: b.date, to: b.endDate }))}
                </article>
                <article className="analytics-chart-card">
                  <h5>Комментарии по датам</h5>
                  {renderDetailedMetricChart(reportPreview.points, "comments", "#6aa0d6", "Комментарии", (b: any) => setSelectedChartRange({ from: b.date, to: b.endDate }))}
                </article>
              </div>

              <div className="analytics-post-report-actions">
                <button className="btn btn-outline" type="button" onClick={downloadReportPdf} disabled={reportPdfLoading}>
                  {reportPdfLoading ? "Формирование отчёта…" : "Скачать PDF-отчет"}
                </button>
              </div>

              <div className="report-metrics-grid analytics-insights-grid analytics-insights-grid-single">
                <article className="analytics-chart-card">
                  {selectedChartRange ? (
                    <div className="analytics-post-top-head" style={{ marginBottom: 8 }}>
                      <h5 style={{ margin: 0 }}>
                        {selectedChartRange.from === selectedChartRange.to
                          ? `Публикации за ${formatChartDate(selectedChartRange.from)}`
                          : `Публикации за ${formatChartDate(selectedChartRange.from)} — ${formatChartDate(selectedChartRange.to)}`}
                      </h5>
                      <button className="btn btn-outline" style={{ padding: "2px 10px", fontSize: 12 }} type="button" onClick={() => setSelectedChartRange(null)}>✕ Сбросить</button>
                    </div>
                  ) : (
                    <h5>Публикации</h5>
                  )}
                  {(() => {
                    const postsList = selectedChartRange ? chartRangePosts : reportAllPostsSorted;
                    return (
                      <>
                        {postsList.length > 0 && (
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, gap: 8 }}>
                            <span className="muted" style={{ fontSize: 12 }}>Всего: {postsList.length}</span>
                            <select
                              value={chartPostsSort}
                              onChange={(e) => setChartPostsSort(e.target.value)}
                              style={{ fontSize: 12 }}
                            >
                              <option value="views_desc">Сначала самые просматриваемые</option>
                              <option value="views_asc">Сначала наименее просматриваемые</option>
                              <option value="date_desc">Сначала новые</option>
                              <option value="date_asc">Сначала старые</option>
                            </select>
                          </div>
                        )}
                        <div className="analytics-post-top-list">
                          {postsList.slice(0, chartPostsLimit).map((item: any, index: number) => (
                            <article key={`${item.date ?? "post"}-${index}`} className="analytics-post-top-card">
                              <div className="analytics-post-top-head">
                                <span>#{index + 1} {item.date ? `· ${formatChartDate(item.date)}` : ""}</span>
                                <strong>{formatMetricValue(item.views)} просмотров</strong>
                              </div>
                              <p>{cropText(item.text || `Пост ${index + 1}`, 180)}</p>
                              <div className="analytics-post-top-meta">
                                <span>Лайки: {formatMetricValue(item.likes ?? null)}</span>
                                <span>Комментарии: {formatMetricValue(item.comments ?? null)}</span>
                                {item.url && <a href={item.url} target="_blank" rel="noopener noreferrer" className="analytics-post-link">Открыть</a>}
                                {item.url && <PublicationPainsToggle authToken={authToken} url={item.url} />}
                              </div>
                            </article>
                          ))}
                          {postsList.length === 0 && (
                            <p className="muted" style={{ fontSize: 13 }}>Публикаций нет.</p>
                          )}
                          {postsList.length > chartPostsLimit && (
                            <button
                              type="button"
                              className="btn btn-outline"
                              style={{ marginTop: 8, alignSelf: "center" }}
                              onClick={() => setChartPostsLimit((n: number) => n + 10)}
                            >
                              Показать ещё ({postsList.length - chartPostsLimit})
                            </button>
                          )}
                        </div>
                      </>
                    );
                  })()}
                </article>
              </div>

              <article className="analytics-chart-card report-recommendations-card">
                <h5>Рекомендации по контенту</h5>
                <pre className="analytics-pre">
                  {reportRecommendationsQuery.isFetching
                    ? "Готовим рекомендации… (LLM, до минуты)"
                    : (reportRecommendationsQuery.data?.recommendations || "Нет рекомендаций")}
                </pre>
              </article>
            </>
          )}
        </section>
      )}

      <p className={`message ${reportMessageType}`}>{reportMessage}</p>
    </motion.section>
  );
}

