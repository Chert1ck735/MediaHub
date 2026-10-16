import { useQuery } from "@tanstack/react-query";

import { apiGetModules } from "../api";
import { queryKeys } from "./queryKeys";

export function useModules(token: string | null) {
  return useQuery({
    queryKey: queryKeys.modules(token),
    enabled: Boolean(token),
    queryFn: () => apiGetModules(token!),
  });
}
