import type { Dispatch, FormEvent, SetStateAction } from "react";

import type { ApiInfoEvent } from "../api";
import { SMART_POST_TYPES } from "../app/constants";
import { EVENT_STATUS } from "../constants";
import type { EventStatus, MessageType, SeriesPlanItem } from "../app/types";

type PublicationTargetOption = {
  id: string;
  label: string;
};

export type CalendarModalProps = {
  open: boolean;
  eventTitle: string;
  eventDescription: string;
  eventDraft: string;
  eventTone: string;
  eventPostType: string;
  eventDate: string;
  eventTime: string;
  eventStatus: EventStatus;
  eventSeriesCount: number;
  eventSeriesStepMinutes: number;
  eventSeriesItems: SeriesPlanItem[];
  eventPlatforms: string[];
  publicationTargetOptions: PublicationTargetOption[];
  editingEventId: string | null;
  calendarGenerating: boolean;
  calendarGenerationProgress: number;
  calendarMessage: string;
  calendarMessageType: MessageType;
  infoEvents: ApiInfoEvent[];
  eventInfoEventId: string | null;
  onSetEventInfoEventId: Dispatch<SetStateAction<string | null>>;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onSetEventTitle: Dispatch<SetStateAction<string>>;
  onSetEventDescription: Dispatch<SetStateAction<string>>;
  onSetEventDraft: Dispatch<SetStateAction<string>>;
  onSetEventTone: Dispatch<SetStateAction<string>>;
  onSetEventPostType: Dispatch<SetStateAction<string>>;
  onSetEventDate: Dispatch<SetStateAction<string>>;
  onSetEventTime: Dispatch<SetStateAction<string>>;
  onSetEventStatus: Dispatch<SetStateAction<EventStatus>>;
  onSetEventSeriesCount: Dispatch<SetStateAction<number>>;
  onSetEventSeriesStepMinutes: Dispatch<SetStateAction<number>>;
  onSetEventSeriesItems: Dispatch<SetStateAction<SeriesPlanItem[]>>;
  onSetEventPlatforms: Dispatch<SetStateAction<string[]>>;
};

