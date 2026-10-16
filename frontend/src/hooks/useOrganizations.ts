import { useQuery } from "@tanstack/react-query";

import { apiGetVkPublics } from "../api";
import { queryKeys } from "./queryKeys";

export function useOrganizations(token: string | null) {
  return useQuery({
    queryKey: queryKeys.organizations(token),
    enabled: Boolean(token),
    queryFn: () => apiGetVkPublics(token!),
  });
}
