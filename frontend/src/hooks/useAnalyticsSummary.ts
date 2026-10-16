import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGetAnalyticsSummary } from "../api";
import { queryKeys } from "./queryKeys";

export function useAnalyticsSummary(
  token: string | null,
  period: string,
  sourceId: string | null,
  municipalityName: string | null = null,
) {
  return useQuery({
    queryKey: queryKeys.analyticsSummary(token, period, sourceId, municipalityName),
    enabled: Boolean(token),
    queryFn: () => apiGetAnalyticsSummary(token!, period, sourceId, municipalityName),
    placeholderData: keepPreviousData,
  });
}
