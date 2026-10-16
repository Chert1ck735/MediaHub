import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGetPainList } from "../api";
import { queryKeys } from "./queryKeys";

export function usePainList(
  token: string | null,
  period: string,
  sourceId: string | null,
  municipalityName: string | null = null,
) {
  return useQuery({
    queryKey: queryKeys.painList(token, period, sourceId, municipalityName),
    enabled: Boolean(token),
    queryFn: () => apiGetPainList(token!, period, sourceId, municipalityName),
    placeholderData: keepPreviousData,
  });
}
