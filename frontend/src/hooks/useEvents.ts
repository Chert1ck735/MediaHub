import { useQuery } from "@tanstack/react-query";

import { apiGetEvents } from "../api";
import { queryKeys } from "./queryKeys";

export function useEvents(token: string | null) {
  return useQuery({
    queryKey: queryKeys.events(token),
    enabled: Boolean(token),
    queryFn: () => apiGetEvents(token!),
  });
}
