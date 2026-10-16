/** Клиент API настроек организации.
 *
 *  Типы здесь — зеркало backend/modules/organization/schemas.py. Держим их
 *  честными: если поле необязательно на сервере, оно необязательно и тут.
 *
 *  Права НЕ проверяются на клиенте — сервер отдаёт 403 сам. UI только скрывает
 *  то, что всё равно не сработает, и показывает понятный экран при отказе.
 */
import { httpClient } from "../lib/httpClient";

export type UserRole = "superadmin" | "admin" | "minion";
export type UserStatus = "active" | "blocked" | "invited";
export type Permission =
  | "view_community"
  | "create_post"
  | "manage_community"
  | "view_organization_analytics";
export type SubjectType = "user" | "user_group";
export type ResourceType = "community" | "community_group";

export const ROLE_LABELS: Record<UserRole, string> = {
  superadmin: "Суперадминистратор",
  admin: "Администратор",
  minion: "Пользователь",
};

export const STATUS_LABELS: Record<UserStatus, string> = {
  active: "Активен",
  blocked: "Заблокирован",
  invited: "Приглашён",
};

/** Права, которые реально выдаются вручную.
 *
 *  «Просмотр» сюда НЕ входит: сообщества своей организации видит каждый
 *  сотрудник по умолчанию (см. AuthorizationService.has_permission). Рисовать
 *  для него чекбокс — врать: он всё равно был бы всегда включён и ни на что не
 *  влиял. Грантами управляется только то, что МЕНЯЕТ мир. */
export const EDITABLE_PERMISSIONS: { key: Permission; label: string }[] = [
  { key: "create_post", label: "Публикация" },
];

export type OrgType =
  | "government"
  | "university"
  | "volunteer"
  | "business"
  | "youth_center"
  | "other";

export const ORG_TYPE_LABELS: Record<OrgType, string> = {
  government: "Организация",
  university: "Вуз",
  volunteer: "Волонтёрская",
  business: "Бизнес",
  youth_center: "Молодёжный центр",
  other: "Другое",
};

export type Organization = {
  id: string;
  name: string;
  type: OrgType;
  description: string | null;
  region_id: string | null;
  region_name: string | null;
  municipality_name: string | null;
  is_active: boolean;
  created_at: string;
  user_count: number;
  community_count: number;
};

export type RegionOption = {
  id: string;
  name: string;
  code?: string | null;
};

export type UserGroupBrief = { id: string; name: string };

export type OrgUser = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  role: UserRole;
  status: UserStatus;
  created_at: string;
  groups: UserGroupBrief[];
  accessible_communities_count: number;
};

export type UserListPage = {
  items: OrgUser[];
  total: number;
  page: number;
  page_size: number;
};

export type UserGroup = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  member_count: number;
  grant_count: number;
};

export type CommunityGroup = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  community_count: number;
  grant_count: number;
};

export type Community = { id: string; name: string };

export type DataStatus = "empty" | "fresh" | "warning" | "stale" | "unknown";
export type ClassificationStatus =
  | "no_comments"
  | "complete"
  | "processing"
  | "incomplete"
  | "has_errors";
export type OverallHealthStatus =
  | "ok"
  | "attention"
  | "stale_data"
  | "classification_incomplete"
  | "classification_errors"
  | "empty";

export type DataHealthItem = {
  public_id: string;
  public_name: string;
  link_id: string;
  link_title: string | null;
  url: string;
  is_active: boolean;
  social_network_code: string;
  social_network_name: string;
  posts_count: number;
  comments_count: number;
  analyzed_count: number;
  classified_count: number;
  pending_count: number;
  processing_count: number;
  failed_count: number;
  missing_analysis_count: number;
  classification_percent: number;
  last_publication_at: string | null;
  last_post_sync_at: string | null;
  last_comment_at: string | null;
  last_parsed_at: string | null;
  last_analysis_at: string | null;
  data_age_hours: number | null;
  data_status: DataStatus;
  classification_status: ClassificationStatus;
  overall_status: OverallHealthStatus;
};

