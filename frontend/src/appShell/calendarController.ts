import { apiCreateCalendarEvent, apiDeleteCalendarEvent, apiUpdateCalendarEvent, llmGenerate } from "../api";
import { DEFAULT_EVENT_SLOT_MS } from "../constants";
import { apiCalendarEventToCalendarEvent, focusCalendarOnDate } from "../app/mappers";
import { EVENT_STATUS, GENERATED_TEXT_MAX_LENGTH, MESSAGE_STATUS } from "../constants";
import {
  buildCalendarUrl,
  buildSeriesPlanItems,
  cleanGeneratedPostText,
  createClientId,
  localCalendarToUtcPayload,
  shiftDateTime,
  toInputDate,
} from "../app/utils";

export async function submitCalendarEvent(event: any, ctx: any) {
  event.preventDefault();
  if (!ctx.authToken) {
    ctx.setCalendarMessageType(MESSAGE_STATUS.ERROR);
    ctx.setCalendarMessage("Для работы с календарём нужно войти в аккаунт.");
    ctx.openAuth("login");
    return;
  }
  if (!ctx.eventTitle.trim() || !ctx.eventDate || !ctx.eventTime) {
    ctx.setCalendarMessageType(MESSAGE_STATUS.ERROR);
    ctx.setCalendarMessage("Введите корректные данные события.");
    return;
  }

  const title = ctx.eventTitle.trim();
  const startTime = ctx.eventTime;
  const start = new Date(`${ctx.eventDate}T${startTime}:00`);
  const end = new Date(start.getTime() + DEFAULT_EVENT_SLOT_MS);
  const endTime = `${String(end.getHours()).padStart(2, "0")}:${String(end.getMinutes()).padStart(2, "0")}`;
  const utcStart = localCalendarToUtcPayload(ctx.eventDate, startTime);
  const utcEnd = localCalendarToUtcPayload(ctx.eventDate, endTime);
  const desc = ctx.eventDescription.trim() || "Событие медиахаба";
  const publicSocialLinkIds = [...new Set((ctx.eventPlatforms as string[]).filter(Boolean))];

  if (publicSocialLinkIds.length === 0) {
    ctx.setCalendarMessageType(MESSAGE_STATUS.ERROR);
    ctx.setCalendarMessage("Выберите хотя бы один паблик.");
    return;
  }

  const seriesCount = !ctx.editingEventId && ctx.eventStatus === EVENT_STATUS.SCHEDULED
    ? Math.max(1, Math.min(30, Math.trunc(ctx.eventSeriesCount || 1)))
    : 1;
  const seriesStepMinutes = Math.max(1, Math.min(240, Math.trunc(ctx.eventSeriesStepMinutes || 5)));
  const seriesPlan = !ctx.editingEventId && ctx.eventStatus === EVENT_STATUS.SCHEDULED
    ? buildSeriesPlanItems(
        seriesCount,
        seriesStepMinutes,
        title,
        desc,
        ctx.eventPostType,
        ctx.eventSeriesItems,
      )
    : [];

  const generateDraftText = async (
    itemTitle: string,
    itemDesc: string,
    itemPostType: string,
    itemDate: string,
    index: number,
  ): Promise<string> => {
    if (ctx.editingEventId || ctx.eventStatus !== EVENT_STATUS.SCHEDULED) {
      return ctx.eventDraft.trim();
    }
    try {
      const llm = await llmGenerate(ctx.authToken, {
        public_social_link_id: publicSocialLinkIds[0],
        event_description: itemDesc,
        event_date: itemDate,
        post_type: itemPostType || undefined,
      });
      return cleanGeneratedPostText(llm.text).slice(0, GENERATED_TEXT_MAX_LENGTH);
    } catch {
      return cleanGeneratedPostText(
        [
          itemTitle,
          itemDesc,
          ctx.eventTone.trim() ? `Тон: ${ctx.eventTone.trim()}.` : "",
          seriesCount > 1 ? `Это публикация ${index + 1} из ${seriesCount}.` : "",
          "Поделитесь мнением в комментариях.",
        ].filter(Boolean).join("\n\n"),
      ).slice(0, GENERATED_TEXT_MAX_LENGTH);
    }
  };

  try {
    ctx.setCalendarGenerating(true);
    ctx.setCalendarGenerationProgress(0);

    if (ctx.editingEventId) {
      const res = await apiUpdateCalendarEvent(ctx.authToken, ctx.editingEventId, {
        title,
        date: utcStart.date,
        description: desc,
        start_time: utcStart.time,
        end_time: utcEnd.time,
        status: ctx.eventStatus,
        platforms: [],
        public_social_link_ids: publicSocialLinkIds,
        draft: ctx.eventDraft.trim(),
        tone: ctx.eventTone.trim(),
        post_type: ctx.eventPostType,
        info_event_id: ctx.eventInfoEventId,
      });
      const saved = apiCalendarEventToCalendarEvent(res);
      focusCalendarOnDate(saved.date, ctx.setSelectedDay, ctx.setCalendarDate);
      await ctx.reloadCalendarFromBackend();
      await ctx.reloadContentFromBackend();
    } else {
      const createdCalendarEvents: any[] = [];
      for (let index = 0; index < seriesCount; index += 1) {
        ctx.setCalendarGenerationProgress(index + 1);
        const planItem = seriesPlan[index] ?? {
          id: createClientId(),
          index,
          title: seriesCount > 1 ? `${title} · ${index + 1}/${seriesCount}` : title,
          description: desc,
          postType: ctx.eventPostType,
          offsetMinutes: index * seriesStepMinutes,
        };
        const itemTitle = (planItem.title || title).trim();
        const itemDesc = (planItem.description || desc).trim();
        const itemPostType = planItem.postType || ctx.eventPostType;
        const shifted = shiftDateTime(ctx.eventDate, startTime, planItem.offsetMinutes);
        const itemDate = shifted.date;
        const itemStartTime = shifted.time;
        const itemStart = new Date(`${itemDate}T${itemStartTime}:00`);
        const itemEnd = new Date(itemStart.getTime() + DEFAULT_EVENT_SLOT_MS);
        const itemEndTime = `${String(itemEnd.getHours()).padStart(2, "0")}:${String(itemEnd.getMinutes()).padStart(2, "0")}`;
        const utcItemStart = localCalendarToUtcPayload(itemDate, itemStartTime);
        const utcItemEnd = localCalendarToUtcPayload(itemDate, itemEndTime);
        const generatedDraft = await generateDraftText(itemTitle, itemDesc, itemPostType, itemDate, index);

        const createdEvent = await apiCreateCalendarEvent(ctx.authToken, {
          title: itemTitle,
          date: utcItemStart.date,
          description: itemDesc,
          start_time: utcItemStart.time,
          end_time: utcItemEnd.time,
          status: ctx.eventStatus,
          platforms: [],
          public_social_link_ids: publicSocialLinkIds,
          draft: generatedDraft,
          tone: ctx.eventTone.trim(),
          post_type: itemPostType,
          info_event_id: ctx.eventInfoEventId,
        });
        createdCalendarEvents.push(apiCalendarEventToCalendarEvent(createdEvent));
      }

      if (createdCalendarEvents[0]) {
        focusCalendarOnDate(createdCalendarEvents[0].date, ctx.setSelectedDay, ctx.setCalendarDate);
      }
      await ctx.reloadCalendarFromBackend();
      await ctx.reloadContentFromBackend();
    }

    if (!ctx.editingEventId) {
      const url = buildCalendarUrl(title, ctx.eventDate, ctx.eventTime);
      window.open(url, "_blank", "noopener,noreferrer");
    }

    ctx.setCalendarMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setCalendarMessage(ctx.editingEventId ? "Событие обновлено." : "События созданы и открыты в календаре.");
    ctx.setCalendarModalOpen(false);
    ctx.setEditingEventId(null);
  } catch (err) {
    ctx.setCalendarMessageType(MESSAGE_STATUS.ERROR);
    ctx.setCalendarMessage(err instanceof Error ? err.message : "Ошибка при сохранении события");
  } finally {
    ctx.setCalendarGenerating(false);
  }
}

