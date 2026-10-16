import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { buildCalendarLegend, calendarEventClass, calendarEventPublicationUrl, type CalendarPublicOption } from "../app/calendarVisuals";
import { WEEK_DAYS, statusLabel } from "../app/constants";
import { CALENDAR_VIEW } from "../constants";
import type { CalendarEvent, CalendarView } from "../app/types";
import { parseInputDate, toInputDate } from "../app/utils";

export type CalendarPageProps = {
  authToken: string;
  calendarDate: Date;
  calendarView: CalendarView;
  dataLoading: boolean;
  dataFetching?: boolean;
  dayLoading?: boolean;
  error?: string;
  dayError?: string;
  retry: () => void;
  hasMore?: boolean;
  loadingMore?: boolean;
  loadMore: () => void;
  eventsByDate: Map<string, CalendarEvent[]>;
  monthCells: Date[];
  openAuth: (mode: "login") => void;
  openEditEvent: (event: CalendarEvent) => void;
  openSchedulePost: (date?: string, time?: string) => void;
  periodLabel: string;
  removeEvent: (id: string) => void;
  selectedDay: string;
  selectedEvents: CalendarEvent[];
  selectedPublicIds: string[];
  setSelectedPublicIds: Dispatch<SetStateAction<string[]>>;
  publicationTargetOptions: CalendarPublicOption[];
  setCalendarDate: Dispatch<SetStateAction<Date>>;
  setCalendarView: Dispatch<SetStateAction<CalendarView>>;
  setSelectedDay: Dispatch<SetStateAction<string>>;
  shiftPeriod: (dir: 1 | -1) => void;
  weekDays: Date[];
};

