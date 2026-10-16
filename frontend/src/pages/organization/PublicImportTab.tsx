/** Вкладка «Импорт площадок» — wizard в два шага.
 *
 *  Шаг 1: загрузка .xlsx/.csv + ссылка на шаблон.
 *  Шаг 2: preview построчно («Будет создана» / «Пропущена» / «Ошибка»),
 *  счётчики, и кнопка подтверждения.
 *
 *  Файл содержит две колонки: название площадки (необязательно) и ссылку.
 *  Подтверждение запускает фоновую задачу — импорт идёт через штатный ingest,
 *  поэтому показываем прогресс.
 */
import { useMemo, useRef, useState } from "react";

import {
  downloadPublicErrorReport,
  publicImportTemplateUrl,
  type PublicImportRow,
  type PublicImportRowStatus,
} from "../../api/organization";
import {
  HISTORY_UNITS,
  historyDateFrom,
  type HistoryUnit,
} from "../../app/historyPeriod";
import { usePublicImport } from "../../hooks/useOrganization";
import { ErrorBlock, mutationMessage } from "./shared";

const STATUS_LABELS: Record<PublicImportRowStatus, string> = {
  create: "Будет создана",
  skip: "Пропущена",
  error: "Ошибка",
};

export function PublicImportTab({
  orgId,
  embedded = false,
}: {
  orgId: string;
  embedded?: boolean;
}) {
  const { preview, confirm, progress, cancel } = usePublicImport(orgId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [historyAmount, setHistoryAmount] = useState(2);
  const [historyUnit, setHistoryUnit] = useState<HistoryUnit>("weeks");

  const previewData = preview.data ?? null;
  const resultData = confirm.data ?? null;

  const validCount = useMemo(
    () => (previewData ? previewData.to_create : 0),
    [previewData],
  );

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    setActionError(null);
    confirm.reset();
    setFileName(file.name);
    try {
      await preview.mutateAsync(file);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  const applyImport = async () => {
    if (!previewData) return;
    setActionError(null);
    try {
      await confirm.mutateAsync({
        rows: previewData.rows,
        dateFrom: historyDateFrom(historyAmount, historyUnit).toISOString(),
      });
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  const saveErrorReport = async (rows: PublicImportRow[]) => {
    try {
      const blob = await downloadPublicErrorReport(orgId, rows);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "publics_import_errors.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  const reset = () => {
    preview.reset();
    confirm.reset();
    setFileName(null);
    setActionError(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  return (
    <section
      className={embedded ? "org-import org-import--embedded" : "org-tab org-import"}
    >
      <header className="org-tab-head">
        <div>
          <h3 className="org-import-title">Импорт площадок</h3>
          <p className="muted">
            Колонки: «название» (необязательно) и «ссылка». Ссылки — на vk.com
            или ok.ru.
          </p>
        </div>
        <a
          className="btn btn-ghost"
          href={publicImportTemplateUrl(orgId)}
          download
        >
          Скачать шаблон
        </a>
      </header>

      {actionError ? <p className="org-error-banner">{actionError}</p> : null}

      {/* ── шаг 1: загрузка ── */}
      <label
        className={`org-import-drop${dragOver ? " is-dragover" : ""}${
          preview.isPending ? " is-busy" : ""
        }`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!preview.isPending) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          if (!preview.isPending)
            void pickFile(event.dataTransfer.files?.[0]);
        }}
      >
        <input
          ref={fileInput}
          type="file"
          accept=".xlsx,.csv"
          className="org-import-file"
          onChange={(event) => void pickFile(event.target.files?.[0])}
          disabled={preview.isPending}
        />
        <svg
          className="org-import-drop-icon"
          width="30"
          height="30"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M12 16V4m0 0L7 9m5-5 5 5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <div className="org-import-drop-text">
          <strong>
            {preview.isPending
              ? "Проверяем файл…"
              : fileName ?? "Перетащите файл или нажмите, чтобы выбрать"}
          </strong>
          <span className="muted">
            {fileName && !preview.isPending
              ? "Нажмите, чтобы выбрать другой файл"
              : "Поддерживаются .xlsx и .csv"}
          </span>
        </div>
      </label>

      {preview.isError ? <ErrorBlock error={preview.error} /> : null}

      {/* ── шаг 2: preview ── */}
      {previewData ? (
        <>
          <div className="org-import-counters">
            <span className="org-badge org-badge--create">
              Будет создано: {previewData.to_create}
            </span>
            <span className="org-badge org-badge--skip">
              Пропущено: {previewData.skipped}
            </span>
            <span className="org-badge org-badge--error">
              Ошибок: {previewData.errors}
            </span>
          </div>

          <div className="org-table-wrap">
            <table className="org-table">
              <thead>
                <tr>
                  <th>Строка</th>
                  <th>Статус</th>
                  <th>Название</th>
                  <th>Ссылка</th>
                  <th>Замечания</th>
                </tr>
              </thead>
              <tbody>
                {previewData.rows.map((row) => (
                  <tr
                    key={row.row_number}
                    className={row.status === "error" ? "org-row-error" : ""}
                  >
                    <td>{row.row_number}</td>
                    <td>
                      <span
                        className={`org-badge org-badge--${row.status}`}
                      >
                        {STATUS_LABELS[row.status]}
                      </span>
                    </td>
                    <td>{row.name ?? "—"}</td>
                    <td className="org-cell-muted">{row.url ?? "—"}</td>
                    <td className="org-cell-muted">
                      {row.errors.length > 0 ? (
                        <span className="org-cell-error">
                          {row.errors.join("; ")}
                        </span>
                      ) : null}
                      {row.warnings.length > 0 ? row.warnings.join("; ") : null}
                      {row.errors.length === 0 &&
                      row.warnings.length === 0
                        ? "—"
                        : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <footer className="org-import-actions">
            <label className="vk-ingest-history">
              <span className="muted">Импортировать историю за</span>
              <input
                className="vk-ingest-count-input"
                type="number"
                value={historyAmount}
                min={1}
                disabled={confirm.isPending}
                onChange={(event) =>
                  setHistoryAmount(
                    Math.max(1, Math.trunc(Number(event.target.value) || 1)),
                  )
                }
              />
              <select
                value={historyUnit}
                disabled={confirm.isPending}
                onChange={(event) =>
                  setHistoryUnit(event.target.value as HistoryUnit)
                }
              >
                {HISTORY_UNITS.map((unit) => (
                  <option key={unit.value} value={unit.value}>
                    {unit.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={reset}
            >
              Загрузить другой файл
            </button>
            {previewData.errors > 0 ? (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => void saveErrorReport(previewData.rows)}
              >
                Скачать отчёт об ошибках
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void applyImport()}
              disabled={validCount === 0 || confirm.isPending}
            >
              {confirm.isPending
                ? "Импортируем…"
                : `Импортировать (${validCount})`}
            </button>
          </footer>

          {confirm.isPending && progress ? (
            <div className="org-import-progress">
              <div className="org-import-progress-head">
                <span>{progress.message}</span>
                <div className="org-import-progress-side">
                  <span className="muted">
                    {progress.total != null
                      ? `${progress.done}/${progress.total}`
                      : progress.done}
                  </span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-compact"
                    disabled={progress.cancelRequested}
                    onClick={cancel}
                  >
                    {progress.cancelRequested ? "Отмена…" : "Отменить"}
                  </button>
                </div>
              </div>
              <div className="org-import-progress-track">
                <div
                  className="org-import-progress-bar"
                  style={{
                    width: progress.total
                      ? `${Math.min(100, (progress.done / progress.total) * 100)}%`
                      : "30%",
                  }}
                />
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {/* ── результат ── */}
      {resultData ? (
        <div className="org-import-result">
          <h4>Импорт завершён</h4>
          <p>
            Создано: {resultData.created} · Пропущено: {resultData.skipped} ·{" "}
            Ошибок: {resultData.errors}
          </p>
          {resultData.error_rows.length > 0 ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => void saveErrorReport(resultData.error_rows)}
            >
              Скачать отчёт об ошибках
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