export function CalendarModal({
  open,
  eventTitle,
  eventDescription,
  eventDraft,
  eventTone,
  eventPostType,
  eventDate,
  eventTime,
  eventStatus,
  eventSeriesCount,
  eventSeriesStepMinutes,
  eventSeriesItems,
  eventPlatforms,
  publicationTargetOptions,
  editingEventId,
  calendarGenerating,
  calendarGenerationProgress,
  calendarMessage,
  calendarMessageType,
  infoEvents,
  eventInfoEventId,
  onSetEventInfoEventId,
  onClose,
  onSubmit,
  onSetEventTitle,
  onSetEventDescription,
  onSetEventDraft,
  onSetEventTone,
  onSetEventPostType,
  onSetEventDate,
  onSetEventTime,
  onSetEventStatus,
  onSetEventSeriesCount,
  onSetEventSeriesStepMinutes,
  onSetEventSeriesItems,
  onSetEventPlatforms,
}: CalendarModalProps) {
  if (!open) return null;

  return (
    <div className="modal-layer" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <button className="close" onClick={onClose}>
          x
        </button>
        <h2>{editingEventId ? "Редактирование публикации" : "Новая публикация"}</h2>
        <p className="muted">{editingEventId ? "Настройки поста применяются ко всем выбранным площадкам." : "Подготовьте текст, выберите сообщества и время выхода."}</p>
        <form className="form" onSubmit={onSubmit}>
          <label>
            Название
            <input type="text" value={eventTitle} onChange={(event) => onSetEventTitle(event.target.value)} required />
          </label>
          <label>
            Описание
            <input
              type="text"
              value={eventDescription}
              onChange={(event) => onSetEventDescription(event.target.value)}
              placeholder="Кратко о событии"
            />
          </label>
          <label>
            Черновик поста
            <textarea
              rows={4}
              value={eventDraft}
              onChange={(event) => onSetEventDraft(event.target.value)}
              placeholder="Текст черновика для будущей публикации"
            />
          </label>
          <label>
            Стиль
            <input
              type="text"
              value={eventTone}
              onChange={(event) => onSetEventTone(event.target.value)}
              placeholder="Например: дружелюбный, официальный, короткий"
            />
          </label>
          <label>
            Тип поста
            <select value={eventPostType} onChange={(event) => onSetEventPostType(event.target.value)}>
              <option value="">Не выбран</option>
              {SMART_POST_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Привязать к инфоповоду <span className="muted" style={{ fontWeight: 400 }}>(опционально - пост наследует боли)</span>
            <select
              value={eventInfoEventId ?? ""}
              onChange={(event) => onSetEventInfoEventId(event.target.value || null)}
            >
              <option value="">Без привязки</option>
              {[...infoEvents]
                .sort((a, b) => (b.event_date || "").localeCompare(a.event_date || ""))
                .slice(0, 50)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}{item.event_date ? ` · ${new Date(item.event_date).toLocaleDateString("ru-RU")}` : ""}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Дата
            <input type="date" value={eventDate} onChange={(event) => onSetEventDate(event.target.value)} required />
          </label>
          <label>
            Время
            <input type="time" value={eventTime} onChange={(event) => onSetEventTime(event.target.value)} required />
          </label>
          <label>
            Статус
            <select value={eventStatus} onChange={(event) => onSetEventStatus(event.target.value as EventStatus)}>
              <option value={EVENT_STATUS.DRAFT}>Черновик</option>
              <option value={EVENT_STATUS.SCHEDULED}>Запланирован</option>
              <option value={EVENT_STATUS.PUBLISHED}>Опубликован</option>
            </select>
          </label>
          {!editingEventId && eventStatus === EVENT_STATUS.SCHEDULED && (
            <>
              <label>
                Серия постов (количество)
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={eventSeriesCount}
                  onChange={(event) => onSetEventSeriesCount(Number(event.target.value))}
                />
              </label>
              <label>
                Шаг между постами (минут)
                <input
                  type="number"
                  min={1}
                  max={240}
                  value={eventSeriesStepMinutes}
                  onChange={(event) => onSetEventSeriesStepMinutes(Number(event.target.value))}
                />
              </label>
              <div className="platforms" style={{ display: "block" }}>
                <span>План серии (редактируемый):</span>
                <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
                  {eventSeriesItems.map((item, index) => (
                    <div
                      key={item.id}
                      style={{ border: "1px solid rgba(255,255,255,0.15)", borderRadius: 10, padding: 10 }}
                    >
                      <label>
                        Заголовок поста #{index + 1}
                        <input
                          type="text"
                          value={item.title}
                          onChange={(event) =>
                            onSetEventSeriesItems((prev) =>
                              prev.map((current, currentIndex) =>
                                currentIndex === index ? { ...current, title: event.target.value } : current,
                              ),
                            )
                          }
                        />
                      </label>
                      <label>
                        Описание поста #{index + 1}
                        <textarea
                          rows={2}
                          value={item.description}
                          onChange={(event) =>
                            onSetEventSeriesItems((prev) =>
                              prev.map((current, currentIndex) =>
                                currentIndex === index ? { ...current, description: event.target.value } : current,
                              ),
                            )
                          }
                        />
                      </label>
                      <label>
                        Тип поста #{index + 1}
                        <select
                          value={item.postType}
                          onChange={(event) =>
                            onSetEventSeriesItems((prev) =>
                              prev.map((current, currentIndex) =>
                                currentIndex === index ? { ...current, postType: event.target.value } : current,
                              ),
                            )
                          }
                        >
                          <option value="">Не выбран</option>
                          {SMART_POST_TYPES.map((type) => (
                            <option key={type.value} value={type.value}>
                              {type.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
          <div className="platforms">
            <span>Паблики:</span>
            {publicationTargetOptions.map((option) => (
              <label key={option.id} className="checkbox-line">
                <input
                  type="checkbox"
                  checked={eventPlatforms.includes(option.id)}
                  onChange={(event) => {
                    if (event.target.checked) {
                      onSetEventPlatforms((prev) => [...new Set([...prev, option.id])]);
                    } else {
                      onSetEventPlatforms((prev) => prev.filter((id) => id !== option.id));
                    }
                  }}
                />
                {option.label}
              </label>
            ))}
            {!publicationTargetOptions.length && (
              <p className="muted">Не найдено ни одного доступного паблика для планирования.</p>
            )}
          </div>
          <button className="btn btn-primary" type="submit" disabled={calendarGenerating}>
            {calendarGenerating
              ? `Генерация постов... ${calendarGenerationProgress}${!editingEventId && eventStatus === EVENT_STATUS.SCHEDULED ? `/${Math.max(1, Math.min(30, Math.trunc(eventSeriesCount || 1)))}` : ""}`
              : editingEventId
                ? "Сохранить изменения"
                : "Создать событие"}
          </button>
        </form>
        <p className={`message ${calendarMessageType}`}>
          {calendarGenerating
            ? "Посты генерируются и сохраняются в «Контент». Пожалуйста, дождитесь завершения."
            : calendarMessage}
        </p>
      </div>
    </div>
  );
}
