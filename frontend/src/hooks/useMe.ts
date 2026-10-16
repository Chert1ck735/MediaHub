import { useQuery } from "@tanstack/react-query";

import { apiGetMe } from "../api";
import { queryKeys } from "./queryKeys";

export function useMe(token: string | null) {
  return useQuery({
    queryKey: queryKeys.me(token),
    enabled: Boolean(token),
    queryFn: () => apiGetMe(token!),
  });
}
