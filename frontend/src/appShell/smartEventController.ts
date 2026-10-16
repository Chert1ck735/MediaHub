import {
  apiCreateCalendarEvent,
  apiCreatePost,
  llmGenerate,
  type ApiInfoEvent,
  type ApiPost,
} from "../api";
import { MAX_ATTACHMENT_BYTES } from "../app/constants";
import { apiCalendarEventToCalendarEvent, apiPostToContentEvent, focusCalendarOnDate } from "../app/mappers";
import { EVENT_STATUS, GENERATED_TEXT_MAX_LENGTH, MESSAGE_STATUS } from "../constants";
import { readFileAsDataURL, cleanGeneratedPostText, createClientId, cropText, localCalendarToUtcPayload, toInputDate } from "../app/utils";

export function buildSmartPromptFromInfoEvent(eventItem: ApiInfoEvent) {
  const parts = [
    `Событие: ${eventItem.title}`,
    `Дата: ${new Date(eventItem.event_date).toLocaleDateString("ru-RU")}`,
  ];
  if (eventItem.location?.trim()) {
    parts.push(`Место: ${eventItem.location.trim()}`);
  }
  if (eventItem.description?.trim()) {
    parts.push(`Описание: ${eventItem.description.trim()}`);
  }
  parts.push("Подготовь пост для публикации по этому событию: понятно, конкретно, с призывом к действию при необходимости.");
  return parts.join("\n");
}

export function applyInfoEventToSmartForm(eventItem: ApiInfoEvent, ctx: any) {
  ctx.setSmartSourceEventId(eventItem.id);
  ctx.setSmartTitle(eventItem.title);
  ctx.setSmartPrompt(buildSmartPromptFromInfoEvent(eventItem));
  ctx.setSmartEventDate(eventItem.event_date.slice(0, 10));
  ctx.setSmartScheduleDate(eventItem.event_date.slice(0, 10));
}

export function openSmartEventAction(sourceEvent: ApiInfoEvent | null | undefined, options: { entryMode?: string; scheduleDate?: string; scheduleTime?: string } | undefined, ctx: any) {
  const entryMode = options?.entryMode ?? "content";
  const defaultScheduleDate = options?.scheduleDate ?? ctx.selectedDay ?? toInputDate(new Date());
  const defaultScheduleTime = options?.scheduleTime ?? "10:00";
  ctx.setSmartEntryMode(entryMode);
  ctx.setSmartSourceEventId("");
  ctx.setSmartTitle("");
  ctx.setSmartPrompt("");
  ctx.setSmartEventDate("");
  ctx.setSmartTone("");
  ctx.setSmartPostType("");
  ctx.setSmartPlatforms([]);
  ctx.setSmartScheduleEnabled(entryMode === "calendar");
  ctx.setSmartScheduleDate(defaultScheduleDate);
  ctx.setSmartScheduleTime(defaultScheduleTime);
  ctx.setSmartGenerated("");
  ctx.setSmartPainId("");
  ctx.setSmartStrategyId("");
  ctx.setSmartPainDetail(null);
  ctx.setSmartMessage("");
  ctx.setSmartMessageType(MESSAGE_STATUS.IDLE);
  ctx.setSmartImageFile(null);
  ctx.setSmartImagePreview(null);
  ctx.setPublishToVk(false);
  ctx.setVkPublishing(false);
  if (ctx.smartFileInputRef.current) ctx.smartFileInputRef.current.value = "";
  if (sourceEvent) {
    applyInfoEventToSmartForm(sourceEvent, ctx);
  }
  ctx.setSmartEventOpen(true);
}

export function closeSmartEventAction(ctx: any) {
  ctx.setSmartEventOpen(false);
  ctx.setSmartEntryMode("content");
  ctx.setSmartLlmLoading(false);
  ctx.setVkPublishing(false);
}

export function handleSmartSourceEventChangeAction(eventId: string, ctx: any) {
  ctx.setSmartSourceEventId(eventId);
  const eventItem = ctx.infoEvents.find((item: ApiInfoEvent) => item.id === eventId);
  if (!eventItem) return;
  applyInfoEventToSmartForm(eventItem, ctx);
}

export function handleSmartPainSelectAction(painId: string, ctx: any) {
  ctx.setSmartPainId(painId);
  ctx.setSmartStrategyId("");
  ctx.setSmartPainDetail(null);
}

export async function handleSmartImagePickAction(event: any, ctx: any) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Нужен файл изображения.");
    return;
  }
  try {
    const url = await readFileAsDataURL(file, MAX_ATTACHMENT_BYTES);
    ctx.setSmartImageFile(file);
    ctx.setSmartImagePreview(url);
    ctx.setSmartMessageType(MESSAGE_STATUS.IDLE);
    ctx.setSmartMessage("");
  } catch (err) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage(err instanceof Error ? err.message : "Ошибка файла");
    ctx.setSmartImageFile(null);
    ctx.setSmartImagePreview(null);
  }
}

