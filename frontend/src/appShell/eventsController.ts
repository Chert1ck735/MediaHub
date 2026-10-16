import { apiCreateEventEntry, apiDeleteEventEntry, apiImportEventsFile, apiLinkEventPains, apiUnlinkEventPain, apiUpdateEventEntry } from "../api";
import { MESSAGE_STATUS } from "../constants";

export async function submitInfoEvent(event: any, ctx: any) {
  event.preventDefault();
  if (!ctx.authToken) {
    ctx.openAuth("login");
    return;
  }
  if (!ctx.infoEventForm.title.trim()) {
    ctx.setInfoEventMessageType(MESSAGE_STATUS.ERROR);
    ctx.setInfoEventMessage("Укажите название события.");
    return;
  }

  ctx.setInfoEventCreating(true);
  ctx.setInfoEventMessage("");
  ctx.setInfoEventMessageType(MESSAGE_STATUS.IDLE);
  try {
    const payload = {
      title: ctx.infoEventForm.title.trim(),
      event_date: ctx.infoEventForm.eventDate,
      description: ctx.infoEventForm.description.trim() || null,
      location: ctx.infoEventForm.location.trim() || null,
    };
    if (ctx.editingInfoEventId) {
      const updated = await apiUpdateEventEntry(ctx.authToken, ctx.editingInfoEventId, payload);
      ctx.setInfoEvents((prev: any[]) => prev.map((item) => (item.id === updated.id ? updated : item)));
      ctx.setSelectedInfoEventId(updated.id);
      await ctx.queryClient.invalidateQueries({ queryKey: ctx.queryKeys.events(ctx.authToken) });
      ctx.setInfoEventMessageType(MESSAGE_STATUS.SUCCESS);
      ctx.setInfoEventMessage("Событие обновлено.");
    } else {
      const item = await apiCreateEventEntry(ctx.authToken, payload);
      ctx.setInfoEvents((prev: any[]) => [item, ...prev]);
      ctx.setSelectedInfoEventId(item.id);
      await ctx.queryClient.invalidateQueries({ queryKey: ctx.queryKeys.events(ctx.authToken) });
      ctx.setInfoEventMessageType(MESSAGE_STATUS.SUCCESS);
      ctx.setInfoEventMessage("Событие добавлено.");
    }
    ctx.setInfoEventForm(ctx.defaultInfoEventForm());
    ctx.setEditingInfoEventId(null);
    ctx.setInfoEventModalOpen(false);
  } catch (err) {
    ctx.setInfoEventMessageType(MESSAGE_STATUS.ERROR);
    ctx.setInfoEventMessage(
      err instanceof Error
        ? err.message
        : ctx.editingInfoEventId
          ? "Не удалось обновить событие"
          : "Не удалось добавить событие",
    );
  } finally {
    ctx.setInfoEventCreating(false);
  }
}

export function openCreateInfoEventModalAction(ctx: any) {
  if (!ctx.authToken) {
    ctx.openAuth("login");
    return;
  }
  ctx.setInfoEventMessage("");
  ctx.setInfoEventMessageType(MESSAGE_STATUS.IDLE);
  ctx.setInfoEventForm(ctx.defaultInfoEventForm());
  ctx.setEditingInfoEventId(null);
  ctx.setInfoEventModalOpen(true);
}

export function openEditInfoEventModalAction(eventItem: any, ctx: any) {
  if (!ctx.authToken) {
    ctx.openAuth("login");
    return;
  }
  ctx.setInfoEventMessage("");
  ctx.setInfoEventMessageType(MESSAGE_STATUS.IDLE);
  ctx.setInfoEventForm({
    title: eventItem.title,
    eventDate: eventItem.event_date.slice(0, 10),
    location: eventItem.location ?? "",
    description: eventItem.description ?? "",
  });
  ctx.setEditingInfoEventId(eventItem.id);
  ctx.setInfoEventModalOpen(true);
}

export async function importInfoEventsAction(event: any, ctx: any) {
  const file = event.target.files?.[0];
  if (!file || !ctx.authToken) return;
  ctx.setInfoEventsImporting(true);
  ctx.setInfoEventMessage("");
  ctx.setInfoEventMessageType(MESSAGE_STATUS.IDLE);
  try {
    const result = await apiImportEventsFile(ctx.authToken, file);
    ctx.setInfoEvents((prev: any[]) => [...result.items, ...prev]);
    ctx.setSelectedInfoEventId((prev: any) => prev ?? result.items[0]?.id ?? null);
    await ctx.queryClient.invalidateQueries({ queryKey: ctx.queryKeys.events(ctx.authToken) });
    ctx.setInfoEventMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setInfoEventMessage(`Импортировано: ${result.imported_count}`);
  } catch (err) {
    ctx.setInfoEventMessageType(MESSAGE_STATUS.ERROR);
    ctx.setInfoEventMessage(err instanceof Error ? err.message : "Не удалось импортировать файл");
  } finally {
    event.target.value = "";
    ctx.setInfoEventsImporting(false);
  }
}

export async function deleteInfoEventAction(eventId: string, ctx: any) {
  if (!ctx.authToken) {
    ctx.openAuth("login");
    return;
  }
  const previousEvents = ctx.infoEvents;
  const currentIndex = ctx.infoEvents.findIndex((item: any) => item.id === eventId);
  const fallbackSelection = ctx.infoEvents[currentIndex + 1]?.id ?? ctx.infoEvents[currentIndex - 1]?.id ?? null;
  ctx.setInfoEvents((prev: any[]) => prev.filter((item) => item.id !== eventId));
  ctx.setSelectedInfoEventId((prev: any) => (prev === eventId ? fallbackSelection : prev));
  try {
    await apiDeleteEventEntry(ctx.authToken, eventId);
    await ctx.queryClient.invalidateQueries({ queryKey: ctx.queryKeys.events(ctx.authToken) });
    ctx.setInfoEventMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setInfoEventMessage("Событие удалено.");
  } catch (err) {
    ctx.setInfoEvents(previousEvents);
    ctx.setSelectedInfoEventId(eventId);
    ctx.setInfoEventMessageType(MESSAGE_STATUS.ERROR);
    ctx.setInfoEventMessage(err instanceof Error ? err.message : "Не удалось удалить событие");
  }
}

export async function linkPainToEventAction(painId: string, ctx: any) {
  if (!ctx.authToken || !ctx.selectedInfoEventId) return;
  try {
    await apiLinkEventPains(ctx.authToken, ctx.selectedInfoEventId, [painId]);
    await ctx.queryClient.invalidateQueries({ queryKey: ctx.queryKeys.eventPains(ctx.authToken, ctx.selectedInfoEventId) });
    ctx.setEventPainPickerOpen(false);
  } catch {}
}

export async function unlinkPainFromEventAction(painId: string, ctx: any) {
  if (!ctx.authToken || !ctx.selectedInfoEventId) return;
  try {
    await apiUnlinkEventPain(ctx.authToken, ctx.selectedInfoEventId, painId);
    await ctx.queryClient.invalidateQueries({ queryKey: ctx.queryKeys.eventPains(ctx.authToken, ctx.selectedInfoEventId) });
  } catch {}
}

