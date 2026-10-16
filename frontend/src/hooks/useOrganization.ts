/** Серверное состояние настроек организации.
 *
 *  Всё через TanStack Query, а не useEffect+useState: список пользователей
 *  перезапрашивается при каждом изменении фильтра, и самодельный фетч ловил бы
 *  классическую гонку — старый ответ приходит последним и затирает новый.
 *
 *  После любой мутации инвалидируем затронутые ключи: права зависят от групп,
 *  а счётчик доступных сообществ у пользователя — от прав, поэтому изменение
 *  группы обязано освежить и список пользователей.
 */
import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "../api/organization";

const keys = {
  organizations: () => ["organizations"] as const,
  regions: () => ["regions"] as const,
  users: (orgId: string, filters: api.UserFilters) =>
    ["org", orgId, "users", filters] as const,
  userGroups: (orgId: string) => ["org", orgId, "user-groups"] as const,
  userGroupMembers: (orgId: string, groupId: string) =>
    ["org", orgId, "user-groups", groupId, "members"] as const,
  communities: (orgId: string) => ["org", orgId, "communities"] as const,
  dataHealth: (orgId: string) => ["org", orgId, "data-health"] as const,
  communityGroups: (orgId: string) => ["org", orgId, "community-groups"] as const,
  communityGroupMembers: (orgId: string, groupId: string) =>
    ["org", orgId, "community-groups", groupId, "communities"] as const,
  grants: (orgId: string, subjectType: string, subjectId: string) =>
    ["org", orgId, "grants", subjectType, subjectId] as const,
  effectiveAccess: (orgId: string, userId: string) =>
    ["org", orgId, "effective-access", userId] as const,
};

/** Инвалидация всего, на что влияет изменение состава/прав.
 *  Список организаций тоже: в его строках живут счётчики user_count /
 *  community_count, которые показываются в заголовках секций. */
function useInvalidateOrg(orgId: string) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["org", orgId] });
    void client.invalidateQueries({ queryKey: ["organizations"] });
  };
}

// ── организации ────────────────────────────────────────────────────────────

/** Суперадмин получит все организации, админ — только свою (фильтрует сервер). */
export function useOrganizations() {
  return useQuery({
    queryKey: keys.organizations(),
    queryFn: () => api.listOrganizations(),
  });
}

export function useRegions() {
  return useQuery({
    queryKey: keys.regions(),
    queryFn: () => api.listRegions(),
  });
}

export function useOrganizationMutations() {
  const client = useQueryClient();
  // Создание организации меняет и её список, и всё, что от неё зависит.
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["organizations"] });
    void client.invalidateQueries({ queryKey: ["org"] });
  };

  const create = useMutation({
    mutationFn: (payload: api.OrganizationCreatePayload) =>
      api.createOrganization(payload),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({
      orgId,
      payload,
    }: {
      orgId: string;
      payload: api.OrganizationUpdatePayload;
    }) => api.updateOrganization(orgId, payload),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (orgId: string) => api.deleteOrganization(orgId),
    onSuccess: invalidate,
  });

  return { create, update, remove };
}

// ── пользователи ───────────────────────────────────────────────────────────

export function useUsers(orgId: string, filters: api.UserFilters) {
  return useQuery({
    queryKey: keys.users(orgId, filters),
    queryFn: () => api.listUsers(orgId, filters),
    enabled: Boolean(orgId),
    // Прошлая страница остаётся на экране, пока грузится новая — иначе таблица
    // «моргает» пустотой на каждое нажатие клавиши в поиске.
    placeholderData: (previous) => previous,
  });
}

export function useUserMutations(orgId: string) {
  const invalidate = useInvalidateOrg(orgId);

  const create = useMutation({
    mutationFn: (payload: api.UserCreatePayload) => api.createUser(orgId, payload),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: api.UserUpdatePayload }) =>
      api.updateUser(orgId, userId, payload),
    onSuccess: invalidate,
  });

  const block = useMutation({
    mutationFn: ({ userId, blocked }: { userId: string; blocked: boolean }) =>
      blocked ? api.blockUser(orgId, userId) : api.unblockUser(orgId, userId),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (userId: string) => api.deleteUser(orgId, userId),
    onSuccess: invalidate,
  });

  const resendInvitation = useMutation({
    mutationFn: (userId: string) => api.resendInvitation(orgId, userId),
    onSuccess: invalidate,
  });

  return { create, update, block, remove, resendInvitation };
}

export function useEffectiveAccess(orgId: string, userId: string | null) {
  return useQuery({
    queryKey: keys.effectiveAccess(orgId, userId ?? ""),
    queryFn: () => api.getEffectiveAccess(orgId, userId!),
    enabled: Boolean(orgId && userId),
  });
}

// ── группы пользователей ───────────────────────────────────────────────────

export function useUserGroups(orgId: string) {
  return useQuery({
    queryKey: keys.userGroups(orgId),
    queryFn: () => api.listUserGroups(orgId),
    enabled: Boolean(orgId),
  });
}