export function clearSmartImageAction(ctx: any) {
  ctx.setSmartImageFile(null);
  ctx.setSmartImagePreview(null);
  if (ctx.smartFileInputRef.current) ctx.smartFileInputRef.current.value = "";
}

export function buildSmartGeneratePayload(ctx: any) {
  return {
    public_social_link_id: ctx.smartPlatforms[0] || "",
    event_description: ctx.smartPrompt.trim(),
    event_date: ctx.smartEventDate || undefined,
    post_type: ctx.smartPostType || undefined,
  };
}

export function buildSmartFallbackText(ctx: any) {
  return cleanGeneratedPostText(ctx.smartPrompt.trim());
}

export async function handleSmartGenerateAction(ctx: any) {
  if (!ctx.smartPlatforms[0]) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Выберите паблик, для которого нужно подготовить пост.");
    return;
  }
  if (!ctx.smartPrompt.trim()) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Опишите событие для генерации поста.");
    return;
  }
  ctx.setSmartLlmLoading(true);
  ctx.setSmartMessage("");
  try {
    const res = await llmGenerate(ctx.authToken, buildSmartGeneratePayload(ctx));
    ctx.setSmartGenerated(cleanGeneratedPostText(res.text));
    ctx.setSmartMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setSmartMessage(`Пост сгенерирован (${res.model}).`);
  } catch (err) {
    const fallback = buildSmartFallbackText(ctx);
    if (fallback) {
      ctx.setSmartGenerated(fallback);
    }
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage(
      err instanceof Error
        ? `${err.message}. Подставлен черновик без LLM.`
        : "Ошибка LLM. Подставлен черновик без LLM."
    );
  } finally {
    ctx.setSmartLlmLoading(false);
  }
}

