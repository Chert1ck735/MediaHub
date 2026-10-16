import { Fragment, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  apiCancelJob,
  apiDeleteImportedPublic,
  apiGetRegions,
  apiUpdatePublicRegion,
  ingestLink,
  isOkLink,
  isTelegramLink,
  waitForJob,
  type IngestResponse,
  type JobInfo,
  type RegionOption,
  type VkPublicLink,
  type VkPublicSummary,
} from "./api";
import { KRASNOYARSK_MUNICIPALITIES } from "./app/krasnoyarskMunicipalities";
import { useOrganizations } from "./hooks/useOrganizations";
import { useDataHealth } from "./hooks/useOrganization";
import { queryKeys } from "./hooks/queryKeys";
import { formatMetricValue } from "./app/utils";
import {
  HISTORY_UNITS,
  historyDateFrom,
  type HistoryUnit,
} from "./app/historyPeriod";
import { RefreshIcon } from "./components/icons";
import { ConfirmDialog } from "./pages/organization/shared";
import { PublicImportTab } from "./pages/organization/PublicImportTab";

type Props = {
  token: string;
  orgId: string;
  onIngested?: () => void | Promise<void>;
};

// Свежесть самых старых данных — из data-health summary.
function formatAge(hours: number | null): string {
  if (hours == null) return "—";
  if (hours < 1) return "< 1 ч";
  if (hours < 48) return `${Math.round(hours)} ч`;
  return `${Math.round(hours / 24)} дн`;
}

const formatPercent = (value: number): string => `${Math.round(value)}%`;

const INGEST_JOB_KEY = "media-events:active-ingest-job";

const LINK_HINT =
  "VK: сообщество, профиль или отдельный пост. " +
  "Одноклассники: группа (ok.ru/group/...) или отдельная тема. " +
  "Telegram: публичный канал или отдельный пост. " +
  "Дальше свежие комментарии подтягивает автопарсер сам.";

const TYPE_LABEL: Record<IngestResponse["type"], string> = {
  community: "Сообщество",
  profile: "Профиль",
  post: "Пост",
  group: "Группа OK",
  topic: "Тема OK",
  channel: "Канал Telegram",
};


// ── Человекочитаемые ошибки автопарсера ────────────────────────────────────
function describeAutoparseError(raw: string): string {
  if (raw === "no_active_org_user") {
    return "Нет активного пользователя организации — от чьего имени парсить.";
  }
  if (raw.startsWith("unsupported_network:")) {
    const net = raw.split(":")[1] ?? "";
    return `Сеть «${net.toUpperCase()}» пока не поддерживается автопарсером.`;
  }
  // Технические исключения приходят как «ТипОшибки: текст» — показываем текст,
  // тип оставляем в подсказке (title), чтобы не пугать пользователя.
  const idx = raw.indexOf(": ");
  const message = idx > -1 ? raw.slice(idx + 2) : raw;
  if (/timeout|timed out|ConnectTimeout|ReadTimeout/i.test(raw)) {
    return "Соцсеть не ответила вовремя. Повторится на следующем проходе.";
  }
  if (/rate.?limit|Too Many Requests|429|flood/i.test(raw)) {
    return "Соцсеть ограничила частоту запросов. Повторится позже.";
  }
  if (/access|forbidden|403|private|closed/i.test(raw)) {
    return "Нет доступа к площадке (закрыта или изменились права).";
  }
  return message || "Неизвестная ошибка автопарсера.";
}

// ── Агрегат классификации по паблику (из data-health, по public_id) ─────────
type HealthAgg = { comments: number; classified: number; failed: number };

// ── Агрегат по площадке для таблицы ────────────────────────────────────────
type PublicRow = {
  id: string;
  name: string;
  networks: string[];
  primaryUrl: string | null;
  publications: number;
  comments: number;
  classificationPercent: number | null;
  classificationErrors: number;
  regionId: string | null;
  municipalityName: string | null;
  range: string | null;
  lastCheck: string | null;
  error: { raw: string; network: string } | null;
};

function networkOf(link: VkPublicLink): string {
  if (link.social_network_code === "telegram" || (link.url && isTelegramLink(link.url))) return "TG";
  return link.url && isOkLink(link.url) ? "OK" : "VK";
}

