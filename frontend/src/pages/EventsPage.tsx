import type { ChangeEvent, Dispatch, RefObject, SetStateAction } from "react";
import { motion } from "framer-motion";

import type { ApiInfoEvent, PainListItem } from "../api";
import { WEEK_DAYS } from "../app/constants";
import { cropText } from "../app/utils";
import { INFO_EVENT_SORT } from "../constants";
import type { InfoEventSort } from "../constants";

export type EventsPageProps = {
  authToken: string;
  eventPainPickerOpen: boolean;
  eventPains: any[];
  filteredInfoEvents: ApiInfoEvent[];
  handleInfoEventDelete: (eventId: string) => void;
  handleInfoEventImport: (ev: ChangeEvent<HTMLInputElement>) => void;
  handleLinkPainToEvent: (painId: string) => void;
  handleUnlinkPainFromEvent: (painId: string) => void;
  infoEventMessage: string;
  infoEventMessageType: string;
  infoEventQuery: string;
  infoEventSort: InfoEventSort;
  infoEvents: ApiInfoEvent[];
  infoEventsImporting: boolean;
  infoEventsLoading: boolean;
  infoEventStats: Array<{ label: string; count: number }>;
  infoImportInputRef: RefObject<HTMLInputElement | null>;
  openAuth: (mode: "login") => void;
  openCreateInfoEventModal: () => void;
  openEditInfoEventModal: (eventItem: ApiInfoEvent) => void;
  openSmartEvent: (eventItem: ApiInfoEvent, options?: { entryMode?: "content" | "calendar" }) => void;
  painItems: PainListItem[];
  selectedInfoEvent: ApiInfoEvent | null;
  setEventPainPickerOpen: Dispatch<SetStateAction<boolean>>;
  setInfoEventQuery: Dispatch<SetStateAction<string>>;
  setInfoEventSort: Dispatch<SetStateAction<InfoEventSort>>;
  setSelectedInfoEventId: Dispatch<SetStateAction<string | null>>;
};

