import { useEffect, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { Link, NavLink, useParams } from "react-router-dom";

import {
  apiBackfillAddressCaseGeocoding,
  apiCancelJob,
  apiChangeMyPassword,
  apiClassificationReview,
  apiClassificationReviewTaxonomy,
  apiExportAddressCases,
  apiGetAddressCaseGeocodingStats,
  apiInferPublicLocations,
  apiReclassifyVk,
  apiRebuildVkAnalytics,
  apiResolveClassificationReview,
  apiResumeWorker,
  apiRotateGeoCache,
  waitForJob,
  type AddressCaseGeocodingBackfillResponse,
  type AddressCaseGeocodingStats,
  type ClassificationReviewItem,
  type ClassificationReviewTaxonomy,
  type JobInfo,
} from "../api";
import { SETTINGS_SECTIONS, type SettingsSection } from "../appShell/routeConfig";
import { useMe } from "../hooks/useMe";
import { useOrganizations } from "../hooks/useOrganizations";
import { downloadBlob } from "../lib/downloadBlob";
import { AutoparseSettingsSection } from "./AutoparseSettingsSection";

export type SettingsPageProps = {
  authToken: string;
  currentUser: string;
  deepLlmAnalysis: boolean;
  setDeepLlmAnalysis: Dispatch<SetStateAction<boolean>>;
  prefilterEnabled: boolean;
  setPrefilterEnabled: Dispatch<SetStateAction<boolean>>;
  onLogout: () => void;
};

const ROLE_LABELS: Record<string, string> = {
  superadmin: "Суперадминистратор",
  admin: "Администратор",
  minion: "Пользователь",
};

const REVIEW_PAGE_SIZE = 25;
const ADDRESS_GEOCODING_JOB_KEY = "media-events:active-address-geocoding-job";

function cropReviewText(text: string, limit = 360) {
  const value = (text || "").replace(/\s+/g, " ").trim();
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

function ClassificationReviewSection({ token }: { token: string }) {
  const [taxonomy, setTaxonomy] = useState<ClassificationReviewTaxonomy | null>(null);
  const [items, setItems] = useState<ClassificationReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<"success" | "error">("success");

  const loadPage = async (nextOffset = 0, append = false) => {
    setLoading(true);
    setMessage("");
    try {
      const [taxonomyResult, page] = await Promise.all([
        taxonomy ? Promise.resolve(taxonomy) : apiClassificationReviewTaxonomy(token),
        apiClassificationReview(token, { limit: REVIEW_PAGE_SIZE, offset: nextOffset }),
      ]);
      setTaxonomy(taxonomyResult);
      setItems((prev) => (append ? [...prev, ...page.items] : page.items));
      setTotal(page.total);
      setOffset(page.offset + page.items.length);
      setHasMore(page.has_more);
    } catch (error) {
      setMessageType("error");
      setMessage(error instanceof Error ? error.message : "Не удалось загрузить комментарии.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) return;
    void loadPage(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const resolveItem = async (
    item: ClassificationReviewItem,
    payload: { category: string; subcategory?: string; case?: string },
  ) => {
    setSavingId(item.analysis_id);
    setMessage("");
    try {
      await apiResolveClassificationReview(token, item.analysis_id, payload);
      setItems((prev) => prev.filter((candidate) => candidate.analysis_id !== item.analysis_id));
      setTotal((value) => Math.max(0, value - 1));
      setMessageType("success");
      setMessage("Категория сохранена.");
    } catch (error) {
      setMessageType("error");
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить категорию.");
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="card-glass">
      <div className="settings-review-head">
        <div>
          <h3>Проверка категорий</h3>
          <p className="hint-text">
            Комментарии, где LLM завершила классификацию, но не смогла выбрать категорию.
          </p>
        </div>
        <button type="button" className="btn btn-outline" onClick={() => loadPage(0, false)} disabled={loading}>
          {loading ? "Обновляем..." : "Обновить"}
        </button>
      </div>

      <div className="settings-review-total">
        <span className="settings-stat-value">{total.toLocaleString("ru-RU")}</span>
        <span className="settings-stat-label">требуют ручной категории</span>
      </div>

      {message && <p className={`message ${messageType}`}>{message}</p>}

      {!loading && items.length === 0 ? (
        <p className="hint-text">Комментариев на проверку нет.</p>
      ) : (
        <div className="settings-review-list">
          {items.map((item) => (
            <ClassificationReviewRow
              key={item.analysis_id}
              item={item}
              taxonomy={taxonomy}
              saving={savingId === item.analysis_id}
              onResolve={(payload) => resolveItem(item, payload)}
            />
          ))}
        </div>
      )}

      {hasMore && (
        <div className="settings-action-row">
          <button type="button" className="btn btn-outline" onClick={() => loadPage(offset, true)} disabled={loading}>
            {loading ? "Загружаем..." : "Показать ещё"}
          </button>
        </div>
      )}
    </div>
  );
}

function ClassificationReviewRow({
  item,
  taxonomy,
  saving,
  onResolve,
}: {
  item: ClassificationReviewItem;
  taxonomy: ClassificationReviewTaxonomy | null;
  saving: boolean;
  onResolve: (payload: { category: string; subcategory?: string; case?: string }) => void;
}) {
  const categories = taxonomy?.categories ?? [];
  const initialCategory = String(item.hierarchy?.category || "");
  const [category, setCategory] = useState(initialCategory && categories.includes(initialCategory) ? initialCategory : "");
  const [subcategory, setSubcategory] = useState(String(item.hierarchy?.subcategory || ""));
  const [caseName, setCaseName] = useState(String(item.hierarchy?.case || ""));
  const subcategories = category ? taxonomy?.subcategories[category] ?? [] : [];

  useEffect(() => {
    if (subcategory && !subcategories.includes(subcategory)) {
      setSubcategory("");
    }
  }, [subcategory, subcategories]);

  return (
    <article className="settings-review-item">
      <div className="settings-review-meta">
        <span>{item.public_name || "Паблик"}</span>
        {item.sentiment && <span>{item.sentiment}</span>}
        {item.message_type && <span>{item.message_type}</span>}
      </div>
      <p className="settings-review-text">{cropReviewText(item.text)}</p>
      {item.summary && <p className="hint-text">{item.summary}</p>}
      {item.publication_url && (
        <a className="settings-review-link" href={item.publication_url} target="_blank" rel="noreferrer">
          Открыть публикацию
        </a>
      )}

      <div className="settings-review-form">
        <label>
          Категория
          <select
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              setSubcategory("");
            }}
          >
            <option value="">Не выбрано</option>
            {categories.map((candidate) => (
              <option key={candidate} value={candidate}>
                {candidate}
              </option>
            ))}
          </select>
        </label>

        <label>
          Подкатегория
          <select
            value={subcategory}
            onChange={(event) => setSubcategory(event.target.value)}
            disabled={!category || subcategories.length === 0}
          >
            <option value="">Не выбрано</option>
            {subcategories.map((candidate) => (
              <option key={candidate} value={candidate}>
                {candidate}
              </option>
            ))}
          </select>
        </label>

        <label>
          Кейс
          <input value={caseName} onChange={(event) => setCaseName(event.target.value)} placeholder="Адрес или краткий кейс" />
        </label>

        <button
          type="button"
          className="btn btn-primary"
          disabled={!category || saving}
          onClick={() => onResolve({ category, subcategory, case: caseName })}
        >
          {saving ? "Сохраняем..." : "Сохранить"}
        </button>
      </div>
    </article>
  );
}

function AddressCasesExportSection({ token }: { token: string }) {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [limit, setLimit] = useState(50_000);
  const [geoStats, setGeoStats] = useState<AddressCaseGeocodingStats | null>(null);
  const [geoStatsLoading, setGeoStatsLoading] = useState(false);
  const [geoStatsError, setGeoStatsError] = useState("");
  const [geoJob, setGeoJob] = useState<JobInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<"success" | "error">("success");

  const loadGeoStats = async () => {
    setGeoStatsLoading(true);
    setGeoStatsError("");
    try {
      const stats = await apiGetAddressCaseGeocodingStats(token);
      setGeoStats(stats);
    } catch (error) {
      setGeoStats(null);
      setGeoStatsError(
        error instanceof Error
          ? error.message
          : "Не удалось загрузить статистику геокодинга адресных кейсов.",
      );
    } finally {
      setGeoStatsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setGeoStatsLoading(true);
    setGeoStatsError("");
    apiGetAddressCaseGeocodingStats(token)
      .then((stats) => {
        if (!cancelled) setGeoStats(stats);
      })
      .catch((error) => {
        if (!cancelled) {
          setGeoStats(null);
          setGeoStatsError(
            error instanceof Error
              ? error.message
              : "Не удалось загрузить статистику геокодинга адресных кейсов.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setGeoStatsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    let savedJobId: string | null = null;
    try { savedJobId = localStorage.getItem(ADDRESS_GEOCODING_JOB_KEY); } catch {}
    if (!savedJobId) return;
    (async () => {
      try {
        const finalJob = await waitForJob(token, savedJobId!, (job) => {
          if (!cancelled) setGeoJob(job);
        });
        if (cancelled) return;
        try { localStorage.removeItem(ADDRESS_GEOCODING_JOB_KEY); } catch {}
        await loadGeoStats();
        if (finalJob.status === "failed") {
          setMessageType("error");
          setMessage(finalJob.error || "Догеокодинг адресных кейсов завершился ошибкой.");
        } else if (finalJob.status === "cancelled") {
          setMessageType("error");
          setMessage("Догеокодинг адресных кейсов отменен.");
        } else {
          const result = finalJob.result as Partial<AddressCaseGeocodingBackfillResponse> | null;
          setMessageType("success");
          setMessage(
            `Догеокодинг завершен: запросов ${result?.requests_made ?? 0}, новых координат ${result?.geocoded ?? 0}, miss ${result?.missed ?? 0}.`,
          );
        }
      } catch {
        try { localStorage.removeItem(ADDRESS_GEOCODING_JOB_KEY); } catch {}
      } finally {
        if (!cancelled) setGeoJob(null);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const doBackfill = async () => {
    setGeoJob(null);
    setMessage("");
    try {
      const { job_id } = await apiBackfillAddressCaseGeocoding(token);
      try { localStorage.setItem(ADDRESS_GEOCODING_JOB_KEY, job_id); } catch {}
      const finalJob = await waitForJob(token, job_id, (job) => setGeoJob(job));
      try { localStorage.removeItem(ADDRESS_GEOCODING_JOB_KEY); } catch {}
      await loadGeoStats();
      if (finalJob.status === "failed") {
        throw new Error(finalJob.error || "Догеокодинг адресных кейсов завершился ошибкой.");
      }
      if (finalJob.status === "cancelled") {
        setMessageType("error");
        setMessage("Догеокодинг адресных кейсов отменен.");
        return;
      }
      const result = (finalJob.result || {}) as Partial<AddressCaseGeocodingBackfillResponse>;
      setMessageType("success");
      setMessage(
        `Догеокодинг: запросов ${result.requests_made}, новых координат ${result.geocoded}, miss ${result.missed}, уже было в кэше ${result.already_cached}, свежих отказов пропущено ${result.fresh_miss_skipped}.`,
      );
    } catch (error) {
      setMessageType("error");
      setMessage(
        error instanceof Error
          ? error.message
          : "Не удалось запустить догеокодинг адресных кейсов.",
      );
    } finally {
      setGeoJob(null);
    }
  };

  const doExport = async () => {
    setLoading(true);
    setMessage("");
    try {
      const blob = await apiExportAddressCases(token, {
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        limit,
      });
      const from = dateFrom || "all";
      const to = dateTo || "all";
      downloadBlob(blob, `address-cases-${from}-${to}.xlsx`);
      setMessageType("success");
      setMessage("Файл выгружен.");
    } catch (error) {
      setMessageType("error");
      setMessage(error instanceof Error ? error.message : "Не удалось выгрузить адресные кейсы.");
    } finally {
      setLoading(false);
    }
  };

  const geoJobRunning = geoJob?.status === "running" || geoJob?.status === "pending";
  const geoJobPercent =
    geoJob?.total && geoJob.total > 0
      ? Math.min(100, (geoJob.done / geoJob.total) * 100)
      : null;

  return (
    <div className="card-glass">
      <div className="settings-stats address-case-stats">
        <div className="settings-stat">
          <span className="settings-stat-value">
            {geoStatsLoading ? "..." : geoStats ? geoStats.geocoded_cases.toLocaleString("ru-RU") : "—"}
          </span>
          <span className="settings-stat-label">С координатой</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {geoStatsLoading ? "..." : geoStats ? geoStats.rejected_cases.toLocaleString("ru-RU") : "—"}
          </span>
          <span className="settings-stat-label">Не принял геокодер</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {geoStatsLoading ? "..." : geoStats ? geoStats.untried_cases.toLocaleString("ru-RU") : "—"}
          </span>
          <span className="settings-stat-label">Еще не пробовали</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {geoStatsLoading ? "..." : geoStats ? geoStats.total_cases.toLocaleString("ru-RU") : "—"}
          </span>
          <span className="settings-stat-label">Адресных кейсов</span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-value">
            {geoStatsLoading ? "..." : geoStats ? geoStats.cache_total_entries.toLocaleString("ru-RU") : "—"}
          </span>
          <span className="settings-stat-label">Записей geo-cache</span>
        </div>
      </div>

      {geoStats ? (
        <p className="hint-text">
          Учитываются валидные адресные кейсы карты. Комментариев в них:{" "}
          {geoStats.total_mentions.toLocaleString("ru-RU")}; с координатами:{" "}
          {geoStats.geocoded_mentions.toLocaleString("ru-RU")}; геокодер не принял:{" "}
          {geoStats.rejected_mentions.toLocaleString("ru-RU")}; еще не пробовали:{" "}
          {geoStats.untried_mentions.toLocaleString("ru-RU")}; всего без координат:{" "}
          {geoStats.not_geocoded_mentions.toLocaleString("ru-RU")}.
          {geoStats.skipped_invalid_cases > 0
            ? ` Отброшено невалидных кейсов: ${geoStats.skipped_invalid_cases.toLocaleString("ru-RU")}.`
            : ""}
        </p>
      ) : null}
      {geoStatsError ? <p className="message error">{geoStatsError}</p> : null}

      <div className="settings-address-actions">
        <button
          type="button"
          className="btn btn-outline"
          onClick={doBackfill}
          disabled={
            geoJobRunning
            || geoStatsLoading
            || !geoStats
            || geoStats.not_geocoded_cases <= 0
          }
        >
          {geoJobRunning ? "Догеокодим..." : "Догеокодить недогеокодированное"}
        </button>
      </div>

      {geoJobRunning ? (
        <div className="settings-job-progress">
          <div className="settings-job-progress-head">
            <span>{geoJob?.message || "Догеокодинг адресных кейсов..."}</span>
            <div className="settings-job-progress-actions">
              <span className="muted">
                {geoJob?.total != null
                  ? `${geoJob.done}/${geoJob.total}`
                  : `${geoJob?.done ?? 0}`}
              </span>
              {geoJob ? (
                <button
                  type="button"
                  className="btn btn-outline btn-compact"
                  disabled={geoJob.cancel_requested}
                  onClick={() => {
                    void apiCancelJob(token, geoJob.id).catch(() => {});
                  }}
                >
                  {geoJob.cancel_requested ? "Отмена..." : "Отменить"}
                </button>
              ) : null}
            </div>
          </div>
          <div className="settings-job-progress-bar" aria-hidden="true">
            <div
              className="settings-job-progress-fill"
              style={{ width: geoJobPercent != null ? `${geoJobPercent}%` : "30%" }}
            />
          </div>
        </div>
      ) : null}

      <div className="settings-review-head">
        <div>
          <h3>Выгрузка адресных кейсов</h3>
          <p className="hint-text">
            XLSX с комментариями, hierarchy/entities, площадкой, регионом, публикацией и готовой командой для локального debug-скрипта.
          </p>
        </div>
      </div>

      <div className="settings-review-form">
        <label>
          С даты
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
        </label>
        <label>
          По дату
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
        </label>
        <label>
          Лимит строк
          <input
            type="number"
            min={1}
            max={200000}
            step={1000}
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value) || 1)}
          />
        </label>
        <button type="button" className="btn btn-primary" onClick={doExport} disabled={loading}>
          {loading ? "Готовим файл..." : "Выгрузить XLSX"}
        </button>
      </div>

      {message && <p className={`message ${messageType}`}>{message}</p>}
    </div>
  );
}

export function SettingsPage({
  authToken,
  currentUser,
  deepLlmAnalysis,
  setDeepLlmAnalysis,
  prefilterEnabled,
  setPrefilterEnabled,
  onLogout,
}: SettingsPageProps) {
  const { section } = useParams<{ section: string }>();
  const known = SETTINGS_SECTIONS.some((item) => item.slug === section);
  const requestedSection: SettingsSection = known ? (section as SettingsSection) : "account";

  const meQuery = useMe(authToken);
  const me = meQuery.data;
  const email = me?.email || currentUser;
  const isOrgAdmin = me?.role === "admin" || me?.role === "superadmin";
  const isSuperadmin = me?.role === "superadmin";
  const isMinion = me?.role === "minion";
  const activeSection: SettingsSection =
    requestedSection === "analytics" && (meQuery.isLoading || !isOrgAdmin) ? "account" : requestedSection;
  const minionPublicsQuery = useOrganizations(isMinion ? authToken : null);
  // Очистка геокэша — админская операция (бэкенд отвечает 403 остальным).
  const isAdmin = isOrgAdmin;

  // Состояние очистки геокэша. Потерялось при слиянии веток: JSX кнопки приехал
  // из master, а состояние, на которое он ссылается, — нет, и ветка перестала
  // собираться. Восстановлено здесь.
  const [geoCacheLoading, setGeoCacheLoading] = useState(false);
  const [geoCacheMessage, setGeoCacheMessage] = useState("");
  const [geoCacheMessageType, setGeoCacheMessageType] = useState<"success" | "error">(
    "success",
  );
  const [classificationLoading, setClassificationLoading] = useState(false);
  const [classificationMessage, setClassificationMessage] = useState("");
  const [classificationMessageType, setClassificationMessageType] = useState<
    "success" | "error"
  >("success");
  const [publicLocationLoading, setPublicLocationLoading] = useState(false);
  const [publicLocationMessage, setPublicLocationMessage] = useState("");
  const [publicLocationMessageType, setPublicLocationMessageType] = useState<
    "success" | "error"
  >("success");
  const [fullRebuildConfirmOpen, setFullRebuildConfirmOpen] = useState(false);
  const [fullRebuildLoading, setFullRebuildLoading] = useState(false);
  const [fullRebuildJob, setFullRebuildJob] = useState<JobInfo | null>(null);
  const [fullRebuildMessage, setFullRebuildMessage] = useState("");
  const [fullRebuildMessageType, setFullRebuildMessageType] = useState<"success" | "error">(
    "success",
  );
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState("");
  const [passwordMessageType, setPasswordMessageType] = useState<"success" | "error">(
    "success",
  );

  const handleRotateGeoCache = async () => {
    setGeoCacheLoading(true);
    setGeoCacheMessage("");
    try {
      const result = await apiRotateGeoCache(authToken);
      setGeoCacheMessageType("success");
      setGeoCacheMessage(
        result.rotated
          ? "Кэш карты очищен. Координаты пересоберутся при следующем открытии карты."
          : "Кэш уже пуст — очищать нечего.",
      );
    } catch (error) {
      setGeoCacheMessageType("error");
      setGeoCacheMessage(
        error instanceof Error ? error.message : "Не удалось очистить кэш карты.",
      );
    } finally {
      setGeoCacheLoading(false);
    }
  };

  const handleStartUnclassified = async () => {
    setClassificationLoading(true);
    setClassificationMessage("");
    try {
      const result = await apiReclassifyVk(authToken, "unclassified");
      await apiResumeWorker(authToken);
      setClassificationMessageType("success");
      setClassificationMessage(
        result.requeued > 0
          ? `Поставлено в очередь: ${result.requeued}. Фоновая классификация запущена.`
          : "Неклассифицированных комментариев не найдено.",
      );
    } catch (error) {
      setClassificationMessageType("error");
      setClassificationMessage(
        error instanceof Error
          ? error.message
          : "Не удалось запустить классификацию неклассифицированных комментариев.",
      );
    } finally {
      setClassificationLoading(false);
    }
  };

  const handleInferPublicLocations = async () => {
    setPublicLocationLoading(true);
    setPublicLocationMessage("");
    try {
      const result = await apiInferPublicLocations(authToken);
      setPublicLocationMessageType("success");
      setPublicLocationMessage(
        result.updated_publics > 0
          ? `Обновлено площадок: ${result.updated_publics}. Регион заполнен у ${result.updated_region}, муниципалитет — у ${result.updated_municipality}.`
          : `Подходящих площадок не найдено. Проверено: ${result.considered}.`,
      );
    } catch (error) {
      setPublicLocationMessageType("error");
      setPublicLocationMessage(
        error instanceof Error
          ? error.message
          : "Не удалось автоматически подобрать регион и муниципалитет.",
      );
    } finally {
      setPublicLocationLoading(false);
    }
  };

  const handleFullAnalyticsRebuild = async () => {
    setFullRebuildConfirmOpen(false);
    setFullRebuildLoading(true);
    setFullRebuildJob(null);
    setFullRebuildMessage("");
    try {
      const { job_id } = await apiRebuildVkAnalytics(
        authToken,
        deepLlmAnalysis,
        null,
        prefilterEnabled,
        false,
        null,
      );
      const finalJob = await waitForJob(authToken, job_id, (job) => {
        setFullRebuildJob(job as JobInfo);
      });
      setFullRebuildJob(null);
      if (finalJob.status === "failed") {
        throw new Error(finalJob.error || "Не удалось выполнить полную пересборку аналитики.");
      }
      if (finalJob.status === "cancelled") {
        setFullRebuildMessageType("error");
        setFullRebuildMessage(finalJob.error || "Полная пересборка аналитики отменена.");
        return;
      }
      const result = finalJob.result as any;
      setFullRebuildMessageType("success");
      setFullRebuildMessage(
        result
          ? `Полная пересборка завершена. Болей: ${result.pain_count}. LLM: ${result.llm_classified_comments}, fallback: ${result.fallback_classified_comments}.`
          : "Полная пересборка аналитики завершена.",
      );
    } catch (error) {
      setFullRebuildJob(null);
      setFullRebuildMessageType("error");
      setFullRebuildMessage(
        error instanceof Error ? error.message : "Не удалось выполнить полную пересборку аналитики.",
      );
    } finally {
      setFullRebuildLoading(false);
    }
  };

  const handleChangePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPasswordMessage("");
    if (newPassword !== newPasswordConfirm) {
      setPasswordMessageType("error");
      setPasswordMessage("Новый пароль и подтверждение не совпадают.");
      return;
    }
    setPasswordLoading(true);
    try {
      await apiChangeMyPassword(authToken, currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setNewPasswordConfirm("");
      setPasswordMessageType("success");
      setPasswordMessage("Пароль изменён.");
    } catch (error) {
      setPasswordMessageType("error");
      setPasswordMessage(error instanceof Error ? error.message : "Не удалось изменить пароль.");
    } finally {
      setPasswordLoading(false);
    }
  };

  return (
    <div className="tab-content settings-tab">
      {fullRebuildConfirmOpen && (
        <div className="org-modal-backdrop" role="dialog" aria-modal="true">
          <div className="org-modal">
            <h3 className="org-modal-title">Запустить полную пересборку аналитики?</h3>
            <div className="org-modal-body">
              Это пересоберёт аналитический срез по всем площадкам и всем периодам. Операция может занять время.
              {deepLlmAnalysis ? " Сейчас включена глубокая LLM-аналитика, поэтому пересборка может быть заметно дольше." : ""}
            </div>
            <div className="org-modal-actions">
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setFullRebuildConfirmOpen(false)}
                disabled={fullRebuildLoading}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleFullAnalyticsRebuild}
                disabled={fullRebuildLoading}
              >
                Запустить пересборку
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="section-header">
        <h2>Настройки</h2>
      </div>

      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Разделы настроек">
          <span className="settings-nav-title">Настройки</span>
          {SETTINGS_SECTIONS.filter((item) => {
            if (item.slug === "analytics") return !isMinion;
            if (item.slug === "autoparse") return isOrgAdmin;
            if (item.slug === "address-cases-export") return isSuperadmin;
            return true;
          }).map((item) => (
            <NavLink
              key={item.slug}
              to={`/settings/${item.slug}`}
              className={({ isActive }) => `settings-nav-link${isActive ? " active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="settings-content">
          {activeSection === "account" ? (
            <>
              <div className="card-glass">
                <h3>Аккаунт</h3>
                {meQuery.isLoading && !me ? (
                  <p className="hint-text">Загружаем данные аккаунта…</p>
                ) : (
                  <dl className="settings-defs">
                    <div>
                      <dt>Имя</dt>
                      <dd>{me?.name || "—"}</dd>
                    </div>
                    <div>
                      <dt>Email</dt>
                      <dd>{email || "—"}</dd>
                    </div>
                    <div>
                      <dt>Роль</dt>
                      <dd>{me?.role ? ROLE_LABELS[me.role] ?? me.role : "—"}</dd>
                    </div>
                  </dl>
                )}
                {meQuery.isError && (
                  <p className="hint-text">Не удалось загрузить профиль. Попробуйте перезайти.</p>
                )}

                <form className="settings-password-form" onSubmit={handleChangePassword}>
                  <h4>Смена пароля</h4>
                  <div className="settings-password-grid">
                    <label className="field-label">
                      Текущий пароль
                      <input
                        type="password"
                        minLength={1}
                        maxLength={200}
                        value={currentPassword}
                        onChange={(event) => setCurrentPassword(event.target.value)}
                        autoComplete="current-password"
                        required
                      />
                    </label>
                    <label className="field-label">
                      Новый пароль
                      <input
                        type="password"
                        minLength={8}
                        maxLength={200}
                        value={newPassword}
                        onChange={(event) => setNewPassword(event.target.value)}
                        autoComplete="new-password"
                        required
                      />
                    </label>
                    <label className="field-label">
                      Повторите новый пароль
                      <input
                        type="password"
                        minLength={8}
                        maxLength={200}
                        value={newPasswordConfirm}
                        onChange={(event) => setNewPasswordConfirm(event.target.value)}
                        autoComplete="new-password"
                        required
                      />
                    </label>
                  </div>
                  <div className="settings-action-row">
                    <button type="submit" className="btn btn-outline" disabled={passwordLoading}>
                      {passwordLoading ? "Сохраняем..." : "Изменить пароль"}
                    </button>
                  </div>
                  {passwordMessage && (
                    <p className={`message ${passwordMessageType}`}>{passwordMessage}</p>
                  )}
                </form>

                <div className="settings-account-actions">
                  <button type="button" className="btn btn-outline" onClick={onLogout}>
                    Выйти из аккаунта
                  </button>
                </div>
              </div>

              {isMinion ? (
                <div className="card-glass" style={{ marginTop: "1rem" }}>
                  <h3>Организация</h3>
                  <dl className="settings-defs">
                    <div>
                      <dt>Организация</dt>
                      <dd>{me?.organization_name || "—"}</dd>
                    </div>
                  </dl>

                  <div className="settings-account-org-publics">
                    <h4>Площадки организации</h4>
                    {minionPublicsQuery.isLoading ? (
                      <p className="hint-text">Загружаем площадки…</p>
                    ) : minionPublicsQuery.isError ? (
                      <p className="hint-text">Не удалось загрузить список площадок.</p>
                    ) : (minionPublicsQuery.data ?? []).length === 0 ? (
                      <p className="hint-text">Площадки не назначены или недоступны.</p>
                    ) : (
                      <div className="settings-org-list">
                        {(minionPublicsQuery.data ?? []).map((publicItem) => (
                          <article key={publicItem.id} className="settings-org">
                            <h4>{publicItem.name}</h4>
                            {publicItem.region_name && (
                              <p className="hint-text">Регион: {publicItem.region_name}</p>
                            )}
                            {publicItem.municipality_name && (
                              <p className="hint-text">Муниципалитет: {publicItem.municipality_name}</p>
                            )}
                            {publicItem.links.length > 0 ? (
                              <ul className="settings-org-links">
                                {publicItem.links.map((link) => (
                                  <li key={link.id}>
                                    {link.url ? (
                                      <a href={link.url} target="_blank" rel="noreferrer">
                                        {link.url}
                                      </a>
                                    ) : (
                                      <span>{link.social_network_name || link.social_network_code || "Площадка"}</span>
                                    )}
                                    <span className="muted">{link.social_network_name || link.social_network_code || "—"}</span>
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p className="hint-text">Ссылки не указаны.</p>
                            )}
                          </article>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : null}

              {isOrgAdmin ? (
                <div className="card-glass" style={{ marginTop: "1rem" }}>
                  <h3>Организация</h3>
                  <div className="settings-account-actions">
                    <Link className="btn btn-outline" to="/organization">
                      Перейти в раздел «Организация»
                    </Link>
                  </div>
                </div>
              ) : null}
            </>
          ) : activeSection === "classification-review" ? (
            <ClassificationReviewSection token={authToken} />
          ) : activeSection === "address-cases-export" ? (
            isSuperadmin ? (
              <AddressCasesExportSection token={authToken} />
            ) : (
              <div className="card-glass">
                <p className="hint-text">Раздел доступен только суперадминистратору.</p>
              </div>
            )
          ) : activeSection === "autoparse" ? (
            isOrgAdmin ? (
              <AutoparseSettingsSection
                token={authToken}
                canEdit={me?.role === "superadmin"}
              />
            ) : (
              <div className="card-glass">
                <p className="hint-text">Раздел доступен только администраторам.</p>
              </div>
            )
          ) : (
            <div className="card-glass">
              <h3>Настройки аналитики</h3>
              <p className="hint-text">Применяются при формировании отчёта на странице «Аналитика».</p>

              <div className="settings-toggles">
                <label className="settings-toggle">
                  <input
                    className="an-switch-input"
                    type="checkbox"
                    checked={deepLlmAnalysis}
                    onChange={(e) => setDeepLlmAnalysis(e.target.checked)}
                  />
                  <span className="an-switch" />
                  <span className="settings-toggle-text">
                    <strong>Глубокая LLM-аналитика</strong>
                    <span className="muted">
                      Прогнать все комментарии через LLM (Ollama). Качество категоризации заметно
                      лучше, но на 1000+ комментариев уходят минуты.
                    </span>
                  </span>
                </label>

                <label className={`settings-toggle${deepLlmAnalysis ? "" : " disabled"}`}>
                  <input
                    className="an-switch-input"
                    type="checkbox"
                    checked={prefilterEnabled}
                    onChange={(e) => setPrefilterEnabled(e.target.checked)}
                    disabled={!deepLlmAnalysis}
                  />
                  <span className="an-switch" />
                  <span className="settings-toggle-text">
                    <strong>Префильтр (в разработке)</strong>
                    <span className="muted">
                      Дешёвый 3b-префильтр отсекает шум до 14b — быстрее и дешевле. Выключите, чтобы
                      прогнать через 14b всё и сравнить скорость с качеством. Работает только вместе
                      с глубокой LLM-аналитикой.
                    </span>
                  </span>
                </label>
              </div>

              <div className="settings-maintenance">
                <div>
                  <h4>Полная пересборка аналитики</h4>
                  <p className="muted">
                    Пересобирает общий аналитический срез по всем площадкам и всем периодам из данных в базе.
                    Операция может занять время, поэтому запускайте её осознанно.
                  </p>
                  {!isAdmin && !meQuery.isLoading && (
                    <p className="hint-text">Полная пересборка доступна только администратору и суперадминистратору.</p>
                  )}
                </div>
                <div className="settings-action-row">
                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={() => setFullRebuildConfirmOpen(true)}
                    disabled={!isAdmin || fullRebuildLoading}
                  >
                    {fullRebuildLoading ? "Пересобираем..." : "Запустить полную пересборку аналитики"}
                  </button>
                </div>
                {fullRebuildJob && (
                  <div className="settings-job-progress">
                    <div className="settings-job-progress-head">
                      <span>{fullRebuildJob.message || "Полная пересборка аналитики..."}</span>
                      <span className="muted">
                        {fullRebuildJob.total != null
                          ? `${fullRebuildJob.done.toLocaleString("ru-RU")} / ${fullRebuildJob.total.toLocaleString("ru-RU")}`
                          : ""}
                      </span>
                    </div>
                    <div className="settings-job-progress-bar" aria-hidden="true">
                      <div
                        className="settings-job-progress-fill"
                        style={{
                          width:
                            fullRebuildJob.total && fullRebuildJob.total > 0
                              ? `${Math.min(100, (fullRebuildJob.done / fullRebuildJob.total) * 100)}%`
                              : "30%",
                        }}
                      />
                    </div>
                  </div>
                )}
                {fullRebuildMessage && (
                  <p className={`message ${fullRebuildMessageType}`}>
                    {fullRebuildMessage}
                  </p>
                )}
              </div>

              {isSuperadmin ? (
                <div className="settings-maintenance">
                  <div>
                    <h4>Автоподбор территории площадок</h4>
                    <p className="muted">
                      Подбирает регион и муниципалитет для площадок без такой привязки по названию и описанию паблика.
                    </p>
                  </div>
                  <div className="settings-action-row">
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={handleInferPublicLocations}
                      disabled={publicLocationLoading}
                    >
                      {publicLocationLoading
                        ? "Подбираем..."
                        : "Автоматически подобрать регион и муниципалитет для пабликов"}
                    </button>
                  </div>
                  {publicLocationMessage && (
                    <p className={`message ${publicLocationMessageType}`}>
                      {publicLocationMessage}
                    </p>
                  )}
                </div>
              ) : null}

              <div className="settings-maintenance settings-temporary-tool">
                <div>
                  <h4>Временная кнопка классификации</h4>
                  <p className="muted">
                    Ставит в очередь все комментарии без полноценной классификации:
                    пропущенные, ошибочные, старые записи без анализа и записи,
                    требующие проверки.
                  </p>
                </div>
                <div className="settings-action-row">
                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={handleStartUnclassified}
                    disabled={classificationLoading}
                  >
                    {classificationLoading
                      ? "Запускаем..."
                      : "Запустить классификацию всего неклассифицированного"}
                  </button>
                </div>
                {classificationMessage && (
                  <p className={`message ${classificationMessageType}`}>
                    {classificationMessage}
                  </p>
                )}
              </div>

              <div className="settings-maintenance">
                <div>
                  <h4>Кэш карты болей</h4>
                  <p className="muted">
                    Сбрасывает файловый геокэш координат. После очистки карта заново обратится к
                    геокодеру и пересоберёт регион, муниципалитет и населённый пункт для адресов.
                  </p>
                  {!isAdmin && !meQuery.isLoading && (
                    <p className="hint-text">Очистка геокэша доступна только администратору.</p>
                  )}
                </div>
                <div className="settings-action-row">
                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={handleRotateGeoCache}
                    disabled={!isAdmin || geoCacheLoading}
                  >
                    {geoCacheLoading ? "Очищаем..." : "Очистить кэш карты"}
                  </button>
                </div>
                {geoCacheMessage && (
                  <p className={`message ${geoCacheMessageType}`}>{geoCacheMessage}</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
