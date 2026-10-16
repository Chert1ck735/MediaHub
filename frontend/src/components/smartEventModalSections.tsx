import { useState, type ChangeEvent, type Dispatch, type RefObject, type SetStateAction } from "react";

import type { ApiInfoEvent, PainListItem } from "../api";
import { MAX_ATTACHMENT_BYTES, SMART_POST_TYPES } from "../app/constants";
import type { SmartEntryMode } from "../app/types";

type PublicationTargetOption = {
  id: string;
  label: string;
};

type EventFormProps = {
  smartEntryMode: SmartEntryMode;
  infoEvents: ApiInfoEvent[];
  smartSourceEventId: string;
  selectedSmartSourceEvent: ApiInfoEvent | null;
  smartTitle: string;
  smartPrompt: string;
  smartEventDate: string;
  smartTone: string;
  smartPostType: string;
  smartScheduleEnabled: boolean;
  smartPlatforms: string[];
  publicationTargetOptions: PublicationTargetOption[];
  publicationTargetCount: number;
  publicSearch: string;
  hasPublicSearchMatches: boolean;
  painItems: PainListItem[];
  smartPainId: string;
  onHandleSmartSourceEventChange: (value: string) => void;
  onSetSmartTitle: Dispatch<SetStateAction<string>>;
  onSetSmartPrompt: Dispatch<SetStateAction<string>>;
  onSetSmartEventDate: Dispatch<SetStateAction<string>>;
  onSetSmartTone: Dispatch<SetStateAction<string>>;
  onSetSmartPostType: Dispatch<SetStateAction<string>>;
  onSetSmartScheduleEnabled: Dispatch<SetStateAction<boolean>>;
  onSetSmartPlatforms: Dispatch<SetStateAction<string[]>>;
  onSetPublicSearch: Dispatch<SetStateAction<string>>;
  onHandleSmartPainSelect: (value: string) => Promise<void>;
};