export async function removeCalendarEvent(id: string, ctx: any) {
  const previousEvents = ctx.events;
  const previousContent = ctx.contentEvents;
  const targetEvent = ctx.events.find((event: any) => event.id === id);
  const targetPostId = targetEvent?.postId ?? id;
  ctx.deletedPostIdsRef.current.add(targetPostId);
  ctx.calendarReloadSeqRef.current += 1;
  ctx.contentReloadSeqRef.current += 1;
  ctx.setEvents((prev: any[]) => prev.filter((event) => (event.postId ?? event.id) !== targetPostId));
  ctx.setContentEvents((prev: any[]) => prev.filter((content) => content.id !== targetPostId));

  try {
    await apiDeleteCalendarEvent(ctx.authToken, targetPostId);
  } catch (err) {
    ctx.deletedPostIdsRef.current.delete(targetPostId);
    ctx.setEvents(previousEvents);
    ctx.setContentEvents(previousContent);
    ctx.setCalendarMessageType(MESSAGE_STATUS.ERROR);
    ctx.setCalendarMessage(err instanceof Error ? err.message : "Ошибка при удалении события");
  }
}

export function openEditCalendarEvent(eventItem: any, ctx: any) {
  ctx.setEditingEventId(eventItem.postId ?? eventItem.id);
  ctx.setEventTitle(eventItem.title);
  ctx.setEventDate(eventItem.date);
  ctx.setEventTime(eventItem.startTime);
  ctx.setEventDescription(eventItem.description);
  ctx.setEventStatus(eventItem.status);
  ctx.setEventPlatforms(eventItem.publicSocialLinkIds ?? []);
  ctx.setEventDraft(eventItem.draft ?? "");
  ctx.setEventTone(eventItem.tone ?? "");
  ctx.setEventPostType(eventItem.postType ?? "");
  ctx.setEventInfoEventId(eventItem.infoEventId ?? null);
  ctx.setEventSeriesCount(1);
  ctx.setEventSeriesStepMinutes(5);
  ctx.setEventSeriesItems([]);
  ctx.setCalendarModalOpen(true);
}

export function shiftCalendarPeriod(dir: 1 | -1, ctx: any) {
  const nextDate = new Date(ctx.calendarDate);
  if (ctx.calendarView === "month") {
    nextDate.setDate(1);
    nextDate.setMonth(nextDate.getMonth() + dir);
  } else {
    nextDate.setDate(nextDate.getDate() + 7 * dir);
  }
  ctx.setCalendarDate(nextDate);
  ctx.setSelectedDay(toInputDate(nextDate));
}