export function CalendarPage({ authToken, calendarDate, calendarView, dataLoading, dataFetching,
  dayLoading, error, dayError, retry, hasMore, loadingMore, loadMore, eventsByDate, monthCells,
  openAuth, openEditEvent, openSchedulePost, periodLabel, removeEvent, selectedDay, selectedEvents,
  selectedPublicIds, setSelectedPublicIds, publicationTargetOptions, setCalendarDate,
  setCalendarView, setSelectedDay, shiftPeriod, weekDays,
}: CalendarPageProps) {
  const [publicSearch, setPublicSearch] = useState("");
  const [agendaLimit, setAgendaLimit] = useState(10);
  const [deleteTarget, setDeleteTarget] = useState<CalendarEvent | null>(null);
  const publicKey = selectedPublicIds.join(",");
  useEffect(() => { setAgendaLimit(10); setDeleteTarget(null); }, [selectedDay, publicKey]);
  const legend = useMemo(() => buildCalendarLegend(publicationTargetOptions), [publicationTargetOptions]);
  const matchingLegend = legend.filter(item => item.label.toLocaleLowerCase("ru-RU").includes(publicSearch.trim().toLocaleLowerCase("ru-RU")));
  const days = calendarView === CALENDAR_VIEW.MONTH ? monthCells : weekDays;
  const today = toInputDate(new Date());
  const periodDays = calendarView === CALENDAR_VIEW.MONTH
    ? days.filter(day => day.getMonth() === calendarDate.getMonth()) : days;
  const totalForDay = (key: string) => {
    const items = eventsByDate.get(key) ?? [];
    return Math.max(items[0]?.dayTotal ?? 0, items.length);
  };
  const total = periodDays.reduce((sum, day) => sum + totalForDay(toInputDate(day)), 0);
  const activeDays = periodDays.filter(day => totalForDay(toInputDate(day)) > 0).length;
  const dayTotal = selectedEvents[0]?.dayTotal ?? totalForDay(selectedDay);
  const agendaEvents = selectedEvents.slice(0, agendaLimit);
  const chooseDay = (day: Date) => {
    setSelectedDay(toInputDate(day));
    if (day.getMonth() !== calendarDate.getMonth() || day.getFullYear() !== calendarDate.getFullYear()) setCalendarDate(day);
  };
  const openPublication = (event: CalendarEvent) => {
    const url = calendarEventPublicationUrl(event, selectedPublicIds);
    if (url) window.open(url, "_blank", "noopener,noreferrer");
    else openEditEvent(event);
  };

  if (!authToken) return (
    <section className="calendar-guest workspace-empty">
      <span className="workspace-empty-symbol" aria-hidden="true">▦</span>
      <h1>Календарь публикаций</h1>
      <p>Вся история сообществ и будущие публикации в одном месте.</p>
      <button className="btn btn-primary" onClick={() => openAuth("login")}>Войти в систему</button>
    </section>
  );

  return (
    <section className="calendar calendar-workspace">
      <div className="content-page-head calendar-page-head">
        <div>
          <h1 className="content-page-title">Календарь публикаций</h1>
        </div>
        <button className="btn btn-primary" onClick={() => openSchedulePost(selectedDay)}><span aria-hidden="true">＋</span> Запланировать пост</button>
      </div>

      <div className="calendar-summary" aria-label="Статистика периода" aria-busy={dataLoading}>
        <div><span>Публикации за {calendarView === CALENDAR_VIEW.MONTH ? "месяц" : "неделю"}</span><strong>{dataLoading || error ? "—" : total.toLocaleString("ru-RU")}</strong><small>во всех выбранных пабликах</small></div>
        <div><span>Дни с публикациями</span><strong>{dataLoading || error ? "—" : activeDays}<small> / {periodDays.length}</small></strong><small>активность в выбранном периоде</small></div>
        <div><span>Выбрано сообществ</span><strong>{selectedPublicIds.length || legend.length || "Все"}</strong><small>{selectedPublicIds.length ? "можно изменить в фильтре ниже" : "показываем всю историю"}</small></div>
      </div>

      {error && <div className="workspace-error" role="alert"><span>{error}</span><button className="btn btn-outline" onClick={retry}>Повторить</button></div>}
      <div className="calendar-toolbar">
        <div className="calendar-period-nav">
          <button className="calendar-icon-button" aria-label="Предыдущий период" onClick={() => shiftPeriod(-1)}>‹</button>
          <h2 className="calendar-title">{periodLabel}</h2>
          <button className="calendar-icon-button" aria-label="Следующий период" onClick={() => shiftPeriod(1)}>›</button>
          <button className="btn btn-outline" onClick={() => { const now = new Date(); setCalendarDate(now); setSelectedDay(today); }}>Сегодня</button>
        </div>
        <div className="calendar-toolbar-actions">
          <label className="calendar-jump"><span className="visually-hidden">Перейти к месяцу</span>
            <input type="month" aria-label="Перейти к месяцу" value={toInputDate(calendarDate).slice(0, 7)} onChange={event => {
              if (!event.target.value) return;
              const day = parseInputDate(`${event.target.value}-01`); setCalendarDate(day); setSelectedDay(toInputDate(day));
            }} />
          </label>
          <div className="view-switch" aria-label="Вид календаря">
            <button className={`tiny-btn ${calendarView === CALENDAR_VIEW.MONTH ? "active" : ""}`} aria-pressed={calendarView === CALENDAR_VIEW.MONTH} onClick={() => setCalendarView(CALENDAR_VIEW.MONTH)}>Месяц</button>
            <button className={`tiny-btn ${calendarView === CALENDAR_VIEW.WEEK ? "active" : ""}`} aria-pressed={calendarView === CALENDAR_VIEW.WEEK} onClick={() => setCalendarView(CALENDAR_VIEW.WEEK)}>Неделя</button>
          </div>
        </div>
      </div>

      <div className="calendar-source-bar">
        <details className="calendar-source-picker">
          <summary>Сообщества <span>{selectedPublicIds.length ? selectedPublicIds.length : "Все"}</span><span aria-hidden="true">⌄</span></summary>
          <div className="calendar-source-menu">
            <input type="search" aria-label="Поиск сообщества" placeholder="Найти сообщество…" value={publicSearch} onChange={e => setPublicSearch(e.target.value)} />
            <button className={`calendar-legend-item ${!selectedPublicIds.length ? "active" : ""}`} aria-pressed={!selectedPublicIds.length} onClick={() => setSelectedPublicIds([])}>Все сообщества</button>
            <div className="calendar-source-options">
              {matchingLegend.map(item => <label key={item.id} className="calendar-source-option">
                <input type="checkbox" checked={selectedPublicIds.includes(item.id)} onChange={() => setSelectedPublicIds(prev => prev.includes(item.id) ? prev.filter(id => id !== item.id) : [...prev, item.id])} />
                <span>{item.label}</span>
              </label>)}
              {!matchingLegend.length && <p className="empty">Сообщества не найдены</p>}
            </div>
          </div>
        </details>
        <div className="calendar-source-chips">
          {(selectedPublicIds.length ? legend.filter(item => selectedPublicIds.includes(item.id)) : legend.slice(0, 3)).map(item => (
            <span className="calendar-source-chip" key={item.id}><i className={item.className} />{item.label}
              {selectedPublicIds.length > 0 && <button aria-label={`Убрать фильтр: ${item.label}`} onClick={() => setSelectedPublicIds(prev => prev.filter(id => id !== item.id))}>×</button>}
            </span>
          ))}
          {!selectedPublicIds.length && legend.length > 3 && <span className="muted">и ещё {legend.length - 3}</span>}
        </div>
        <span className="calendar-sync" role="status">{dataFetching ? "Обновляем…" : "Время местное"}</span>
      </div>

      <div className="calendar-board">
        <div className="calendar-grid-panel" aria-busy={dataLoading}>
          <div className={calendarView === CALENDAR_VIEW.MONTH ? "month-grid" : "week-grid"}>
            {WEEK_DAYS.map(d => <div key={d} className="weekday">{d}</div>)}
            {days.map(day => {
              const key = toInputDate(day);
              const events = eventsByDate.get(key) ?? [];
              const dayCount = totalForDay(key);
              const previewCount = calendarView === CALENDAR_VIEW.MONTH ? 2 : 3;
              const previews = events.slice(0, previewCount);
              return <div key={key} className={`day-cell ${day.getMonth() !== calendarDate.getMonth() ? "muted-cell" : ""} ${key === today ? "today-cell" : ""} ${key === selectedDay ? "selected-cell" : ""}`}>
                <button className="calendar-day-select" aria-label={`${day.toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}, публикаций: ${dayCount}`} aria-pressed={key === selectedDay} onClick={() => chooseDay(day)}>
                  <span>{day.getDate()}</span>{dayCount > 0 && <small>{dayCount}</small>}
                </button>
                <div className="mini-events">
                  {dataLoading ? <div className="calendar-cell-skeleton" /> : previews.map(event => <button key={event.id} className={`mini-event ${calendarEventClass(event, legend)}`} title={`${event.startTime} · ${event.title}`} onClick={() => openPublication(event)}><b>{event.startTime}</b><span>{event.title}</span></button>)}
                  {!dataLoading && dayCount > previews.length && <button className="mini-more" onClick={() => chooseDay(day)}>Ещё {dayCount - previews.length}</button>}
                </div>
              </div>;
            })}
          </div>
          <div className="calendar-grid-footer"><span><i /> Сегодня</span><span>Выберите день, чтобы увидеть все публикации</span></div>
        </div>

        <aside className="agenda-panel" aria-label="Публикации выбранного дня" aria-busy={dayLoading}>
          <div className="day-header"><div><p className="eyebrow">Публикации дня</p><h2>{parseInputDate(selectedDay).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}</h2></div><span className="agenda-count">{dayLoading ? "…" : dayTotal}</span></div>
          <button className="agenda-create" onClick={() => openSchedulePost(selectedDay)}>＋ Добавить публикацию</button>
          {dayError && <div className="workspace-error" role="alert"><span>{dayError}</span><button className="link-btn" onClick={retry}>Повторить</button></div>}
          <div className="day-list">
            {dayLoading ? <div className="agenda-skeleton" role="status">Загружаем публикации…</div> : !agendaEvents.length && !dayError ? <div className="workspace-empty agenda-empty"><span className="workspace-empty-symbol" aria-hidden="true">▦</span><h3>Здесь пока свободно</h3><p>На этот день публикаций нет. Самое время запланировать новую.</p></div> : null}
            {agendaEvents.map(event => {
              const url = calendarEventPublicationUrl(event, selectedPublicIds);
              return <article key={event.id} className={`day-event ${calendarEventClass(event, legend)}`}>
                <div className="agenda-event-meta"><time>{event.startTime}</time><span className={`publication-status status-${event.status}`}>{statusLabel[event.status as keyof typeof statusLabel] ?? event.status}</span></div>
                <button className="agenda-event-title" onClick={() => openPublication(event)}>{event.title || "Без названия"}</button>
                <p className="agenda-event-source">{event.platforms.join(", ")}</p>
                <div className="day-event-actions">
                  {url && <a className="link-btn" href={url} target="_blank" rel="noopener noreferrer">Открыть ↗</a>}
                  {event.origin !== "parsed" && <button className="link-btn" onClick={() => openEditEvent(event)}>Изменить пост</button>}
                  <button className="link-btn agenda-delete" aria-label={`Удалить пост: ${event.title}`} onClick={() => setDeleteTarget(event)}>Удалить</button>
                </div>
                {deleteTarget?.id === event.id && <div className="calendar-delete-confirm"><p>Удалить пост и все его публикации?</p><button className="link-btn danger" onClick={() => { removeEvent(event.id); setDeleteTarget(null); }}>Да, удалить</button><button className="link-btn" onClick={() => setDeleteTarget(null)}>Отмена</button></div>}
              </article>;
            })}
          </div>
          {(selectedEvents.length > agendaLimit || hasMore) && <button className="btn btn-outline agenda-more" disabled={loadingMore} onClick={() => {
            if (selectedEvents.length <= agendaLimit) loadMore();
            setAgendaLimit(value => value + 50);
          }}>{loadingMore ? "Загружаем…" : `Показать ещё · ${agendaEvents.length} из ${dayTotal}`}</button>}
        </aside>
      </div>
    </section>
  );
}
