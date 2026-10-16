import { useMemo, useState } from "react";
import { apiGetCalendarEvent } from "../../api";
import { apiCalendarEventToCalendarEvent } from "../../app/mappers";

import { startOfWeek } from "../../app/utils";
import { CALENDAR_VIEW } from "../../constants";
import { CalendarPage } from "../../pages/CalendarPage";
import { useAppShellContext } from "../AppShellContext";
import {
  openEditCalendarEvent,
  removeCalendarEvent,
  shiftCalendarPeriod,
} from "../calendarController";
import { openSmartEventAction } from "../smartEventController";

export function CalendarRoute() {
  const { shellState, shellData, openAuth, reloadCalendarFromBackend } = useAppShellContext();
  const [actionError, setActionError] = useState("");

  const eventsByDate = useMemo(() => {
    const map = new Map<string, typeof shellState.events>();
    for (const eventItem of shellState.events) {
      if (
        shellState.deletedPostIdsRef.current.has(eventItem.postId ?? eventItem.id) ||
        shellState.deletedPostIdsRef.current.has(eventItem.id)
      ) {
        continue;
      }
      const list = map.get(eventItem.date) ?? [];
      list.push(eventItem);
      map.set(eventItem.date, list);
    }
    for (const list of map.values()) {
      list.sort((left, right) => left.startTime.localeCompare(right.startTime));
    }
    return map;
  }, [shellState.deletedPostIdsRef, shellState.events]);

  const monthCells = useMemo(() => {
    const first = new Date(
      shellState.calendarDate.getFullYear(),
      shellState.calendarDate.getMonth(),
      1,
    );
    const start = startOfWeek(first);
    const cells: Date[] = [];
    for (let index = 0; index < 42; index += 1) {
      const day = new Date(start);
      day.setDate(start.getDate() + index);
      cells.push(day);
    }
    return cells;
  }, [shellState.calendarDate]);

  const weekDays = useMemo(() => {
    const start = startOfWeek(shellState.calendarDate);
    return Array.from({ length: 7 }, (_, index) => {
      const day = new Date(start);
      day.setDate(start.getDate() + index);
      return day;
    });
  }, [shellState.calendarDate]);

  const periodLabel = useMemo(() => {
    if (shellState.calendarView === CALENDAR_VIEW.MONTH) {
      return shellState.calendarDate.toLocaleDateString("ru-RU", {
        month: "long",
        year: "numeric",
      });
    }
    const start = weekDays[0];
    const end = weekDays[6];
    return `${start.toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "short",
    })} - ${end.toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })}`;
  }, [shellState.calendarDate, shellState.calendarView, weekDays]);

  const selectedEvents = shellData.calendarDayEvents
    .filter((event) => !shellState.deletedPostIdsRef.current.has(event.post_id ?? event.id))
    .map(apiCalendarEventToCalendarEvent);

  const openEditEvent = async (eventItem: any) => {
    setActionError("");
    try {
      const fullEvent = await apiGetCalendarEvent(shellState.authToken, eventItem.postId ?? eventItem.id);
      openEditCalendarEvent(apiCalendarEventToCalendarEvent(fullEvent), {
      setEditingEventId: shellState.setEditingEventId,
      setEventTitle: shellState.setEventTitle,
      setEventDate: shellState.setEventDate,
      setEventTime: shellState.setEventTime,
      setEventDescription: shellState.setEventDescription,
      setEventStatus: shellState.setEventStatus,
      setEventPlatforms: shellState.setEventPlatforms,
      setEventDraft: shellState.setEventDraft,
      setEventTone: shellState.setEventTone,
      setEventPostType: shellState.setEventPostType,
      setEventInfoEventId: shellState.setEventInfoEventId,
      setEventSeriesCount: shellState.setEventSeriesCount,
      setEventSeriesStepMinutes: shellState.setEventSeriesStepMinutes,
      setEventSeriesItems: shellState.setEventSeriesItems,
      setCalendarModalOpen: shellState.setCalendarModalOpen,
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось открыть публикацию");
    }
  };

  const openSchedulePost = (date?: string, time = "10:00") =>
    openSmartEventAction(
      null,
      { entryMode: "calendar", scheduleDate: date, scheduleTime: time },
      {
        selectedDay: shellState.selectedDay,
        defaultVkPublicLinkId: shellData.defaultVkPublicLinkId,
        smartFileInputRef: shellState.smartFileInputRef,
        setSmartEntryMode: shellState.setSmartEntryMode,
        setSmartSourceEventId: shellState.setSmartSourceEventId,
        setSmartTitle: shellState.setSmartTitle,
        setSmartPrompt: shellState.setSmartPrompt,
        setSmartEventDate: shellState.setSmartEventDate,
        setSmartTone: shellState.setSmartTone,
        setSmartPostType: shellState.setSmartPostType,
        setSmartPlatforms: shellState.setSmartPlatforms,
        setSmartScheduleEnabled: shellState.setSmartScheduleEnabled,
        setSmartScheduleDate: shellState.setSmartScheduleDate,
        setSmartScheduleTime: shellState.setSmartScheduleTime,
        setSmartGenerated: shellState.setSmartGenerated,
        setSmartPainId: shellState.setSmartPainId,
        setSmartStrategyId: shellState.setSmartStrategyId,
        setSmartPainDetail: shellState.setSmartPainDetail,
        setSmartMessage: shellState.setSmartMessage,
        setSmartMessageType: shellState.setSmartMessageType,
        setSmartImageFile: shellState.setSmartImageFile,
        setSmartImagePreview: shellState.setSmartImagePreview,
        setPublishToVk: shellState.setPublishToVk,
        setVkPublishing: shellState.setVkPublishing,
        setSmartEventOpen: shellState.setSmartEventOpen,
      },
    );

  const removeEvent = async (id: string) => {
    await removeCalendarEvent(id, {
      authToken: shellState.authToken,
      events: shellState.events,
      contentEvents: shellState.contentEvents,
      deletedPostIdsRef: shellState.deletedPostIdsRef,
      calendarReloadSeqRef: shellState.calendarReloadSeqRef,
      contentReloadSeqRef: shellState.contentReloadSeqRef,
      setEvents: shellState.setEvents,
      setContentEvents: shellState.setContentEvents,
      setCalendarMessageType: shellState.setCalendarMessageType,
      setCalendarMessage: shellState.setCalendarMessage,
    });
    await reloadCalendarFromBackend();
  };

  const shiftPeriod = (dir: 1 | -1) =>
    shiftCalendarPeriod(dir, {
      calendarDate: shellState.calendarDate,
      calendarView: shellState.calendarView,
      setCalendarDate: shellState.setCalendarDate,
      setSelectedDay: shellState.setSelectedDay,
    });

  return (
    <CalendarPage
      authToken={shellState.authToken}
      calendarDate={shellState.calendarDate}
      calendarView={shellState.calendarView}
      dataLoading={shellData.calendarPageLoading}
      dataFetching={shellData.calendarFetching}
      dayLoading={shellData.calendarDayQuery.isLoading}
      error={actionError || (shellState.calendarMessageType === "error" ? shellState.calendarMessage : "") || (shellData.calendarEventsQuery.isError ? "Не удалось загрузить календарь." : "")}
      dayError={shellData.calendarDayQuery.isError ? "Не удалось загрузить публикации дня." : ""}
      retry={() => { setActionError(""); void shellData.calendarEventsQuery.refetch(); void shellData.calendarDayQuery.refetch(); }}
      hasMore={shellData.calendarDayQuery.hasNextPage}
      loadingMore={shellData.calendarDayQuery.isFetchingNextPage}
      loadMore={() => { void shellData.calendarDayQuery.fetchNextPage(); }}
      eventsByDate={eventsByDate}
      monthCells={monthCells}
      openAuth={openAuth}
      openEditEvent={openEditEvent}
      openSchedulePost={openSchedulePost}
      periodLabel={periodLabel}
      removeEvent={removeEvent}
      selectedDay={shellState.selectedDay}
      selectedEvents={selectedEvents}
      selectedPublicIds={shellState.selectedPublicIds}
      setSelectedPublicIds={shellState.setSelectedPublicIds}
      publicationTargetOptions={shellData.publicationTargetOptions}
      setCalendarDate={shellState.setCalendarDate}
      setCalendarView={shellState.setCalendarView}
      setSelectedDay={shellState.setSelectedDay}
      shiftPeriod={shiftPeriod}
      weekDays={weekDays}
    />
  );
}
