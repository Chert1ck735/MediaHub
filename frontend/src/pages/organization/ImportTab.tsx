/** Вкладка «Импорт пользователей» — wizard в два шага.
 *
 *  Шаг 1: загрузка .xlsx/.csv + ссылка на шаблон.
 *  Шаг 2: preview построчно («Будет создан» / «Будет обновлён» / «Пропущен» /
 *  «Ошибка»), счётчики, и кнопка подтверждения — активная ТОЛЬКО если есть хоть
 *  одна валидная строка. Подтверждать нечего, если валидных строк ноль.
 *
 *  Шаг состояния выводится из данных, а не хранится отдельным `step`: пока нет
 *  preview — мы на шаге 1, появился — на шаге 2. Отдельный счётчик шага
 *  неминуемо разъехался бы с реальностью.
 */
import { useMemo, useRef, useState } from "react";

import {
  downloadErrorReport,
  importTemplateUrl,
  type ImportRow,
  type ImportRowStatus,
} from "../../api/organization";
import { useImport } from "../../hooks/useOrganization";
import { ErrorBlock, mutationMessage } from "./shared";

const STATUS_LABELS: Record<ImportRowStatus, string> = {
  create: "Будет создан",
  update: "Будет обновлён",
  skip: "Пропущен",
  error: "Ошибка",
};

export function ImportTab({ orgId, embedded = false }: { orgId: string; embedded?: boolean }) {
  const { preview, confirm } = useImport(orgId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const previewData = preview.data ?? null;
  const resultData = confirm.data ?? null;

  const validCount = useMemo(
    () => (previewData ? previewData.to_create + previewData.to_update : 0),
    [previewData],
  );

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    setActionError(null);
    confirm.reset(); // новый файл — прошлый результат больше не актуален
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
      await confirm.mutateAsync(previewData.rows);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  const saveErrorReport = async (rows: ImportRow[]) => {
    try {
      const blob = await downloadErrorReport(orgId, rows);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "import_errors.csv";
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
    <section className={embedded ? "org-import org-import--embedded" : "org-tab org-import"}>
      <header className="org-tab-head">
        <div>
          <h3 className="org-import-title">Импорт пользователей</h3>
          <p className="muted">
            Колонки: <code>email</code>, <code>first_name</code>, <code>last_name</code>,{" "}
            <code>role</code>, <code>user_groups</code>. Группы разделяются знаком «;».
          </p>
        </div>
        <a className="btn btn-ghost" href={importTemplateUrl(orgId)} download>
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
          if (!preview.isPending) void pickFile(event.dataTransfer.files?.[0]);
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
            <span className="org-badge org-badge--update">
              Будет обновлено: {previewData.to_update}
            </span>
            <span className="org-badge org-badge--skip">
              Пропущено: {previewData.skipped}
            </span>
            <span className="org-badge org-badge--error">
              Ошибок: {previewData.errors}
            </span>
          </div>

          {previewData.new_groups.length > 0 ? (
            <p className="org-warning">
              Будут созданы группы: {previewData.new_groups.join(", ")}
            </p>
          ) : null}

          <div className="org-table-wrap">
            <table className="org-table">
              <thead>
                <tr>
                  <th>Строка</th>
                  <th>Статус</th>
                  <th>Email</th>
                  <th>ФИО</th>
                  <th>Роль</th>
                  <th>Группы</th>
                  <th>Замечания</th>
                </tr>
              </thead>
              <tbody>
                {previewData.rows.map((row) => (
                  <tr key={row.row_number} className={row.status === "error" ? "org-row-error" : ""}>
                    <td>{row.row_number}</td>
                    <td>
                      <span className={`org-badge org-badge--${row.status}`}>
                        {STATUS_LABELS[row.status]}
                      </span>
                    </td>
                    <td>{row.email ?? "—"}</td>
                    <td>{[row.first_name, row.last_name].filter(Boolean).join(" ") || "—"}</td>
                    <td>{row.role ?? "—"}</td>
                    <td className="org-cell-muted">{row.user_groups.join(", ") || "—"}</td>
                    <td className="org-cell-muted">
                      {row.errors.length > 0 ? (
                        <span className="org-cell-error">{row.errors.join("; ")}</span>
                      ) : null}
                      {row.warnings.length > 0 ? row.warnings.join("; ") : null}
                      {row.errors.length === 0 && row.warnings.length === 0 ? "—" : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <footer className="org-import-actions">
            <button type="button" className="btn btn-ghost" onClick={reset}>
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
              // Подтверждать нечего, если валидных строк нет.
              disabled={validCount === 0 || confirm.isPending}
            >
              {confirm.isPending
                ? "Импортируем…"
                : `Импортировать (${validCount})`}
            </button>
          </footer>
        </>
      ) : null}

      {/* ── результат ── */}
      {resultData ? (
        <div className="org-import-result">
          <h4>Импорт завершён</h4>
          <p>
            Создано: {resultData.created} · Обновлено: {resultData.updated} · Пропущено:{" "}
            {resultData.skipped} · Ошибок: {resultData.errors}
          </p>
          {resultData.created_groups.length > 0 ? (
            <p className="muted">Созданы группы: {resultData.created_groups.join(", ")}</p>
          ) : null}
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
