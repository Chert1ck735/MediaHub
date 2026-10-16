import { useQuery } from "@tanstack/react-query";

import { apiReportRecommendations } from "../api";
import type { ReportPeriod, ReportPlatform } from "../constants";
import { queryKeys } from "./queryKeys";

export function useReportRecommendations(
  token: string | null,
  platform: ReportPlatform,
  sourceId: string | null,
  period: ReportPeriod,
  municipalityName: string | null = null,
  enabled = false,
) {
  const supported = ["vk", "ok", "telegram"].includes(platform);
  return useQuery({
    queryKey: queryKeys.reportRecommendations(token, platform, sourceId, period, municipalityName),
    enabled: Boolean(token) && enabled && supported,
    staleTime: 1000 * 60 * 30,
    queryFn: () =>
      apiReportRecommendations(token!, {
        platform,
        public_social_link_id: sourceId,
        municipality_name: municipalityName,
        period,
      }),
  });
}
