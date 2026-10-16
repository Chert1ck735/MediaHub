import { useQuery } from "@tanstack/react-query";

import { apiGetPosts } from "../api";
import { queryKeys } from "./queryKeys";

export function usePosts(token: string | null) {
  return useQuery({
    queryKey: queryKeys.posts(token),
    enabled: Boolean(token),
    queryFn: () => apiGetPosts(token!),
  });
}
