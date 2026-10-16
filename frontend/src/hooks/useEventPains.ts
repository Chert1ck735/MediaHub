import { useQuery } from "@tanstack/react-query";

import { apiGetEventPains } from "../api";
import { queryKeys } from "./queryKeys";

export function useEventPains(token: string | null, eventId: string | null) {
  return useQuery({
    queryKey: queryKeys.eventPains(token, eventId),
    enabled: Boolean(token && eventId),
    queryFn: () => apiGetEventPains(token!, eventId!),
  });
}
