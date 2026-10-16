import { useQuery } from "@tanstack/react-query";

import { apiGetVkDefaultPublic } from "../api";
import { queryKeys } from "./queryKeys";

export function useDefaultVkPublic(token: string | null) {
  return useQuery({
    queryKey: queryKeys.defaultVkPublic(token),
    enabled: Boolean(token),
    queryFn: () => apiGetVkDefaultPublic(token!),
  });
}