export function EventForm({
  smartEntryMode,
  infoEvents,
  smartSourceEventId,
  selectedSmartSourceEvent,
  smartTitle,
  smartPrompt,
  smartEventDate,
  smartTone,
  smartPostType,
  smartScheduleEnabled,
  smartPlatforms,
  publicationTargetOptions,
  publicationTargetCount,
  publicSearch,
  hasPublicSearchMatches,
  painItems,
  smartPainId,
  onHandleSmartSourceEventChange,
  onSetSmartTitle,
  onSetSmartPrompt,
  onSetSmartEventDate,
  onSetSmartTone,
  onSetSmartPostType,
  onSetSmartScheduleEnabled,
  onSetSmartPlatforms,
  onSetPublicSearch,
  onHandleSmartPainSelect,
}: EventFormProps) {
  return (
    <>
      <label>
        Поиск паблика
        <input
          type="search"
          value={publicSearch}
          onChange={(event) => onSetPublicSearch(event.target.value)}
          placeholder="Введите название паблика"
          autoComplete="off"
        />
      </label>
      <label>
        Паблик для поста
        <select
          value={smartPlatforms[0] ?? ""}
          onChange={(event) => onSetSmartPlatforms(event.target.value ? [event.target.value] : [])}
          required
        >
          <option value="">Выберите паблик</option>
          {publicationTargetOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
          {!!publicSearch.trim() && !hasPublicSearchMatches && (
            <option value="" disabled>Паблики не найдены</option>
          )}
        </select>
        {!publicationTargetCount && (
          <small className="attachment-hint">Сначала добавьте паблик в настройках организации.</small>
        )}
      </label>
      {!!infoEvents.length && (
        <label>
          Событие-источник
          <select value={smartSourceEventId} onChange={(event) => onHandleSmartSourceEventChange(event.target.value)}>
            <option value="">Не выбрано</option>
            {infoEvents.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title} · {new Date(item.event_date).toLocaleDateString("ru-RU")}
              </option>
            ))}
          </select>
        </label>
      )}
      {selectedSmartSourceEvent && (
        <p className="muted">
          В форму подтянутся название, дата и описание события из вкладки «События».
          Текст можно отредактировать вручную.
        </p>
      )}
      <label>
        Название события (необязательно)
        <input
          type="text"
          value={smartTitle}
          onChange={(event) => onSetSmartTitle(event.target.value)}
          placeholder="Например: Кинопоказ на Татышеве"
        />
      </label>
      <label>
        Описание события
        <textarea
          rows={4}
          value={smartPrompt}
          onChange={(event) => onSetSmartPrompt(event.target.value)}
          placeholder="Что произошло, где и для кого это важно; какие факты нужно сообщить…"
          required
        />
      </label>
      <label>
        Дата события (необязательно)
        <input
          type="date"
          value={smartEventDate}
          onChange={(event) => onSetSmartEventDate(event.target.value)}
        />
      </label>
      <label>
        Тон и стиль (необязательно)
        <input
          type="text"
          value={smartTone}
          onChange={(event) => onSetSmartTone(event.target.value)}
          placeholder="Дружелюбно, с хэштегами, коротко…"
        />
      </label>
      <label>
        Тип поста
        <select value={smartPostType} onChange={(event) => onSetSmartPostType(event.target.value)}>
          <option value="">Не выбран</option>
          {SMART_POST_TYPES.map((type) => (
            <option key={type.value} value={type.value}>
              {type.label}
            </option>
          ))}
        </select>
      </label>
      {smartEntryMode === "content" && (
        <label className="checkbox-line">
          <input
            type="checkbox"
            checked={smartScheduleEnabled}
            onChange={(event) => onSetSmartScheduleEnabled(event.target.checked)}
          />
          Запланировать публикацию в календаре
        </label>
      )}
      {!!painItems.length && (
        <label>
          Боль / тема
          <span className="muted" style={{ fontWeight: "normal", fontSize: "0.85em" }}>
            {" "}для более точного текста
          </span>
          <select value={smartPainId} onChange={(event) => void onHandleSmartPainSelect(event.target.value)}>
            <option value="">Не выбрано</option>
            {painItems.map((pain) => (
              <option key={pain.id} value={pain.id}>
                {pain.title}
              </option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}

type SchedulePickerProps = {
  smartEntryMode: SmartEntryMode;
  smartScheduleEnabled: boolean;
  publishToVk: boolean;
  smartPlatforms: string[];
  publicationTargetOptions: PublicationTargetOption[];
  publicationTargetCount: number;
  hasPublicSearchMatches: boolean;
  smartScheduleDate: string;
  smartScheduleTime: string;
  onSetSmartPlatforms: Dispatch<SetStateAction<string[]>>;
  onSetSmartScheduleDate: Dispatch<SetStateAction<string>>;
  onSetSmartScheduleTime: Dispatch<SetStateAction<string>>;
};

export function SchedulePicker({
  smartEntryMode,
  smartScheduleEnabled,
  publishToVk,
  smartPlatforms,
  publicationTargetOptions,
  publicationTargetCount,
  hasPublicSearchMatches,
  smartScheduleDate,
  smartScheduleTime,
  onSetSmartPlatforms,
  onSetSmartScheduleDate,
  onSetSmartScheduleTime,
}: SchedulePickerProps) {
  if (!(smartEntryMode === "calendar" || smartScheduleEnabled || publishToVk)) return null;

  return (
    <>
      <div className="platforms">
        <span>Паблики:</span>
        {publicationTargetOptions.map((option) => (
          <label key={option.id} className="checkbox-line">
            <input
              type="checkbox"
              checked={smartPlatforms.includes(option.id)}
              onChange={(event) => {
                if (event.target.checked) {
                  onSetSmartPlatforms((prev) => [...new Set([...prev, option.id])]);
                } else {
                  onSetSmartPlatforms((prev) => prev.filter((item) => item !== option.id));
                }
              }}
            />
            {option.label}
          </label>
        ))}
        {!publicationTargetCount && (
          <p className="muted">Не найдено ни одного доступного паблика для планирования.</p>
        )}
        {!!publicationTargetCount && !hasPublicSearchMatches && (
          <p className="muted">По вашему запросу паблики не найдены.</p>
        )}
      </div>
      {(smartEntryMode === "calendar" || smartScheduleEnabled) && (
        <>
          <label>
            Дата публикации
            <input
              type="date"
              value={smartScheduleDate}
              onChange={(event) => onSetSmartScheduleDate(event.target.value)}
              required={smartEntryMode === "calendar" || smartScheduleEnabled}
            />
          </label>
          <label>
            Время публикации
            <input
              type="time"
              value={smartScheduleTime}
              onChange={(event) => onSetSmartScheduleTime(event.target.value)}
              required={smartEntryMode === "calendar" || smartScheduleEnabled}
            />
          </label>
        </>
      )}
    </>
  );
}

type LLMGeneratorPanelProps = {
  smartLlmLoading: boolean;
  smartGenerated: string;
  onHandleSmartGenerate: () => void;
  onSetSmartGenerated: Dispatch<SetStateAction<string>>;
};

export function LLMGeneratorPanel({
  smartLlmLoading,
  smartGenerated,
  onHandleSmartGenerate,
  onSetSmartGenerated,
}: LLMGeneratorPanelProps) {
  const [copyStatus, setCopyStatus] = useState("");

  const copyGeneratedText = async () => {
    if (!smartGenerated.trim()) return;
    try {
      await navigator.clipboard.writeText(smartGenerated);
      setCopyStatus("Текст скопирован");
    } catch {
      setCopyStatus("Не удалось скопировать текст");
    }
  };

  return (
    <>
      <div className="smart-llm-row">
        <button className="btn btn-outline" type="button" onClick={onHandleSmartGenerate} disabled={smartLlmLoading}>
          {smartLlmLoading ? "Генерация…" : "Сгенерировать текст (LLM)"}
        </button>
      </div>
      <label>
        Готовый текст поста
        <textarea
          rows={5}
          value={smartGenerated}
          onChange={(event) => onSetSmartGenerated(event.target.value)}
          placeholder="Здесь появится текст от ИИ. Его можно отредактировать перед сохранением или копированием."
        />
      </label>
      <div className="smart-llm-row">
        <button
          className="btn btn-outline"
          type="button"
          onClick={() => void copyGeneratedText()}
          disabled={!smartGenerated.trim()}
        >
          Скопировать текст
        </button>
        {copyStatus && <span className="attachment-hint">{copyStatus}</span>}
      </div>
    </>
  );
}

type ImagePickerProps = {
  smartImagePreview: string | null;
  smartFileInputRef: RefObject<HTMLInputElement | null>;
  onHandleSmartImagePick: (event: ChangeEvent<HTMLInputElement>) => void;
  onClearSmartImage: () => void;
};

export function ImagePicker({
  smartImagePreview,
  smartFileInputRef,
  onHandleSmartImagePick,
  onClearSmartImage,
}: ImagePickerProps) {
  return (
    <div className="smart-attachment-block">
      <span className="smart-attachment-label">Изображение к событию</span>
      <input
        ref={smartFileInputRef}
        type="file"
        accept="image/*"
        className="visually-hidden"
        onChange={onHandleSmartImagePick}
      />
      <div className="smart-attachment-row">
        <button className="btn btn-secondary" type="button" onClick={() => smartFileInputRef.current?.click()}>
          Прикрепить изображение
        </button>
        {smartImagePreview && (
          <button className="btn btn-outline" type="button" onClick={onClearSmartImage}>
            Убрать файл
          </button>
        )}
      </div>
      {smartImagePreview && <img src={smartImagePreview} alt="Предпросмотр" className="smart-preview" />}
      <small className="attachment-hint">До {Math.round(MAX_ATTACHMENT_BYTES / 1024)} КБ, хранится в браузере.</small>
    </div>
  );
}

type PublishButtonProps = {
  publishToVk: boolean;
  vkPublishing: boolean;
  onSetPublishToVk: Dispatch<SetStateAction<boolean>>;
};

export function PublishButton({ publishToVk, vkPublishing, onSetPublishToVk }: PublishButtonProps) {
  return (
    <>
      <label className="checkbox-line vk-publish-line">
        <input
          type="checkbox"
          checked={publishToVk}
          onChange={(event) => onSetPublishToVk(event.target.checked)}
          disabled={vkPublishing}
        />
        Опубликовать на стену VK после сохранения (тот же текст: заголовок + пост/промпт)
      </label>
      <button className="btn btn-primary" type="submit" disabled={vkPublishing}>
        {vkPublishing ? "Публикация в VK…" : "Сохранить"}
      </button>
    </>
  );
}