export function useUserGroupMembers(orgId: string, groupId: string | null) {
  return useQuery({
    queryKey: keys.userGroupMembers(orgId, groupId ?? ""),
    queryFn: () => api.getUserGroupMembers(orgId, groupId!),
    enabled: Boolean(orgId && groupId),
  });
}

export function useUserGroupMutations(orgId: string) {
  const invalidate = useInvalidateOrg(orgId);

  const create = useMutation({
    mutationFn: (payload: api.GroupPayload) => api.createUserGroup(orgId, payload),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({ groupId, payload }: { groupId: string; payload: api.GroupPayload }) =>
      api.updateUserGroup(orgId, groupId, payload),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (groupId: string) => api.deleteUserGroup(orgId, groupId),
    onSuccess: invalidate,
  });

  return { create, update, remove };
}

// ── сообщества и их группы ─────────────────────────────────────────────────

export function useCommunities(orgId: string) {
  return useQuery({
    queryKey: keys.communities(orgId),
    queryFn: () => api.listCommunities(orgId),
    enabled: Boolean(orgId),
  });
}

export function useDataHealth(orgId: string) {
  return useQuery({
    queryKey: keys.dataHealth(orgId),
    queryFn: () => api.getDataHealth(orgId),
    enabled: Boolean(orgId),
  });
}

export function useCommunityGroups(orgId: string) {
  return useQuery({
    queryKey: keys.communityGroups(orgId),
    queryFn: () => api.listCommunityGroups(orgId),
    enabled: Boolean(orgId),
  });
}

export function useCommunityGroupMembers(orgId: string, groupId: string | null) {
  return useQuery({
    queryKey: keys.communityGroupMembers(orgId, groupId ?? ""),
    queryFn: () => api.getCommunityGroupMembers(orgId, groupId!),
    enabled: Boolean(orgId && groupId),
  });
}

export function useCommunityGroupMutations(orgId: string) {
  const invalidate = useInvalidateOrg(orgId);

  const create = useMutation({
    mutationFn: (payload: api.CommunityGroupPayload) =>
      api.createCommunityGroup(orgId, payload),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({
      groupId,
      payload,
    }: {
      groupId: string;
      payload: api.CommunityGroupPayload;
    }) => api.updateCommunityGroup(orgId, groupId, payload),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (groupId: string) => api.deleteCommunityGroup(orgId, groupId),
    onSuccess: invalidate,
  });

  return { create, update, remove };
}

// ── права ──────────────────────────────────────────────────────────────────

export function useGrants(
  orgId: string,
  subjectType: api.SubjectType,
  subjectId: string | null,
) {
  return useQuery({
    queryKey: keys.grants(orgId, subjectType, subjectId ?? ""),
    queryFn: () => api.getGrants(orgId, subjectType, subjectId!),
    enabled: Boolean(orgId && subjectId),
  });
}

export function useReplaceGrants(orgId: string) {
  const invalidate = useInvalidateOrg(orgId);
  return useMutation({
    mutationFn: ({
      subjectType,
      subjectId,
      grants,
    }: {
      subjectType: api.SubjectType;
      subjectId: string;
      grants: api.GrantItem[];
    }) => api.replaceGrants(orgId, subjectType, subjectId, grants),
    onSuccess: invalidate,
  });
}

// ── импорт ─────────────────────────────────────────────────────────────────

export function useImport(orgId: string) {
  const invalidate = useInvalidateOrg(orgId);

  const preview = useMutation({
    mutationFn: (file: File) => api.importPreview(orgId, file),
  });

  const confirm = useMutation({
    mutationFn: (rows: api.ImportRow[]) => api.importConfirm(orgId, rows),
    onSuccess: invalidate,
  });

  return { preview, confirm };
}

// ── импорт площадок ────────────────────────────────────────────────────────

export function usePublicImport(orgId: string) {
  const invalidate = useInvalidateOrg(orgId);
  const [progress, setProgress] = useState<api.PublicImportProgress | null>(null);

  const preview = useMutation({
    mutationFn: (file: File) => api.publicImportPreview(orgId, file),
  });

  // Импорт идёт фоновой задачей: каждая площадка — это поход в API соцсети.
  const confirm = useMutation({
    mutationFn: async ({
      rows,
      dateFrom,
    }: {
      rows: api.PublicImportRow[];
      dateFrom: string | null;
    }) => {
      const { job_id } = await api.publicImportConfirm(orgId, rows, dateFrom);
      setProgress({
        jobId: job_id,
        done: 0,
        total: null,
        message: "Подготовка импорта…",
        cancelRequested: false,
      });
      try {
        return await api.waitPublicImportJob(job_id, setProgress);
      } finally {
        setProgress(null);
      }
    },
    // Часть площадок могла создаться и при отмене, поэтому списки обновляем
    // в любом исходе.
    onSettled: invalidate,
  });

  const cancel = () => {
    if (!progress) return;
    setProgress({ ...progress, cancelRequested: true });
    void api.publicImportCancel(progress.jobId).catch(() => {});
  };

  return { preview, confirm, progress, cancel };
}
