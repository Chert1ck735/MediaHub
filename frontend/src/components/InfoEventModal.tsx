import type { Dispatch, FormEvent, SetStateAction } from "react";

import type { InfoEventForm, MessageType } from "../app/types";

export type InfoEventModalProps = {
  open: boolean;
  authToken: string;
  infoEventCreating: boolean;
  editingInfoEventId: string | null;
  infoEventForm: InfoEventForm;
  infoEventMessage: string;
  infoEventMessageType: MessageType;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onSetInfoEventForm: Dispatch<SetStateAction<InfoEventForm>>;
};

export function InfoEventModal({
  open,
  authToken,
  infoEventCreating,
  editingInfoEventId,
  infoEventForm,
  infoEventMessage,
  infoEventMessageType,
  onClose,
  onSubmit,
  onSetInfoEventForm,
}: InfoEventModalProps) {
  if (!open) return null;

  return (
    <div className="modal-layer" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <button className="close" type="button" onClick={onClose}>
          x
        </button>
        <h2>{editingInfoEventId ? "Редактировать событие" : "Добавить событие вручную"}</h2>
        <p className="muted">
          {editingInfoEventId
            ? "Изменения сразу сохранятся в реальной таблице `events`."
            : "Логика сохранения та же: запись сразу попадёт в реальную таблицу `events`."}
        </p>
        <form className="form" onSubmit={onSubmit}>
          <label>
            Название
            <input
              value={infoEventForm.title}
              onChange={(event) => onSetInfoEventForm((prev) => ({ ...prev, title: event.target.value }))}
              placeholder="Например: Прямая линия по транспорту"
              disabled={!authToken || infoEventCreating}
            />
          </label>
          <label>
            Дата
            <input
              type="date"
              value={infoEventForm.eventDate}
              onChange={(event) => onSetInfoEventForm((prev) => ({ ...prev, eventDate: event.target.value }))}
              disabled={!authToken || infoEventCreating}
            />
          </label>
          <label>
            Регион / место
            <input
              value={infoEventForm.location}
              onChange={(event) => onSetInfoEventForm((prev) => ({ ...prev, location: event.target.value }))}
              placeholder="Красноярск"
              disabled={!authToken || infoEventCreating}
            />
          </label>
          <label>
            Описание
            <textarea
              value={infoEventForm.description}
              onChange={(event) => onSetInfoEventForm((prev) => ({ ...prev, description: event.target.value }))}
              placeholder="Краткое описание события"
              disabled={!authToken || infoEventCreating}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={!authToken || infoEventCreating}>
            {infoEventCreating ? "Сохранение..." : editingInfoEventId ? "Сохранить изменения" : "Добавить событие"}
          </button>
        </form>
        <p className={`message ${infoEventMessageType}`}>{infoEventMessage}</p>
      </div>
    </div>
  );
}