export function EventsPage({
  authToken,
  eventPainPickerOpen,
  eventPains,
  filteredInfoEvents,
  handleInfoEventDelete,
  handleInfoEventImport,
  handleLinkPainToEvent,
  handleUnlinkPainFromEvent,
  infoEventMessage,
  infoEventMessageType,
  infoEventQuery,
  infoEventSort,
  infoEvents,
  infoEventsImporting,
  infoEventsLoading,
  infoEventStats,
  infoImportInputRef,
  openAuth,
  openCreateInfoEventModal,
  openEditInfoEventModal,
  openSmartEvent,
  painItems,
  selectedInfoEvent,
  setEventPainPickerOpen,
  setInfoEventQuery,
  setInfoEventSort,
  setSelectedInfoEventId,
}: EventsPageProps) {
  void WEEK_DAYS;
  return (
    <motion.section
      key="infopovody"
      className="content-page workflow-page"
      initial={{ opacity: 0, y: 18, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -14, filter: "blur(3px)" }}
      transition={{ duration: 0.45 }}
    >
      <div className="content-page-head">
        <div>
          <h2 className="content-page-title">События</h2>
          <p className="muted content-page-lead">Основа для контента.</p>
        </div>
        <div className="workflow-head-actions">
          <input
            ref={infoImportInputRef}
            type="file"
            accept=".csv,.xlsx"
            className="visually-hidden"
            onChange={handleInfoEventImport}
          />
          <button className="btn btn-secondary" type="button" onClick={openCreateInfoEventModal}>
            Добавить событие вручную
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => (authToken ? infoImportInputRef.current?.click() : openAuth("login"))}
            disabled={infoEventsImporting}
          >
            {infoEventsImporting ? "Импорт..." : "Загрузить файл"}
          </button>
        </div>
      </div>

      <div className="workflow-kpi-grid">
        {infoEventStats.map((item) => (
          <article key={item.label} className="workflow-kpi-card">
            <span>{item.label}</span>
            <strong>{item.count}</strong>
          </article>
        ))}
      </div>

      <div className="workflow-toolbar">
        <div className="workflow-search">
          <input
            className="workflow-search-input"
            value={infoEventQuery}
            onChange={(event) => setInfoEventQuery(event.target.value)}
            placeholder="Поиск по названию, месту или описанию"
          />
        </div>
        <select
          className="workflow-sort-select"
          value={infoEventSort}
          onChange={(event) => setInfoEventSort(event.target.value as InfoEventSort)}
        >
          <option value={INFO_EVENT_SORT.EVENT_DATE_DESC}>Сначала новые даты</option>
          <option value={INFO_EVENT_SORT.EVENT_DATE_ASC}>Сначала ранние даты</option>
        </select>
      </div>

      {!authToken ? (
        <p className="empty content-empty">Войдите в систему, чтобы работать с событиями в реальной базе.</p>
      ) : infoEventsLoading && !infoEvents.length ? (
        <p className="empty content-empty">Загрузка событий...</p>
      ) : filteredInfoEvents.length === 0 ? (
        <p className="empty content-empty">События пока не найдены. Добавьте первое вручную или импортируйте файл.</p>
      ) : (
        <div className="workflow-list">
          {filteredInfoEvents.map((item) => (
            <article
              key={item.id}
              className={`workflow-list-card ${selectedInfoEvent?.id === item.id ? "active" : ""}`}
              onClick={() => setSelectedInfoEventId(item.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelectedInfoEventId(item.id);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="workflow-list-card-head">
                <h3>{item.title}</h3>
                <span>{new Date(item.event_date).toLocaleDateString("ru-RU")}</span>
              </div>
              <p className="workflow-list-card-meta">{item.location || "без региона"}</p>
              {item.description && <p className="workflow-snippet">{cropText(item.description, 140)}</p>}
              {selectedInfoEvent?.id === item.id && (
                <div className="event-pain-attribution" onClick={(e) => e.stopPropagation()}>
                  <div className="analytics-events-head">
                    <h4>Связанные боли</h4>
                    <button
                      type="button"
                      className="btn btn-outline btn-compact"
                      onClick={() => setEventPainPickerOpen((v) => !v)}
                    >
                      {eventPainPickerOpen ? "Скрыть" : "+ Привязать боль"}
                    </button>
                  </div>
                  {eventPains.length === 0 ? (
                    <p className="muted" style={{ margin: "4px 0 0" }}>
                      Нет привязок. Свяжите боли, на которые это событие отвечает.
                    </p>
                  ) : (
                    <ul className="analytics-events-list">
                      {eventPains.map((ep) => (
                        <li key={ep.pain_id} className="analytics-event-row">
                          <div className="analytics-event-main">
                            <div className="analytics-event-title">{ep.pain_title}</div>
                            {ep.pain_category && (
                              <div className="analytics-event-meta muted">{ep.pain_category}</div>
                            )}
                          </div>
                          <button
                            type="button"
                            className="analytics-event-remove"
                            onClick={() => handleUnlinkPainFromEvent(ep.pain_id)}
                            title="Отвязать"
                          >×</button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {eventPainPickerOpen && (
                    <div className="analytics-event-picker">
                      <div className="analytics-event-picker-list">
                        {(() => {
                          const linkedIds = new Set(eventPains.map((p) => p.pain_id));
                          const candidates = painItems.filter((p) => !linkedIds.has(p.id));
                          if (candidates.length === 0) {
                            return <p className="muted">Все боли уже привязаны.</p>;
                          }
                          return candidates.map((p) => (
                            <button
                              key={p.id}
                              type="button"
                              className="analytics-event-picker-item"
                              onClick={() => handleLinkPainToEvent(p.id)}
                            >
                              <div>{p.title}</div>
                              <div className="muted">
                                {p.category}
                                {" · "}
                                {p.mentions_count} упоминаний
                              </div>
                            </button>
                          ));
                        })()}
                      </div>
                    </div>
                  )}
                </div>
              )}
              {selectedInfoEvent?.id === item.id && (
                <div className="workflow-list-card-actions">
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      openSmartEvent(item, { entryMode: "calendar" });
                    }}
                  >
                    Создать пост
                  </button>
                  <button
                    className="btn btn-secondary"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      openEditInfoEventModal(item);
                    }}
                  >
                    Редактировать
                  </button>
                  <button
                    className="btn btn-outline"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      handleInfoEventDelete(item.id);
                    }}
                  >
                    Удалить
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      <p className={`message ${infoEventMessageType}`}>{infoEventMessage}</p>
    </motion.section>
  );
}
