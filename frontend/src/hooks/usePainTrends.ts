import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGetPainTrends } from "../api";
import { REPORT_PERIOD } from "../constants";
import { queryKeys } from "./queryKeys";

export function usePainTrends(
  token: string | null,
  period: string,
  sourceId: string | null,
  municipalityName: string | null = null,
) {
  const trendPeriod = period === REPORT_PERIOD.ALL ? REPORT_PERIOD.MONTH : period;

  return useQuery({
    queryKey: queryKeys.painTrends(token, trendPeriod, sourceId, municipalityName),
    enabled: Boolean(token),
    queryFn: () => apiGetPainTrends(token!, trendPeriod, sourceId, municipalityName),
    placeholderData: keepPreviousData,
  });
}