export async function handleSmartSubmitAction(event: any, ctx: any) {
  event.preventDefault();
  const shouldSchedule = ctx.smartEntryMode === "calendar" || ctx.smartScheduleEnabled;
  if (!ctx.smartPlatforms[0]) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Выберите паблик для поста.");
    return;
  }
  if (!ctx.smartPrompt.trim()) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Опишите событие для поста.");
    return;
  }
  const postTitle = ctx.smartTitle.trim() || cropText(ctx.smartPrompt.trim(), 90);
  if (shouldSchedule && (!ctx.smartScheduleDate || !ctx.smartScheduleTime)) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Укажите дату и время публикации.");
    return;
  }
  if (shouldSchedule && ctx.smartPlatforms.length === 0) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Выберите хотя бы один паблик.");
    return;
  }
  if (ctx.publishToVk && ctx.smartPlatforms.length === 0) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Выберите паблик для публикации.");
    return;
  }
  if (shouldSchedule && !ctx.authToken) {
    ctx.setSmartMessageType(MESSAGE_STATUS.ERROR);
    ctx.setSmartMessage("Для планирования публикации нужно войти в аккаунт.");
    ctx.openAuth("login");
    return;
  }

  let generatedText = (ctx.smartGenerated.trim() || "").slice(0, GENERATED_TEXT_MAX_LENGTH);
  if (!generatedText) {
    try {
      const res = await llmGenerate(ctx.authToken, buildSmartGeneratePayload(ctx));
      generatedText = cleanGeneratedPostText(res.text).slice(0, GENERATED_TEXT_MAX_LENGTH);
    } catch {
      generatedText = buildSmartFallbackText(ctx).slice(0, GENERATED_TEXT_MAX_LENGTH);
    }
  }
  generatedText = cleanGeneratedPostText(generatedText).slice(0, GENERATED_TEXT_MAX_LENGTH);

  let savedPost: ApiPost | null = null;
  if (ctx.authToken) {
    try {
      savedPost = await apiCreatePost(ctx.authToken, {
        title: postTitle,
        text_draft: ctx.smartPrompt.trim(),
        text_generated: generatedText,
        tone: ctx.smartTone.trim(),
        vk_post_id: null,
        strategy_id: ctx.smartStrategyId || null,
      });
    } catch {}
  }

  const newItem = savedPost
    ? {
        ...apiPostToContentEvent(savedPost),
        attachmentName: ctx.smartImageFile?.name ?? undefined,
        attachmentDataUrl: ctx.smartImagePreview ?? undefined,
      }
    : {
        id: createClientId(),
        title: postTitle,
        prompt: ctx.smartPrompt.trim(),
        tone: ctx.smartTone.trim(),
        generatedText,
        attachmentName: ctx.smartImageFile?.name ?? undefined,
        attachmentDataUrl: ctx.smartImagePreview ?? undefined,
        strategyId: ctx.smartStrategyId || null,
        createdAt: new Date().toISOString(),
      };

  ctx.setContentEvents((prev: any[]) => [newItem, ...prev]);

  if (ctx.authToken && shouldSchedule) {
    try {
      const scheduleStart = new Date(`${ctx.smartScheduleDate}T${ctx.smartScheduleTime}:00`);
      const scheduleEnd = new Date(scheduleStart.getTime() + ctx.DEFAULT_EVENT_SLOT_MS);
      const scheduleEndTime = `${String(scheduleEnd.getHours()).padStart(2, "0")}:${String(scheduleEnd.getMinutes()).padStart(2, "0")}`;
      const utcScheduleStart = localCalendarToUtcPayload(ctx.smartScheduleDate, ctx.smartScheduleTime);
      const utcScheduleEnd = localCalendarToUtcPayload(ctx.smartScheduleDate, scheduleEndTime);
      const savedCalendarEvent = await apiCreateCalendarEvent(ctx.authToken, {
        title: postTitle,
        date: utcScheduleStart.date,
        description: ctx.smartPrompt.trim() || "Запланированная публикация поста",
        start_time: utcScheduleStart.time,
        end_time: utcScheduleEnd.time,
        status: EVENT_STATUS.SCHEDULED,
        platforms: [],
        public_social_link_ids: [...new Set((ctx.smartPlatforms as string[]).filter(Boolean))],
        draft: generatedText,
        tone: ctx.smartTone.trim(),
        post_type: ctx.smartPostType,
        post_id: savedPost?.id ?? null,
        info_event_id: ctx.smartSourceEventId || null,
      });
      focusCalendarOnDate(ctx.smartScheduleDate, ctx.setSelectedDay, ctx.setCalendarDate);
      await ctx.reloadContentFromBackend();
      ctx.setEvents((prev: any[]) => {
        const next = [...prev, apiCalendarEventToCalendarEvent(savedCalendarEvent)];
        next.sort((a, b) => (a.date + a.startTime).localeCompare(b.date + b.startTime));
        return next;
      });
      await ctx.reloadCalendarFromBackend();
    } catch (err) {
      ctx.setContentMessageType(MESSAGE_STATUS.ERROR);
      ctx.setContentMessage(err instanceof Error
        ? `Пост сохранен, но не удалось добавить его в календарь: ${err.message}`
        : "Пост сохранен, но не удалось добавить его в календарь.");
      ctx.closeSmartEvent();
      return;
    }
  }

  if (ctx.publishToVk) {
    ctx.setVkPublishing(true);
    ctx.setSmartMessageType(MESSAGE_STATUS.IDLE);
    ctx.setSmartMessage("");
    try {
      const vk = await ctx.publishContentEventToVk(newItem, ctx.smartImageFile);
      const selectedPublicSocialLinkId = ctx.smartPlatforms[0];
      if (ctx.authToken && savedPost) {
        try {
          const syncedPost = await ctx.syncPublishedVkPost(savedPost.id, (newItem as any).vkPublicationId, selectedPublicSocialLinkId, vk);
          ctx.setContentEvents((prev: any[]) =>
            prev.map((item) =>
              item.id === newItem.id
                ? {
                    ...apiPostToContentEvent(syncedPost),
                    attachmentName: item.attachmentName,
                    attachmentDataUrl: item.attachmentDataUrl,
                    vkPublishError: undefined,
                  }
                : item
            )
          );
          await ctx.reloadCalendarFromBackend();
        } catch {
          try { await ctx.apiUpdatePostVk(ctx.authToken, savedPost.id, String(vk.postId)); } catch {}
        }
      }
      ctx.setContentEvents((prev: any[]) =>
        prev.map((item) =>
          item.id === newItem.id ? { ...item, vkWallUrl: vk.url, vkPostId: vk.postId, vkPublishError: undefined } : item
        )
      );
      ctx.setContentMessageType(MESSAGE_STATUS.SUCCESS);
      ctx.setContentMessage(
        shouldSchedule
          ? "Пост сохранен, запланирован в календаре и опубликован в VK."
          : "Сохранено и опубликовано в VK."
      );
    } catch (err) {
      const errorText =
        err instanceof Error ? err.message : "Ошибка VK (проверьте бэкенд: токен, группа, proxy).";
      ctx.setContentEvents((prev: any[]) =>
        prev.map((item) => (item.id === newItem.id ? { ...item, vkPublishError: errorText } : item))
      );
      ctx.setContentMessageType(MESSAGE_STATUS.ERROR);
      ctx.setContentMessage(`Сохранено, но VK не опубликовал: ${errorText}`);
    }
    ctx.setVkPublishing(false);
  } else {
    ctx.setContentMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setContentMessage(
      shouldSchedule
        ? "Пост сохранен в Контент и запланирован в календаре."
        : "Пост сохранен в Контент."
    );
  }
  ctx.closeSmartEvent();
}
