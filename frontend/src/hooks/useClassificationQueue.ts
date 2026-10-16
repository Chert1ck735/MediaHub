import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  apiClassificationQueue,
  apiPauseWorker,
  apiResumeWorker,
  type ClassificationQueue,
} from "../api";
import { queryKeys } from "./queryKeys";

const POLL_MS = 3000;

export type ClassificationQueueState = {
  queue: ClassificationQueue | null;
  toggleWorker: () => void;
  setQueue: (updater: (prev: ClassificationQueue | null) => ClassificationQueue | null) => void;
};

/** Очередь классификации: поллинг серверных метрик и пауза воркера.
 *
 *  Живёт на react-query, поэтому сайдбар и страница аналитики делят один
 *  запрос — сколько бы компонентов хук ни вызвало, поллер остаётся один.
 */
export function useClassificationQueue(token: string | null): ClassificationQueueState {
  const queryClient = useQueryClient();
  const queryKey = queryKeys.classificationQueue(token);

  const { data } = useQuery({
    queryKey,
    enabled: Boolean(token),
    queryFn: () => apiClassificationQueue(token!),
    refetchInterval: POLL_MS,
  });

  const queue = data ?? null;

  const setQueue = useCallback(
    (updater: (prev: ClassificationQueue | null) => ClassificationQueue | null) => {
      queryClient.setQueryData<ClassificationQueue>(queryKey, (prev) =>
        (updater(prev ?? null) ?? undefined) as ClassificationQueue | undefined,
      );
    },
    [queryClient, queryKey],
  );

  const toggleWorker = useCallback(() => {
    if (!token || !queue) return;
    const call = queue.paused ? apiResumeWorker : apiPauseWorker;
    call(token)
      .then((r) => setQueue((prev) => (prev ? { ...prev, paused: r.paused } : prev)))
      .catch(() => {});
  }, [token, queue, setQueue]);

  return { queue, toggleWorker, setQueue };
}
