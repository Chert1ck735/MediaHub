import { useInfiniteQuery } from "@tanstack/react-query";

import { apiListPainComments } from "../api";
import { PAIN_COMMENTS_PAGE_SIZE } from "../constants";
import { queryKeys } from "./queryKeys";

type UsePainCommentsOptions = {
  subcategory?: string | null;
  sourceId?: string | null;
  municipalityName?: string | null;
  period?: string | null;
  limit?: number;
};

export function usePainComments(
  token: string | null,
  painId: string | null,
  {
    subcategory = null,
    sourceId = null,
    municipalityName = null,
    period = "all",
    limit = PAIN_COMMENTS_PAGE_SIZE,
  }: UsePainCommentsOptions = {},
) {
  return useInfiniteQuery({
    queryKey: queryKeys.painComments(
      token,
      painId,
      subcategory,
      sourceId,
      period ?? "all",
      limit,
      municipalityName,
    ),
    enabled: Boolean(token && painId),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      apiListPainComments(token!, painId!, {
        subcategory,
        sourceId,
        municipalityName,
        period,
        limit,
        offset: pageParam,
      }),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });
}
