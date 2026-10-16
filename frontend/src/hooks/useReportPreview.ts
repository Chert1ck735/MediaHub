import { useQuery } from "@tanstack/react-query";

import { apiReportPreview } from "../api";
import type { ReportPeriod, ReportPlatform } from "../constants";
import { queryKeys } from "./queryKeys";

export function useReportPreview(
  token: string | null,
  platform: ReportPlatform,
  sourceId: string | null,
  period: ReportPeriod,
  municipalityName: string | null = null,
  enabled = false,
) {
  const supported = ["vk", "ok", "telegram"].includes(platform);
  return useQuery({
    queryKey: queryKeys.reportPreview(token, platform, sourceId, period, municipalityName),
    enabled: Boolean(token) && enabled && supported,
    queryFn: () =>
      apiReportPreview(token!, {
        platform,
        public_social_link_id: sourceId,
        municipality_name: municipalityName,
        period,
      }),
  });
}
