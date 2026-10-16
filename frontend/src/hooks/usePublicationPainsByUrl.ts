import { useQuery } from "@tanstack/react-query";

import { apiGetPublicationPainsByUrl } from "../api";
import { queryKeys } from "./queryKeys";

export function usePublicationPainsByUrl(
  token: string | null,
  url: string | null,
  enabled = false,
) {
  return useQuery({
    queryKey: queryKeys.publicationPainsByUrl(token, url),
    enabled: Boolean(token && url && enabled),
    queryFn: () => apiGetPublicationPainsByUrl(token!, url!),
  });
}
