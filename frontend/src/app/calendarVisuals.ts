import type { CalendarEvent } from "./types";

export type CalendarPublicOption = {
  id: string;
  label: string;
};

export type CalendarLegendItem = CalendarPublicOption & {
  className: string;
};

const PUBLIC_EVENT_CLASSES = [
  "calendar-event-public-1",
  "calendar-event-public-2",
  "calendar-event-public-3",
  "calendar-event-public-4",
  "calendar-event-public-5",
  "calendar-event-public-6",
];

export function buildCalendarLegend(publicOptions: CalendarPublicOption[]): CalendarLegendItem[] {
  return publicOptions.map((item, index) => ({
    ...item,
    className: PUBLIC_EVENT_CLASSES[index % PUBLIC_EVENT_CLASSES.length],
  }));
}

export function calendarEventClass(
  eventItem: CalendarEvent,
  legendItems: CalendarLegendItem[],
): string {
  const firstPublicId = eventItem.publicSocialLinkIds?.[0];
  const publicClass = firstPublicId
    ? legendItems.find((item) => item.id === firstPublicId)?.className
    : null;

  if (publicClass) return publicClass;
  return eventItem.origin === "parsed" ? "calendar-event-parsed" : "calendar-event-system";
}

/** Фильтр по пабликам — список выбранных id. Пустой список = «все паблики». */
export function calendarEventMatchesPublic(
  eventItem: CalendarEvent,
  publicIds: readonly string[],
): boolean {
  if (!publicIds.length) return true;
  return Boolean(eventItem.publicSocialLinkIds?.some((id) => publicIds.includes(id)));
}

export function calendarEventPublicationUrl(
  eventItem: CalendarEvent,
  publicIds: readonly string[],
): string | null {
  // Ссылку берём у первого выбранного паблика, который реально есть у события,
  // иначе — первую доступную.
  for (const publicId of publicIds) {
    const index = eventItem.publicSocialLinkIds?.indexOf(publicId) ?? -1;
    if (index >= 0) {
      const url = eventItem.publicationUrls?.[index];
      if (url) return url;
    }
  }

  return eventItem.publicationUrls?.find((url): url is string => Boolean(url)) ?? null;
}

export function calendarEventCompactTitle(
  eventItem: CalendarEvent,
  publicIds: readonly string[],
): string {
  // Когда фильтр включён, событий в ячейке меньше — можно показать заголовок целиком.
  if (publicIds.length) return eventItem.title;
  return eventItem.title.trim().slice(0, 9);
}
