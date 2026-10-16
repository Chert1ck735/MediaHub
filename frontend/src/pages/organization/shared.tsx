/** Общие куски раздела настроек организации.
 *
 *  Здесь живут состояния, о которых легко забыть: загрузка, ошибка, пусто и
 *  «нет доступа». UI, который рисует только счастливый путь, выглядит сломанным
 *  при первой же сетевой икоте.
 */
import type { ReactNode } from "react";

// ── состояния ──────────────────────────────────────────────────────────────

export function Forbidden({ hint }: { hint?: string }) {
  return (
    <div className="org-state org-state--forbidden">
      <h3 className="org-state-title">Нет доступа</h3>
      <p className="muted">
        {hint ?? "Раздел доступен только администратору организации."}
      </p>
    </div>
  );
}

export function LoadingBlock({ label = "Загрузка…" }: { label?: string }) {
  return <div className="org-state muted">{label}</div>;
}

export function EmptyBlock({ label }: { label: string }) {
  return <div className="org-state muted">{label}</div>;
}

/** Ошибку показываем человеческим текстом. Технические детали — в консоль, а
 *  не в лицо пользователю (и не чужие данные из ответа сервера). */
export function ErrorBlock({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const isForbidden = isForbiddenError(error);
  if (isForbidden) return <Forbidden />;

  return (
    <div className="org-state org-state--error">
      <p>Не удалось загрузить данные.</p>
      {onRetry ? (
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
          Повторить
        </button>
      ) : null}
    </div>
  );
}

/** 403 отличаем от прочих ошибок: по ТЗ на него нужен отдельный экран. */
export function isForbiddenError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const status = (error as { status?: number; statusCode?: number }).status
    ?? (error as { statusCode?: number }).statusCode;
  if (status === 403) return true;
  const message = (error as { message?: string }).message ?? "";
  return message.includes("403");
}

/** Читаемое сообщение об ошибке мутации (409 «последний админ» и т.п.). */
export function mutationMessage(error: unknown): string {
  if (!error || typeof error !== "object") return "Не удалось выполнить действие";
  const detail = (error as { detail?: string }).detail;
  const message = (error as { message?: string }).message;
  return detail || message || "Не удалось выполнить действие";
}

// ── подтверждение опасного действия ────────────────────────────────────────

export function ConfirmDialog({
  title,
  description,
  confirmLabel = "Удалить",
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="org-modal-backdrop" role="dialog" aria-modal="true">
      <div className="org-modal">
        <h3 className="org-modal-title">{title}</h3>
        <div className="org-modal-body">{description}</div>
        <div className="org-modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Отмена
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Выполняем…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
