import { useQuery } from "@tanstack/react-query";

import { apiGetPainEvents } from "../api";
import { queryKeys } from "./queryKeys";

export function usePainEvents(token: string | null, painId: string | null) {
  return useQuery({
    queryKey: queryKeys.painEvents(token, painId),
    enabled: Boolean(token && painId),
    queryFn: () => apiGetPainEvents(token!, painId!),
  });
}
