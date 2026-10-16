import type { Dispatch, FormEvent, SetStateAction } from "react";

import type { ApiModule } from "../api";
import { AUTOCOMPLETE_BLUR_DELAY_MS } from "../constants";

export type OrganizationsPageProps = {
  moduleDescription: string;
  moduleGoal: string;
  moduleLoading: boolean;
  moduleName: string;
  moduleNameFocused: boolean;
  moduleNameMatchesPublic: boolean;
  moduleNameSuggestions: string[];
  modulePublicNames: string[];
  modulesList: ApiModule[];
  normalizedModuleName: string;
  reportSourcesLoading: boolean;
  setModuleDescription: Dispatch<SetStateAction<string>>;
  setModuleGoal: Dispatch<SetStateAction<string>>;
  setModuleLoading: Dispatch<SetStateAction<boolean>>;
  setModuleName: Dispatch<SetStateAction<string>>;
  setModuleNameFocused: Dispatch<SetStateAction<boolean>>;
  setTimeoutSafe: (cb: () => void, ms: number) => number;
  handleModuleSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function OrganizationsPage({
  moduleDescription,
  moduleGoal,
  moduleLoading,
  moduleName,
  moduleNameFocused,
  moduleNameMatchesPublic,
  moduleNameSuggestions,
  modulePublicNames,
  modulesList,
  normalizedModuleName,
  reportSourcesLoading,
  setModuleDescription,
  setModuleGoal,
  setModuleName,
  setModuleNameFocused,
  setTimeoutSafe,
  handleModuleSubmit,
}: OrganizationsPageProps) {
  return (
    <div className="tab-content organizations-tab">
      <div className="section-header">
        <h2>Организации</h2>
      </div>

      <div className="card-glass">
        <h3>Создать новый модуль</h3>
        <p className="hint-text">Выберите существующий паблик.</p>

        <form onSubmit={handleModuleSubmit}>
          <div className="form-group">
            <label>Название модуля</label>
            <div className="autocomplete-field">
              <input
                type="text"
                className="input-field"
                value={moduleName}
                onChange={(e) => setModuleName(e.target.value)}
                onFocus={() => setModuleNameFocused(true)}
                onBlur={() => setTimeoutSafe(() => setModuleNameFocused(false), AUTOCOMPLETE_BLUR_DELAY_MS)}
                placeholder={reportSourcesLoading ? "Загружаем паблики..." : "Начните вводить название паблика"}
                autoComplete="off"
                required
                disabled={reportSourcesLoading || modulePublicNames.length === 0}
              />
              {moduleNameFocused && !reportSourcesLoading && moduleNameSuggestions.length > 0 && (
                <div className="autocomplete-menu">
                  {moduleNameSuggestions.map((name) => (
                    <button
                      key={name}
                      type="button"
                      className={`autocomplete-option ${name === normalizedModuleName ? "active" : ""}`}
                      onMouseDown={(event) => {
                        event.preventDefault();
                        setModuleName(name);
                        setModuleNameFocused(false);
                      }}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <p className="muted" style={{ marginTop: 8 }}>
              {reportSourcesLoading
                ? "Список пабликов загружается."
                : modulePublicNames.length === 0
                  ? "Паблики пока не найдены. Сначала добавьте или загрузите площадки."
                  : normalizedModuleName.length === 0
                    ? `Доступно пабликов для выбора: ${modulePublicNames.length}.`
                    : moduleNameSuggestions.length === 0
                      ? "Совпадений не найдено. Выберите существующий паблик."
                      : !moduleNameMatchesPublic
                        ? "Выберите один из предложенных вариантов."
                        : "Модуль будет создан для выбранного паблика."}
            </p>
          </div>

          <div className="form-group">
            <label>Цель (необязательно)</label>
            <input
              type="text"
              className="input-field"
              value={moduleGoal}
              onChange={(e) => setModuleGoal(e.target.value)}
              placeholder="Какую задачу решает?"
            />
          </div>

          <div className="form-group">
            <label>Описание (необязательно)</label>
            <textarea
              className="input-field"
              value={moduleDescription}
              onChange={(e) => setModuleDescription(e.target.value)}
              placeholder="Подробности работы модуля..."
              rows={3}
            />
          </div>

          <button
            className="btn btn-primary"
            type="submit"
            disabled={moduleLoading || !normalizedModuleName || !moduleNameMatchesPublic}
          >
            {moduleLoading ? "Создание..." : "Создать модуль"}
          </button>
        </form>
      </div>

      <div className="card-glass" style={{ marginTop: "1rem" }}>
        <h3>Модули из базы</h3>
        {modulesList.length === 0 ? (
          <p className="hint-text">Пока нет сохранённых модулей.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {modulesList.map((module) => (
              <article key={module.id} className="calendar-event-card">
                <h4 style={{ margin: 0 }}>{module.name}</h4>
                <p className="muted" style={{ margin: "0.35rem 0" }}>
                  <strong>Цель:</strong> {module.goal || "—"}
                </p>
                <p className="muted" style={{ margin: 0 }}>
                  <strong>Описание:</strong> {module.description || "—"}
                </p>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
