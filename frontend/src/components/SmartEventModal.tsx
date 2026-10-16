import { useEffect, useState, type ChangeEvent, type Dispatch, type FormEvent, type RefObject, type SetStateAction } from "react";

import type { ApiInfoEvent, PainListItem } from "../api";
import type { MessageType, SmartEntryMode } from "../app/types";
import {
  EventForm,
  ImagePicker,
  LLMGeneratorPanel,
  PublishButton,
  SchedulePicker,
} from "./smartEventModalSections";

type PublicationTargetOption = {
  id: string;
  label: string;
};

type SmartEventModalProps = {
  open: boolean;
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
  publishToVk: boolean;
  smartScheduleDate: string;
  smartScheduleTime: string;
  painItems: PainListItem[];
  smartPainId: string;
  smartLlmLoading: boolean;
  smartGenerated: string;
  smartImagePreview: string | null;
  smartFileInputRef: RefObject<HTMLInputElement | null>;
  vkPublishing: boolean;
  smartMessage: string;
  smartMessageType: MessageType;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onHandleSmartSourceEventChange: (value: string) => void;
  onSetSmartTitle: Dispatch<SetStateAction<string>>;
  onSetSmartPrompt: Dispatch<SetStateAction<string>>;
  onSetSmartEventDate: Dispatch<SetStateAction<string>>;
  onSetSmartTone: Dispatch<SetStateAction<string>>;
  onSetSmartPostType: Dispatch<SetStateAction<string>>;
  onSetSmartScheduleEnabled: Dispatch<SetStateAction<boolean>>;
  onSetSmartPlatforms: Dispatch<SetStateAction<string[]>>;
  onSetSmartScheduleDate: Dispatch<SetStateAction<string>>;
  onSetSmartScheduleTime: Dispatch<SetStateAction<string>>;
  onHandleSmartPainSelect: (value: string) => Promise<void>;
  onHandleSmartGenerate: () => void;
  onSetSmartGenerated: Dispatch<SetStateAction<string>>;
  onHandleSmartImagePick: (event: ChangeEvent<HTMLInputElement>) => void;
  onClearSmartImage: () => void;
  onSetPublishToVk: Dispatch<SetStateAction<boolean>>;
};

export function SmartEventModal({
  open,
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
  publishToVk,
  smartScheduleDate,
  smartScheduleTime,
  painItems,
  smartPainId,
  smartLlmLoading,
  smartGenerated,
  smartImagePreview,
  smartFileInputRef,
  vkPublishing,
  smartMessage,
  smartMessageType,
  onClose,
  onSubmit,
  onHandleSmartSourceEventChange,
  onSetSmartTitle,
  onSetSmartPrompt,
  onSetSmartEventDate,
  onSetSmartTone,
  onSetSmartPostType,
  onSetSmartScheduleEnabled,
  onSetSmartPlatforms,
  onSetSmartScheduleDate,
  onSetSmartScheduleTime,
  onHandleSmartPainSelect,
  onHandleSmartGenerate,
  onSetSmartGenerated,
  onHandleSmartImagePick,
  onClearSmartImage,
  onSetPublishToVk,
}: SmartEventModalProps) {
  const [publicSearch, setPublicSearch] = useState("");

  useEffect(() => {
    if (!open) setPublicSearch("");
  }, [open]);

  if (!open) return null;

  const normalizedPublicSearch = publicSearch.trim().toLocaleLowerCase("ru-RU");
  const matchingPublicationTargets = normalizedPublicSearch
    ? publicationTargetOptions.filter((option) =>
        option.label.toLocaleLowerCase("ru-RU").includes(normalizedPublicSearch),
      )
    : publicationTargetOptions;
  // Выбранные варианты остаются видимыми, чтобы их можно было снять при
  // множественном выборе пабликов для публикации.
  const visiblePublicationTargets = normalizedPublicSearch
    ? publicationTargetOptions.filter(
        (option) =>
          matchingPublicationTargets.includes(option) || smartPlatforms.includes(option.id),
      )
    : publicationTargetOptions;

  return (
    <div className="modal-layer">
      <div className="modal modal-wide smart-event-modal" onClick={(event) => event.stopPropagation()}>
        <button className="close" type="button" onClick={onClose}>
          x
        </button>
        <h2>{smartEntryMode === "calendar" ? "Запланировать пост" : "Создать пост"}</h2>
        {smartEntryMode !== "calendar" && (
          <p className="muted">
            LLM генерирует текст поста, после сохранения запись попадает во вкладку
            {" "}«Контент». Оттуда пост можно опубликовать в VK вручную или сразу
            при сохранении через галочку ниже.
          </p>
        )}
        <form className="form" onSubmit={onSubmit}>
          <EventForm
            smartEntryMode={smartEntryMode}
            infoEvents={infoEvents}
            smartSourceEventId={smartSourceEventId}
            selectedSmartSourceEvent={selectedSmartSourceEvent}
            smartTitle={smartTitle}
            smartPrompt={smartPrompt}
            smartEventDate={smartEventDate}
            smartTone={smartTone}
            smartPostType={smartPostType}
            smartScheduleEnabled={smartScheduleEnabled}
            smartPlatforms={smartPlatforms}
            publicationTargetOptions={visiblePublicationTargets}
            publicationTargetCount={publicationTargetOptions.length}
            publicSearch={publicSearch}
            hasPublicSearchMatches={matchingPublicationTargets.length > 0}
            painItems={painItems}
            smartPainId={smartPainId}
            onHandleSmartSourceEventChange={onHandleSmartSourceEventChange}
            onSetSmartTitle={onSetSmartTitle}
            onSetSmartPrompt={onSetSmartPrompt}
            onSetSmartEventDate={onSetSmartEventDate}
            onSetSmartTone={onSetSmartTone}
            onSetSmartPostType={onSetSmartPostType}
            onSetSmartScheduleEnabled={onSetSmartScheduleEnabled}
            onSetSmartPlatforms={onSetSmartPlatforms}
            onSetPublicSearch={setPublicSearch}
            onHandleSmartPainSelect={onHandleSmartPainSelect}
          />
          <SchedulePicker
            smartEntryMode={smartEntryMode}
            smartScheduleEnabled={smartScheduleEnabled}
            publishToVk={publishToVk}
            smartPlatforms={smartPlatforms}
            publicationTargetOptions={visiblePublicationTargets}
            publicationTargetCount={publicationTargetOptions.length}
            hasPublicSearchMatches={matchingPublicationTargets.length > 0}
            smartScheduleDate={smartScheduleDate}
            smartScheduleTime={smartScheduleTime}
            onSetSmartPlatforms={onSetSmartPlatforms}
            onSetSmartScheduleDate={onSetSmartScheduleDate}
            onSetSmartScheduleTime={onSetSmartScheduleTime}
          />
          <LLMGeneratorPanel
            smartLlmLoading={smartLlmLoading}
            smartGenerated={smartGenerated}
            onHandleSmartGenerate={onHandleSmartGenerate}
            onSetSmartGenerated={onSetSmartGenerated}
          />
          <ImagePicker
            smartImagePreview={smartImagePreview}
            smartFileInputRef={smartFileInputRef}
            onHandleSmartImagePick={onHandleSmartImagePick}
            onClearSmartImage={onClearSmartImage}
          />
          <PublishButton
            publishToVk={publishToVk}
            vkPublishing={vkPublishing}
            onSetPublishToVk={onSetPublishToVk}
          />
        </form>
        <p className={`message ${smartMessageType}`}>{smartMessage}</p>
      </div>
    </div>
  );
}
