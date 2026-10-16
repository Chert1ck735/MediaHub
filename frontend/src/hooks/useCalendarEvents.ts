import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { apiGetCalendarEvents } from "../api";
import { queryKeys } from "./queryKeys";

export function useCalendarEvents(
  token: string | null,
  dateFrom: string | null = null,
  dateTo: string | null = null,
  perDay: number | null = null,
  publicIds: string[] = [],
) {
  const publicsKey = [...publicIds].sort().join(",");
  return useQuery({
    queryKey: queryKeys.calendarEvents(token, dateFrom, dateTo, perDay, publicsKey),
    enabled: Boolean(token && dateFrom && dateTo),
    queryFn: ({ signal }) => apiGetCalendarEvents(token!, dateFrom, dateTo, perDay, publicIds, undefined, signal),
  });
}

export function useCalendarDayEvents(
  token: string | null, dateFrom: string | null, dateTo: string | null, publicIds: string[] = [],
) {
  const limit = 50;
  return useInfiniteQuery({
    queryKey: [...queryKeys.calendarEvents(token, dateFrom, dateTo, null, [...publicIds].sort().join(",")), "pages"],
    enabled: Boolean(token && dateFrom && dateTo),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => apiGetCalendarEvents(
      token!, dateFrom, dateTo, null, publicIds, { limit, offset: pageParam }, signal,
    ),
    getNextPageParam: (lastPage, pages) => {
      const loaded = pages.reduce((sum, page) => sum + page.length, 0);
      return lastPage.length && loaded < (lastPage[0]?.day_total ?? 0) ? loaded : undefined;
    },
  });
}