export type DataHealthResponse = {
  generated_at: string;
  thresholds: {
    fresh_hours: number;
    warning_hours: number;
  };
  summary: {
    links_count: number;
    active_links_count: number;
    posts_count: number;
    comments_count: number;
    classified_count: number;
    pending_count: number;
    processing_count: number;
    failed_count: number;
    missing_analysis_count: number;
    classification_percent: number;
    stale_links_count: number;
    warning_links_count: number;
    incomplete_classification_links_count: number;
    failed_classification_links_count: number;
    oldest_data_age_hours: number | null;
  };
  items: DataHealthItem[];
};

export type GrantItem = {
  resource_type: ResourceType;
  resource_id: string;
  permission: Permission;
};

export type GrantMatrix = {
  subject_type: SubjectType;
  subject_id: string;
  grants: GrantItem[];
};

export type EffectiveAccessItem = {
  community_id: string;
  community_name: string;
  permission: Permission;
  source_type: "direct" | "user_group";
  source_name: string | null;
};

export type ImportRowStatus = "create" | "update" | "skip" | "error";

export type ImportRow = {
  row_number: number;
  status: ImportRowStatus;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  role: UserRole | null;
  user_groups: string[];
  errors: string[];
  warnings: string[];
};

export type ImportPreview = {
  rows: ImportRow[];
  to_create: number;
  to_update: number;
  skipped: number;
  errors: number;
  new_groups: string[];
};

export type ImportResult = {
  created: number;
  updated: number;
  skipped: number;
  errors: number;
  created_groups: string[];
  error_rows: ImportRow[];
};

const base = (orgId: string) => `/api/organizations/${orgId}`;

// ── организации ────────────────────────────────────────────────────────────

export function listOrganizations(): Promise<Organization[]> {
  return httpClient.get<Organization[]>("/api/organizations");
}

export type OrganizationCreatePayload = {
  name: string;
  type: OrgType;
  description?: string | null;
  region_id?: string | null;
  municipality_name?: string | null;
  /** Организацию без админа управлять сможет только суперадмин, поэтому
   *  администратора удобно завести тем же действием. */
  admin_email?: string | null;
  admin_first_name?: string | null;
  admin_last_name?: string | null;
};

export function createOrganization(
  payload: OrganizationCreatePayload,
): Promise<Organization> {
  return httpClient.post<Organization>("/api/organizations", payload);
}

export type OrganizationUpdatePayload = Partial<{
  name: string;
  type: OrgType;
  description: string | null;
  region_id: string | null;
  municipality_name: string | null;
  is_active: boolean;
}>;

export function updateOrganization(
  orgId: string,
  payload: OrganizationUpdatePayload,
): Promise<Organization> {
  return httpClient.patch<Organization>(`/api/organizations/${orgId}`, payload);
}

/** Удаляет организацию со всем содержимым. Только суперадмин — сервер вернёт
 *  403 остальным, независимо от того, что нарисовано в интерфейсе. */
export function deleteOrganization(orgId: string): Promise<void> {
  return httpClient.delete(`/api/organizations/${orgId}`);
}

export function listRegions(): Promise<RegionOption[]> {
  return httpClient.get<RegionOption[]>("/api/analytics/regions");
}

// ── пользователи ───────────────────────────────────────────────────────────

export type UserFilters = {
  search?: string;
  role?: UserRole | "";
  status?: UserStatus | "";
  page?: number;
  pageSize?: number;
};

export function listUsers(orgId: string, filters: UserFilters = {}): Promise<UserListPage> {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.role) params.set("role", filters.role);
  if (filters.status) params.set("status", filters.status);
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 25));
  return httpClient.get<UserListPage>(`${base(orgId)}/users?${params.toString()}`);
}

export type UserCreatePayload = {
  email: string;
  first_name: string;
  last_name?: string;
  role?: UserRole;
  group_ids?: string[];
};

export function createUser(orgId: string, payload: UserCreatePayload): Promise<OrgUser> {
  return httpClient.post<OrgUser>(`${base(orgId)}/users`, payload);
}

export type UserUpdatePayload = Partial<{
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  status: UserStatus;
  group_ids: string[];
}>;

export function updateUser(
  orgId: string,
  userId: string,
  payload: UserUpdatePayload,
): Promise<OrgUser> {
  return httpClient.patch<OrgUser>(`${base(orgId)}/users/${userId}`, payload);
}