function buildRow(p: VkPublicSummary, health: Map<string, HealthAgg>): PublicRow {
  const networks = Array.from(new Set(p.links.map(networkOf)));
  const primaryUrl = p.links.find((l) => l.url)?.url ?? null;

  const publications = p.links.reduce((a, l) => a + (l.publications_count || 0), 0);
  const comments = p.links.reduce((a, l) => a + (l.total_comments || 0), 0);

  // Классификация приходит из data-health (по ссылкам, свёрнуто в public_id).
  // Пока health не загрузился или у паблика нет комментариев — процент = null («—»).
  const agg = health.get(p.id);
  const classificationPercent =
    agg && agg.comments > 0 ? (agg.classified / agg.comments) * 100 : null;
  const classificationErrors = agg?.failed ?? 0;

  const firsts = p.links.map((l) => l.first_comment_at).filter(Boolean) as string[];
  const lasts = p.links.map((l) => l.last_comment_at).filter(Boolean) as string[];
  let range: string | null = null;
  if (firsts.length && lasts.length) {
    const from = new Date([...firsts].sort()[0]).toLocaleDateString("ru-RU");
    const sortedLasts = [...lasts].sort();
    const to = new Date(sortedLasts[sortedLasts.length - 1]).toLocaleDateString("ru-RU");
    range = from === to ? from : `${from} – ${to}`;
  }

  const checks = p.links.map((l) => l.last_autoparse_at).filter(Boolean) as string[];
  const lastCheck = checks.length ? [...checks].sort()[checks.length - 1] : null;

  const errored = p.links.find((l) => l.last_autoparse_error);
  const error = errored
    ? { raw: errored.last_autoparse_error as string, network: networkOf(errored) }
    : null;

  return {
    id: p.id,
    name: p.name,
    networks,
    primaryUrl,
    publications,
    comments,
    classificationPercent,
    classificationErrors,
    regionId: p.region_id ?? null,
    municipalityName: p.municipality_name ?? null,
    range,
    lastCheck,
    error,
  };
}

function relativeCheck(iso: string | null): string {
  if (!iso) return "ещё не проверялась";
  const then = new Date(iso).getTime();
  const diffH = (Date.now() - then) / 36e5;
  if (diffH < 1) return "менее часа назад";
  if (diffH < 24) return `${Math.round(diffH)} ч назад`;
  const days = Math.round(diffH / 24);
  return `${days} дн назад`;
}

const num = (v: number) => v.toLocaleString("ru-RU");

