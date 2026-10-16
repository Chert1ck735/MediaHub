import { useQuery } from "@tanstack/react-query";

import { apiGetAlerts } from "../api";
import { queryKeys } from "./queryKeys";

export function useAlerts(token: string | null, sourceId: string | null = null) {
  return useQuery({
    queryKey: queryKeys.alerts(token, sourceId),
    enabled: Boolean(token),
    queryFn: () => apiGetAlerts(token!, sourceId),
  });
}