export function blockUser(orgId: string, userId: string): Promise<OrgUser> {
  return httpClient.post<OrgUser>(`${base(orgId)}/users/${userId}/block`);
}

export function unblockUser(orgId: string, userId: string): Promise<OrgUser> {
  return httpClient.post<OrgUser>(`${base(orgId)}/users/${userId}/unblock`);
}

export function deleteUser(orgId: string, userId: string): Promise<void> {
  return httpClient.delete(`${base(orgId)}/users/${userId}`);
}

export function resendInvitation(orgId: string, userId: string): Promise<void> {
  return httpClient.post<void>(`${base(orgId)}/users/${userId}/resend-invitation`);
}

export function getEffectiveAccess(
  orgId: string,
  userId: string,
): Promise<EffectiveAccessItem[]> {
  return httpClient.get<EffectiveAccessItem[]>(
    `${base(orgId)}/users/${userId}/effective-access`,
  );
}

// ── группы пользователей ───────────────────────────────────────────────────

export function listUserGroups(orgId: string): Promise<UserGroup[]> {
  return httpClient.get<UserGroup[]>(`${base(orgId)}/user-groups`);
}

export type GroupPayload = {
  name: string;
  description?: string | null;
  member_ids?: string[];
};

export function createUserGroup(orgId: string, payload: GroupPayload): Promise<UserGroup> {
  return httpClient.post<UserGroup>(`${base(orgId)}/user-groups`, payload);
}

export function updateUserGroup(
  orgId: string,
  groupId: string,
  payload: GroupPayload,
): Promise<UserGroup> {
  return httpClient.put<UserGroup>(`${base(orgId)}/user-groups/${groupId}`, payload);
}

export function deleteUserGroup(orgId: string, groupId: string): Promise<void> {
  return httpClient.delete(`${base(orgId)}/user-groups/${groupId}`);
}

export function getUserGroupMembers(orgId: string, groupId: string): Promise<string[]> {
  return httpClient.get<string[]>(`${base(orgId)}/user-groups/${groupId}/members`);
}

// ── группы сообществ ───────────────────────────────────────────────────────

export function listCommunities(orgId: string): Promise<Community[]> {
  return httpClient.get<Community[]>(`${base(orgId)}/communities`);
}

export function getDataHealth(orgId: string): Promise<DataHealthResponse> {
  return httpClient.get<DataHealthResponse>(`${base(orgId)}/data-health`);
}

export function listCommunityGroups(orgId: string): Promise<CommunityGroup[]> {
  return httpClient.get<CommunityGroup[]>(`${base(orgId)}/community-groups`);
}

export type CommunityGroupPayload = {
  name: string;
  description?: string | null;
  community_ids?: string[];
};

export function createCommunityGroup(
  orgId: string,
  payload: CommunityGroupPayload,
): Promise<CommunityGroup> {
  return httpClient.post<CommunityGroup>(`${base(orgId)}/community-groups`, payload);
}

export function updateCommunityGroup(
  orgId: string,
  groupId: string,
  payload: CommunityGroupPayload,
): Promise<CommunityGroup> {
  return httpClient.put<CommunityGroup>(
    `${base(orgId)}/community-groups/${groupId}`,
    payload,
  );
}

export function deleteCommunityGroup(orgId: string, groupId: string): Promise<void> {
  return httpClient.delete(`${base(orgId)}/community-groups/${groupId}`);
}

export function getCommunityGroupMembers(
  orgId: string,
  groupId: string,
): Promise<string[]> {
  return httpClient.get<string[]>(
    `${base(orgId)}/community-groups/${groupId}/communities`,
  );
}

// ── права ──────────────────────────────────────────────────────────────────

export function getGrants(
  orgId: string,
  subjectType: SubjectType,
  subjectId: string,
): Promise<GrantMatrix> {
  const params = new URLSearchParams({
    subject_type: subjectType,
    subject_id: subjectId,
  });
  return httpClient.get<GrantMatrix>(`${base(orgId)}/grants?${params.toString()}`);
}

export function replaceGrants(
  orgId: string,
  subjectType: SubjectType,
  subjectId: string,
  grants: GrantItem[],
): Promise<GrantMatrix> {
  return httpClient.put<GrantMatrix>(`${base(orgId)}/grants`, {
    subject_type: subjectType,
    subject_id: subjectId,
    grants,
  });
}

