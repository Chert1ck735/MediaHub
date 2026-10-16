import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGetPainDetail } from "../api";
import { queryKeys } from "./queryKeys";

export function usePainDetail(
  token: string | null,
  painId: string | null,
  sourceId: string | null,
  period: string,
  municipalityName: string | null = null,
) {
  return useQuery({
    queryKey: queryKeys.painDetail(token, painId, sourceId, period, municipalityName),
    enabled: Boolean(token && painId),
    queryFn: () => apiGetPainDetail(token!, painId!, sourceId, period, municipalityName),
    placeholderData: keepPreviousData,
  });
}
