/** Раздел «Автопарсинг» в настройках.
 *
 *  Показывает и (для суперадмина) меняет период автопарсера — как часто фоновый
 *  воркер обходит площадки и дотягивает новые комментарии. Значение глобальное
 *  (на весь сервис), хранится в БД; дефолт — раз в день.
 *
 *  Период вводится числом + единицей (часы/дни) ради читаемости, но на бэкенд
 *  уходит всегда в часах.
 */
import { useEffect, useState } from "react";

import {
  apiGetAutoparseConfig,
  apiRefreshVkSubscribers,
  apiUpdateAutoparseConfig,
  waitForJob,
  type AutoParseConfig,
  type JobInfo,
} from "../api";

type Unit = "hours" | "days";

/** Разбивает часы на «человеческую» пару (число + единица): кратные 24 — в днях. */
function splitInterval(hours: number): { amount: number; unit: Unit } {
  if (hours > 0 && hours % 24 === 0) return { amount: hours / 24, unit: "days" };
  return { amount: hours, unit: "hours" };
}

function toHours(amount: number, unit: Unit): number {
  return unit === "days" ? amount * 24 : amount;
}

export function AutoparseSettingsSection({
  token,
  canEdit,
}: {
  token: string;
  canEdit: boolean;
}) {
  const [config, setConfig] = useState<AutoParseConfig | null>(null);
  const [amount, setAmount] = useState(1);
  const [unit, setUnit] = useState<Unit>("days");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [subscribersJob, setSubscribersJob] = useState<JobInfo | null>(null);
  const [subscribersLoading, setSubscribersLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await apiGetAutoparseConfig(token);
        if (cancelled) return;
        setConfig(cfg);
        const split = splitInterval(cfg.interval_hours);
        setAmount(split.amount);
        setUnit(split.unit);
      } catch (error) {
        if (!cancelled) {
          setMessage({
            type: "error",
            text: error instanceof Error ? error.message : "Не удалось загрузить настройки",
          });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const nextHours = toHours(amount, unit);
  const dirty = config != null && nextHours !== config.interval_hours;

  const save = async () => {
    if (!dirty) return;
    setSaving(true);
    setMessage(null);
    try {
      const updated = await apiUpdateAutoparseConfig(token, nextHours);
      setConfig(updated);
      const split = splitInterval(updated.interval_hours);
      setAmount(split.amount);
      setUnit(split.unit);
      setMessage({ type: "success", text: "Период автопарсинга сохранён." });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Не удалось сохранить",
      });
    } finally {
      setSaving(false);
    }
  };

  const refreshSubscribers = async () => {
    if (!canEdit || subscribersLoading) return;
    setSubscribersLoading(true);
    setSubscribersJob(null);
    setMessage(null);
    try {
      const { job_id } = await apiRefreshVkSubscribers(token);
      const finalJob = await waitForJob(token, job_id, (job) => setSubscribersJob(job));
      if (finalJob.status === "failed") {
        throw new Error(finalJob.error || "Не удалось обновить подписчиков VK.");
      }
      if (finalJob.status === "cancelled") {
        setMessage({ type: "error", text: "Обновление подписчиков VK отменено." });
        return;
      }
      const result = finalJob.result || {};
      const updated = Number(result.links_updated ?? 0);
      const failed = Number(result.links_failed ?? 0);
      setMessage({
        type: failed > 0 ? "error" : "success",
        text: `Подписчики VK обновлены: ${updated.toLocaleString("ru-RU")}; ошибок: ${failed.toLocaleString("ru-RU")}.`,
      });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Не удалось обновить подписчиков VK.",
      });
    } finally {
      setSubscribersLoading(false);
      setSubscribersJob(null);
    }
  };

  const subscribersJobRunning =
    subscribersJob?.status === "running" || subscribersJob?.status === "pending";
  const subscribersJobPercent =
    subscribersJob?.total && subscribersJob.total > 0
      ? Math.min(100, (subscribersJob.done / subscribersJob.total) * 100)
      : null;

  return (
    <div className="card-glass">
      <h3>Автопарсинг</h3>
      <p className="hint-text">
        Как часто фоновый парсер обходит площадки и дотягивает новые комментарии.
        Настройка общая для всего сервиса; по умолчанию — раз в день.
      </p>

      {loading ? (
        <p className="hint-text">Загружаем настройки…</p>
      ) : (
        <>
          <div className="settings-interval-row">
            <label className="settings-interval-field">
              <span className="muted">Проверять раз в</span>
              <input
                type="number"
                min={1}
                value={amount}
                disabled={!canEdit || saving}
                onChange={(e) => setAmount(Math.max(1, Math.trunc(Number(e.target.value) || 1)))}
              />
            </label>
            <select
              value={unit}
              disabled={!canEdit || saving}
              onChange={(e) => setUnit(e.target.value as Unit)}
            >
              <option value="hours">часов</option>
              <option value="days">дней</option>
            </select>
            {canEdit ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void save()}
                disabled={!dirty || saving}
              >
                {saving ? "Сохраняем…" : "Сохранить"}
              </button>
            ) : null}
          </div>

          {config ? (
            <p className="muted settings-interval-note">
              Окно догрузки — {config.lookback_days} дн.: за каждый проход парсер
              проверяет посты за последние {config.lookback_days} дней.
              {!config.enabled ? " Внимание: фоновый воркер сейчас выключен." : ""}
            </p>
          ) : null}

          {!canEdit ? (
            <p className="hint-text">
              Менять период может только суперадминистратор.
            </p>
          ) : null}

          {canEdit ? (
            <div className="settings-maintenance">
              <div>
                <h4>Количество подписчиков VK</h4>
                <p className="muted">
                  Обновляет сегодняшнюю метрику подписчиков у всех активных импортированных VK-площадок.
                </p>
              </div>
              <div className="settings-action-row">
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => void refreshSubscribers()}
                  disabled={subscribersLoading}
                >
                  {subscribersLoading ? "Обновляем..." : "Обновить количество подписчиков"}
                </button>
              </div>
              {subscribersJobRunning ? (
                <div className="settings-job-progress">
                  <div className="settings-job-progress-head">
                    <span>{subscribersJob?.message || "Обновление подписчиков VK..."}</span>
                    <span className="muted">
                      {subscribersJob?.total != null
                        ? `${subscribersJob.done.toLocaleString("ru-RU")} / ${subscribersJob.total.toLocaleString("ru-RU")}`
                        : ""}
                    </span>
                  </div>
                  <div className="settings-job-progress-bar" aria-hidden="true">
                    <div
                      className="settings-job-progress-fill"
                      style={{ width: subscribersJobPercent != null ? `${subscribersJobPercent}%` : "30%" }}
                    />
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {message ? <p className={`message ${message.type}`}>{message.text}</p> : null}
        </>
      )}
    </div>
  );
}