// ── импорт ─────────────────────────────────────────────────────────────────

export function importPreview(orgId: string, file: File): Promise<ImportPreview> {
  const form = new FormData();
  form.append("file", file);
  return httpClient.post<ImportPreview>(`${base(orgId)}/users/import/preview`, form);
}

export function importConfirm(orgId: string, rows: ImportRow[]): Promise<ImportResult> {
  return httpClient.post<ImportResult>(`${base(orgId)}/users/import/confirm`, { rows });
}

export function importTemplateUrl(orgId: string): string {
  return `${base(orgId)}/users/import/template`;
}

/** Выгрузка таблицы пользователей. Колонки те же, что принимает импорт, —
 *  файл можно поправить в Excel и загрузить обратно. */
export function exportUsers(orgId: string, fmt: "csv" | "xlsx"): Promise<Blob> {
  return httpClient.getBlob(`${base(orgId)}/users/export?fmt=${fmt}`);
}

/** Общий помощник: сохранить полученный Blob как файл. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function downloadErrorReport(orgId: string, rows: ImportRow[]): Promise<Blob> {
  return httpClient.postBlob(`${base(orgId)}/users/import/error-report`, { rows });
}

// ── импорт площадок ────────────────────────────────────────────────────────

export type PublicImportRowStatus = "create" | "skip" | "error";

export type PublicImportRow = {
  row_number: number;
  status: PublicImportRowStatus;
  name: string | null;
  url: string | null;
  errors: string[];
  warnings: string[];
};

export type PublicImportPreview = {
  rows: PublicImportRow[];
  to_create: number;
  skipped: number;
  errors: number;
};

export type PublicImportResult = {
  created: number;
  skipped: number;
  errors: number;
  error_rows: PublicImportRow[];
};

export function publicImportPreview(orgId: string, file: File): Promise<PublicImportPreview> {
  const form = new FormData();
  form.append("file", file);
  return httpClient.post<PublicImportPreview>(`${base(orgId)}/publics/import/preview`, form);
}

export type PublicImportProgress = {
  jobId: string;
  done: number;
  total: number | null;
  message: string;
  cancelRequested: boolean;
};

type PublicImportJobSnapshot = {
  id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  total: number | null;
  done: number;
  message: string;
  result: PublicImportResult | null;
  error: string | null;
  cancel_requested: boolean;
};

/** Запускает импорт. Возвращает id фоновой задачи — результат ждём отдельно. */
export function publicImportConfirm(
  orgId: string,
  rows: PublicImportRow[],
  dateFrom: string | null,
): Promise<{ job_id: string }> {
  return httpClient.post<{ job_id: string }>(`${base(orgId)}/publics/import/confirm`, {
    rows,
    date_from: dateFrom,
    date_to: null,
  });
}

/** Просит платформу остановить импорт: задача прервётся на ближайшей строке. */
export function publicImportCancel(jobId: string): Promise<unknown> {
  return httpClient.post(`/api/jobs/${jobId}/cancel`, {});
}

/** Поллит задачу импорта до завершения, попутно отдавая прогресс. */
export async function waitPublicImportJob(
  jobId: string,
  onProgress?: (progress: PublicImportProgress) => void,
  { intervalMs = 1500 }: { intervalMs?: number } = {},
): Promise<PublicImportResult> {
  for (;;) {
    const job = await httpClient.get<PublicImportJobSnapshot>(`/api/jobs/${jobId}`);
    onProgress?.({
      jobId: job.id,
      done: job.done,
      total: job.total,
      message: job.message,
      cancelRequested: job.cancel_requested,
    });

    if (job.status === "completed") {
      if (!job.result) throw new Error("Задача завершилась без результата");
      return job.result;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "Импорт завершился ошибкой");
    }
    if (job.status === "cancelled") {
      throw new Error("Импорт отменён");
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function publicImportTemplateUrl(orgId: string): string {
  return `${base(orgId)}/publics/import/template`;
}

export function downloadPublicErrorReport(
  orgId: string,
  rows: PublicImportRow[],
): Promise<Blob> {
  return httpClient.postBlob(`${base(orgId)}/publics/import/error-report`, { rows });
}