export function VkIngestPanel({ token, orgId, onIngested }: Props) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [historyAmount, setHistoryAmount] = useState(2);
  const [historyUnit, setHistoryUnit] = useState<HistoryUnit>("weeks");
  const [submitting, setSubmitting] = useState(false);
  const [progressJob, setProgressJob] = useState<JobInfo | null>(null);
  const [deletingPublicId, setDeletingPublicId] = useState<string | null>(null);
  const [publicToDelete, setPublicToDelete] = useState<PublicRow | null>(null);
  const [savingRegionPublicId, setSavingRegionPublicId] = useState<string | null>(null);
  const [regions, setRegions] = useState<RegionOption[]>([]);
  const [showImported, setShowImported] = useState(true);
  const [showFileImport, setShowFileImport] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<IngestResponse | null>(null);
  const organizationsQuery = useOrganizations(token);
  const publics = organizationsQuery.data ?? [];
  const loadingPublics = organizationsQuery.isFetching;

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    apiGetRegions(token)
      .then((items) => {
        if (!cancelled) setRegions(items);
      })
      .catch(() => {
        if (!cancelled) setRegions([]);
      });
    return () => { cancelled = true; };
  }, [token]);

  // Техническая свежесть/классификация по площадкам (тот же react-query кеш).
  const healthQuery = useDataHealth(orgId);
  const summary = healthQuery.data?.summary ?? null;

  const healthByPublic = new Map<string, HealthAgg>();
  for (const item of healthQuery.data?.items ?? []) {
    const agg = healthByPublic.get(item.public_id) ?? {
      comments: 0,
      classified: 0,
      failed: 0,
    };
    agg.comments += item.comments_count;
    agg.classified += item.classified_count;
    agg.failed += item.failed_count;
    healthByPublic.set(item.public_id, agg);
  }

  const rows = publics.map((p) => buildRow(p, healthByPublic));

  const totalLinks = publics.reduce((a, p) => a + p.links.length, 0);
  const totalPublications = publics.reduce(
    (a, p) => a + p.links.reduce((s, l) => s + (l.publications_count || 0), 0),
    0,
  );
  const totalViews = publics.reduce(
    (a, p) => a + p.links.reduce((s, l) => s + (l.total_views || 0), 0),
    0,
  );
  const queued = summary
    ? summary.pending_count + summary.processing_count + summary.missing_analysis_count
    : null;

  const refreshPublics = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.organizations(token) });
  };

  const isKrasnoyarskRegion = (regionId: string | null) =>
    regions.find((region) => region.id === regionId)?.name === "Красноярский край";

  // Восстановление активного ingest-job после рефреша — снова подключаемся
  // к waitForJob и показываем прогресс, не выглядим будто всё пропало.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    let savedJobId: string | null = null;
    try { savedJobId = localStorage.getItem(INGEST_JOB_KEY); } catch {}
    if (!savedJobId) return;
    setSubmitting(true);
    (async () => {
      try {
        const finalJob = await waitForJob(token, savedJobId!, (j) => {
          if (!cancelled) setProgressJob(j);
        });
        if (cancelled) return;
        try { localStorage.removeItem(INGEST_JOB_KEY); } catch {}
        if (finalJob.status === "failed") {
          setError(finalJob.error || "Импорт не удался");
        } else if (finalJob.status === "cancelled") {
          setError("Импорт отменён. Уже скачанные посты сохранены в БД.");
        } else if (finalJob.result) {
          setLastResult(finalJob.result as unknown as IngestResponse);
        }
        await refreshPublics();
        await onIngested?.();
      } catch {
        try { localStorage.removeItem(INGEST_JOB_KEY); } catch {}
      } finally {
        if (!cancelled) {
          setSubmitting(false);
          setProgressJob(null);
        }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true);
    setError(null);
    setLastResult(null);
    setProgressJob(null);
    try {
      const dateFrom = historyDateFrom(historyAmount, historyUnit);
      const { job_id } = await ingestLink(token, {
        url: url.trim(),
        fetch_comments: true,
        date_from: dateFrom.toISOString(),
        date_to: null,
      });
      try { localStorage.setItem(INGEST_JOB_KEY, job_id); } catch {}
      const finalJob = await waitForJob(token, job_id, (j) => setProgressJob(j));
      try { localStorage.removeItem(INGEST_JOB_KEY); } catch {}
      if (finalJob.status === "failed") {
        throw new Error(finalJob.error || "Импорт не удался");
      }
      if (finalJob.status === "cancelled") {
        setError("Импорт отменён. Уже скачанные посты сохранены в БД.");
      }
      if (finalJob.result) {
        setLastResult(finalJob.result as unknown as IngestResponse);
      }
      setUrl("");
      await refreshPublics();
      await onIngested?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
      setProgressJob(null);
    }
  };

  const handleDeletePublic = async (publicId: string) => {
    setDeletingPublicId(publicId);
    setError(null);
    try {
      await apiDeleteImportedPublic(token, publicId);
      setLastResult(null);
      await refreshPublics();
      await onIngested?.();
      setPublicToDelete(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingPublicId(null);
    }
  };

  const handleLocationChange = async (
    publicId: string,
    regionId: string,
    municipalityName: string | null,
  ) => {
    setSavingRegionPublicId(publicId);
    setError(null);
    try {
      await apiUpdatePublicRegion(
        token,
        publicId,
        regionId || null,
        isKrasnoyarskRegion(regionId) ? municipalityName || null : null,
      );
      await refreshPublics();
      await onIngested?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingRegionPublicId(null);
    }
  };

  return (
    <section className="vk-ingest-panel">
      <div>
        <h3 style={{ margin: 0 }}>Добавить площадку VK / Одноклассники / Telegram</h3>
        <p className="muted" style={{ marginTop: 6, marginBottom: 0 }}>
          {LINK_HINT}
        </p>
      </div>

      {showFileImport ? (
        <PublicImportTab orgId={orgId} embedded />
      ) : (
        <button
          type="button"
          className="btn btn-outline"
          style={{ marginTop: 10, marginBottom: 4 }}
          onClick={() => setShowFileImport(true)}
        >
          📊 Импорт из файла (xlsx / csv)
        </button>
      )}

      {!showFileImport && (
        <form onSubmit={handleSubmit} className="vk-ingest-form">
          <input
            className="vk-ingest-input"
            type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
            placeholder="https://vk.com/... , https://ok.ru/group/... или https://t.me/..."
          required
        />
        <div className="vk-ingest-controls">
          <label className="vk-ingest-history">
            <span className="muted">Импортировать историю за</span>
            <input
              className="vk-ingest-count-input"
              type="number"
              value={historyAmount}
              min={1}
              onChange={(e) =>
                setHistoryAmount(Math.max(1, Math.trunc(Number(e.target.value) || 1)))
              }
            />
            <select
              value={historyUnit}
              onChange={(e) => setHistoryUnit(e.target.value as HistoryUnit)}
            >
              {HISTORY_UNITS.map((u) => (
                <option key={u.value} value={u.value}>{u.label}</option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting || !url.trim()}
          >
            {submitting ? "Добавляем..." : "Добавить площадку"}
          </button>
        </div>
        <p className="muted vk-ingest-note">
          История подтянется один раз при добавлении. Дальше новые комментарии
          собирает автопарсер автоматически.
        </p>
      </form>
        )}

      {error && (
        <div style={{ marginTop: 12, color: "#ff7a85" }}>
          Ошибка: {error}
        </div>
      )}

      {progressJob && (progressJob.status === "running" || progressJob.status === "pending") && (
        <div
          style={{
            marginTop: 14,
            padding: "12px 14px",
            borderRadius: 10,
            background: "rgba(120, 160, 255, 0.08)",
            border: "1px solid rgba(120, 160, 255, 0.25)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13, alignItems: "center" }}>
            <span>{progressJob.message || "Импорт идёт…"}</span>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="muted">
                {progressJob.total != null
                  ? `${progressJob.done}/${progressJob.total}`
                  : `${progressJob.done}`}
              </span>
              <button
                type="button"
                className="btn btn-outline btn-compact"
                disabled={progressJob.cancel_requested}
                onClick={() => {
                  void apiCancelJob(token, progressJob.id).catch(() => {});
                }}
              >
                {progressJob.cancel_requested ? "Отмена…" : "Отменить"}
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
                  progressJob.total && progressJob.total > 0
                    ? `${Math.min(100, (progressJob.done / progressJob.total) * 100)}%`
                    : "30%",
                height: "100%",
                background: "linear-gradient(90deg, #6aa9ff, #b58dff)",
                transition: "width 0.4s ease",
                ...(progressJob.total
                  ? {}
                  : { animation: "vk-ingest-indet 1.4s ease-in-out infinite" }),
              }}
            />
          </div>
        </div>
      )}

      {lastResult && (
        <div
          style={{
            marginTop: 14,
            padding: "12px 14px",
            borderRadius: 10,
            background: "rgba(80, 220, 120, 0.08)",
            border: "1px solid rgba(80, 220, 120, 0.25)",
          }}
        >
          <div style={{ fontWeight: 600 }}>
            {TYPE_LABEL[lastResult.type]} добавлен: {lastResult.canonical_url}
          </div>
          <div className="muted" style={{ marginTop: 4, fontSize: 13 }}>
            Публикаций обработано: {lastResult.publications_imported} · Новых комментариев: {lastResult.comments_imported}
          </div>
        </div>
      )}

      <div className="settings-stats vk-ingest-stats">
        <div className="settings-stat">
          <span className="settings-stat-value">{publics.length}</span>
          <span className="settings-stat-label">Площадок</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">{totalLinks}</span>
          <span className="settings-stat-label">Ссылок</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">{formatMetricValue(totalPublications)}</span>
          <span className="settings-stat-label">Публикаций</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">{formatMetricValue(totalViews)}</span>
          <span className="settings-stat-label">Просмотров</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {summary ? formatMetricValue(summary.comments_count) : "—"}
          </span>
          <span className="settings-stat-label">Комментариев в БД</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {summary ? formatPercent(summary.classification_percent) : "—"}
          </span>
          <span className="settings-stat-label">Классифицировано</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {queued != null ? formatMetricValue(queued) : "—"}
          </span>
          <span className="settings-stat-label">В очереди / без анализа</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {summary ? formatMetricValue(summary.failed_count) : "—"}
          </span>
          <span className="settings-stat-label">Ошибок классификации</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {summary ? formatMetricValue(summary.stale_links_count) : "—"}
          </span>
          <span className="settings-stat-label">Устаревших ссылок</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {summary ? formatAge(summary.oldest_data_age_hours) : "—"}
          </span>
          <span className="settings-stat-label">Самые старые данные</span>
        </div>
      </div>

      <div style={{ marginTop: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h4 style={{ margin: 0 }}>Состояние данных по площадкам</h4>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              className={`btn-arrow-toggle ${showImported ? "open" : ""}`}
              aria-expanded={showImported}
              title={showImported ? "Скрыть список" : "Показать список"}
              onClick={() => setShowImported((prev) => !prev)}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                <polyline points="4,6 8,10 12,6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <button
              type="button"
              className={`btn-icon-refresh ${loadingPublics ? "spinning" : ""}`}
              title={loadingPublics ? "Обновление…" : "Обновить список"}
              aria-label="Обновить список"
              onClick={() => void refreshPublics()}
              disabled={loadingPublics}
            >
              <RefreshIcon />
            </button>
          </div>
        </div>

        {showImported && (
          <>
            {rows.length === 0 ? (
              <p className="muted" style={{ marginTop: 8 }}>
                Площадок пока нет. Вставьте ссылку выше и добавьте первую.
              </p>
            ) : (
              <div className="pub-state-table-wrap">
                <table className="pub-state-table">
                <thead>
                  <tr>
                    <th>Площадка</th>
                    <th className="col-net">Сеть</th>
                    <th className="col-region">Регион</th>
                    <th className="col-municipality">Муниципалитет</th>
                    <th className="col-range">Данные за</th>
                    <th className="col-num">Публ.</th>
                    <th className="col-num">Комм.</th>
                    <th className="col-num">Классиф.%</th>
                    <th className="col-num">Ошибки классиф.</th>
                    <th className="col-check">Автопарсинг</th>
                    <th className="col-act" aria-label="Действия" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <Fragment key={r.id}>
                      <tr className={r.error ? "has-error" : ""}>
                        <td className="col-name">
                          {r.primaryUrl ? (
                            <a href={r.primaryUrl} target="_blank" rel="noreferrer">
                              {r.name}
                            </a>
                          ) : (
                            <span>{r.name}</span>
                          )}
                        </td>
                        <td className="col-net">
                          {r.networks.map((n) => (
                            <span key={n} className={`net-badge net-${n.toLowerCase()}`}>{n}</span>
                          ))}
                        </td>
                        <td className="col-region">
                          <select
                            className="public-region-select"
                            value={r.regionId ?? ""}
                            disabled={savingRegionPublicId === r.id}
                            onChange={(e) => void handleLocationChange(r.id, e.target.value, null)}
                          >
                            <option value="">Не задан</option>
                            {regions.map((region) => (
                              <option key={region.id} value={region.id}>{region.name}</option>
                            ))}
                          </select>
                        </td>
                        <td className="col-municipality">
                          {isKrasnoyarskRegion(r.regionId) ? (
                            <select
                              className="public-region-select"
                              value={r.municipalityName ?? ""}
                              disabled={savingRegionPublicId === r.id}
                              onChange={(e) =>
                                void handleLocationChange(
                                  r.id,
                                  r.regionId ?? "",
                                  e.target.value || null,
                                )
                              }
                            >
                              <option value="">Не задан</option>
                              {KRASNOYARSK_MUNICIPALITIES.map((municipality) => (
                                <option key={municipality.label} value={municipality.label}>
                                  {municipality.label}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="col-range">{r.range ?? "—"}</td>
                        <td className="col-num">{num(r.publications)}</td>
                        <td className="col-num">{num(r.comments)}</td>
                        <td className="col-num">
                          {r.classificationPercent == null
                            ? "—"
                            : formatPercent(r.classificationPercent)}
                        </td>
                        <td className="col-num">
                          {r.classificationErrors > 0 ? num(r.classificationErrors) : "—"}
                        </td>
                        <td className="col-check">
                          {r.error ? (
                            <span className="check-error" title={r.error.raw}>⚠ ошибка</span>
                          ) : (
                            <span className="muted">{relativeCheck(r.lastCheck)}</span>
                          )}
                        </td>
                        <td className="col-act">
                          <button
                            type="button"
                            className="vk-public-del"
                            disabled={deletingPublicId !== null}
                            onClick={() => setPublicToDelete(r)}
                          >
                            {deletingPublicId === r.id ? "…" : "Удалить"}
                          </button>
                        </td>
                      </tr>
                      {r.error && (
                        <tr className="pub-state-error-row">
                          <td colSpan={11}>
                            <span className={`net-badge net-${r.error.network.toLowerCase()}`}>
                              {r.error.network}
                            </span>{" "}
                            {describeAutoparseError(r.error.raw)}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {publicToDelete ? (
        <ConfirmDialog
          title="Удалить площадку?"
          description={
            <>
              <p>«{publicToDelete.name}» будет удалена безвозвратно.</p>
              <p className="org-warning">
                Вместе с площадкой удалятся импортированные публикации и комментарии.
              </p>
            </>
          }
          busy={deletingPublicId === publicToDelete.id}
          onCancel={() => setPublicToDelete(null)}
          onConfirm={() => void handleDeletePublic(publicToDelete.id)}
        />
      ) : null}
    </section>
  );
}

export default VkIngestPanel;
