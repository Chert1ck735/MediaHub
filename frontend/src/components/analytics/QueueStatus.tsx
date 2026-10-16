import type { ClassificationQueue } from "../../api";

type Props = {
  queue: ClassificationQueue;
  onToggle: () => void;
  /** Свёрнутый сайдбар: остаётся только цветная точка с подсказкой. */
  collapsed?: boolean;
};

function formatEta(minutes: number): string {
  const roundedMinutes = Math.max(0, Math.ceil(minutes));
  if (roundedMinutes === 0) return "0 мин";
  if (roundedMinutes < 60) return `${roundedMinutes} мин`;

  const days = Math.floor(roundedMinutes / (24 * 60));
  const hours = Math.floor((roundedMinutes % (24 * 60)) / 60);
  const restMinutes = roundedMinutes % 60;

  if (days > 0) return `${days} д ${hours} ч`;
  return restMinutes > 0 ? `${hours} ч ${restMinutes} мин` : `${hours} ч`;
}

function formatRate(perMinute: number): string {
  if (perMinute >= 1) return Math.round(perMinute).toLocaleString("ru-RU");
  return perMinute.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

function getRemaining(queue: ClassificationQueue): number {
  return queue.remaining ?? queue.pending + queue.processing + (queue.failed_retrying ?? 0);
}

function getEtaText(queue: ClassificationQueue, remaining: number): string {
  if (remaining <= 0) return "Примерное время: 0 мин · анализ завершён";

  const eta = queue.eta_minutes != null && Number.isFinite(queue.eta_minutes)
    ? `≈${formatEta(queue.eta_minutes)}`
    : "рассчитывается";

  if (queue.paused) return `Примерное время: ${eta} · продолжится после возобновления`;
  if (queue.llm_ok === false) return `Примерное время: ${eta} · после восстановления сервиса`;
  return `Примерное время: ${eta}`;
}

export function QueueStatus({ queue, onToggle, collapsed = false }: Props) {
  const down = queue.llm_ok === false;
  const remaining = getRemaining(queue);
  const running = !queue.paused && !down && queue.in_progress > 0;
  const waitingForRetry = !queue.paused && !down && queue.in_progress <= 0 && remaining > 0;

  let tone = "idle";
  let main = "Анализ завершен";
  if (queue.paused) { tone = "warn"; main = "Классификация на паузе"; }
  else if (down) { tone = "danger"; main = "Анализ новых обращений недоступен"; }
  else if (running) { tone = "ok"; main = "Новые обращения анализируются"; }
  else if (waitingForRetry) { tone = "warn"; main = "Ожидание повторного анализа"; }

  const parts: string[] = [];
  if (queue.pending > 0) parts.push(`${queue.pending.toLocaleString("ru-RU")} в очереди`);
  if (queue.processing > 0) parts.push(`${queue.processing.toLocaleString("ru-RU")} в работе`);
  if ((queue.failed_retrying ?? 0) > 0) parts.push(`${queue.failed_retrying!.toLocaleString("ru-RU")} ждёт повтора`);
  if ((queue.failed_final ?? 0) > 0) parts.push(`${queue.failed_final!.toLocaleString("ru-RU")} не удалось`);
  if ((queue.needs_review ?? 0) > 0) parts.push(`${queue.needs_review!.toLocaleString("ru-RU")} на проверке`);
  if (remaining > 0 && queue.rate_per_minute != null && queue.rate_per_minute > 0) {
    const measured = queue.rate_source === "recent" || queue.rate_source === "historical";
    const prefix = measured ? "~" : "стартовая оценка ~";
    parts.push(`${prefix}${formatRate(queue.rate_per_minute)}/мин`);
  }

  const etaText = getEtaText(queue, remaining);
  const summary = [main, ...parts, etaText].join(" · ");

  if (collapsed) {
    return (
      <button
        type="button"
        className="an-queue an-queue--collapsed"
        onClick={onToggle}
        title={`${summary}. ${queue.paused ? "Возобновить" : "Пауза"}`}
        aria-label={summary}
      >
        <span className={`an-queue-dot an-queue-dot--${tone}`} />
      </button>
    );
  }

  return (
    <div className="an-queue" title={summary}>
      <span className={`an-queue-dot an-queue-dot--${tone}`} />
      <div className="an-queue-text">
        <span className="an-queue-main">{main}</span>
        {parts.length > 0 && <span className="an-queue-sub">{parts.join(" · ")}</span>}
        <span className="an-queue-sub an-queue-eta">{etaText}</span>
      </div>
      <button type="button" className="an-queue-btn" onClick={onToggle}>
        {queue.paused ? "Возобновить" : "Пауза"}
      </button>
    </div>
  );
}
