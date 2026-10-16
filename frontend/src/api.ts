/** Инфраструктура HTTP — централизована в src/lib/httpClient.ts.
 *  Здесь оставлены только legacy-обёртки `fetchJson` / `fetchBlob` поверх
 *  него, чтобы 43 существующие функции в этом файле продолжали работать
 *  без изменения сигнатур. JWT_KEY / getStoredToken / apiUrl остаются как
 *  публичные re-exports, потому что их импортируют App.tsx и др. */
import { httpClient } from "./lib/httpClient";
import { JWT_KEY } from "./lib/httpClientConstants";

export { JWT_KEY };
export const getStoredToken = (): string => localStorage.getItem(JWT_KEY) ?? "";

export function apiUrl(path: string): string {
  const base = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
  if (!path.startsWith("/")) return `${base}/${path}`;
  return base ? `${base}${path}` : path;
}

/** Legacy-хелпер. httpClient теперь сам читает токен из localStorage, поэтому
 *  переданный сюда `token` фактически игнорируется при отправке запроса
 *  (заголовок Authorization потом фильтруется в pickExtraHeaders). Оставлен
 *  только чтобы 43 существующие функции в этом файле компилировались. */
function authHeaders(_token: string): Record<string, string> {
  return {};
}

/** Достаём метод и parsed body из существующего RequestInit, чтобы передать
 *  их в httpClient. Это переходной мостик: новые функции пусть зовут
 *  `httpClient.X(...)` напрямую, а старые остаются через fetchJson. */
function deserializeBody(init: RequestInit): unknown {
  if (init.body === undefined || init.body === null) return undefined;
  if (typeof init.body === "string") {
    try {
      return JSON.parse(init.body);
    } catch {
      return init.body; // не JSON — отдаём как есть, httpClient разберётся
    }
  }
  return init.body; // FormData / Blob / etc — пробрасываем как есть
}

/** Доп. заголовки из старого init, без Content-Type (его выставит httpClient
 *  сам, в зависимости от типа body). Authorization мы тоже пропускаем: его
 *  теперь добавляет httpClient из localStorage напрямую. */
function pickExtraHeaders(init: RequestInit): Record<string, string> | undefined {
  if (!init.headers) return undefined;
  const headers = init.headers as Record<string, string>;
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    const lower = key.toLowerCase();
    if (lower === "content-type" || lower === "authorization") continue;
    result[key] = value;
  }
  return Object.keys(result).length > 0 ? result : undefined;
}

async function fetchJson<T>(path: string, init: RequestInit): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const body = deserializeBody(init);
  const extraHeaders = pickExtraHeaders(init);
  const options = { headers: extraHeaders, signal: init.signal ?? undefined };
  switch (method) {
    case "GET":
      return httpClient.get<T>(path, options);
    case "POST":
      return httpClient.post<T>(path, body, options);
    case "PUT":
      return httpClient.put<T>(path, body, options);
    case "PATCH":
      return httpClient.patch<T>(path, body, options);
    case "DELETE":
      return httpClient.delete<T>(path, options);
    default:
      throw new Error(`fetchJson: unsupported method ${method}`);
  }
}

async function fetchBlob(path: string, init: RequestInit): Promise<Blob> {
  const method = (init.method ?? "GET").toUpperCase();
  const body = deserializeBody(init);
  const extraHeaders = pickExtraHeaders(init);
  const options = extraHeaders ? { headers: extraHeaders } : undefined;
  if (method === "POST") return httpClient.postBlob(path, body, options);
  return httpClient.getBlob(path, options);
}

export type LlmGenerateResponse = {
  text: string;
  model: string;
};

export type LlmGeneratePayload = {
  public_social_link_id: string;
  event_description: string;
  event_date?: string;
  post_type?: string;
};

export async function llmGenerate(token: string, payload: LlmGeneratePayload): Promise<LlmGenerateResponse> {
  return fetchJson<LlmGenerateResponse>("/api/llm/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(payload),
  });
}

export type ReportPreviewPoint = {
  date: string;
  views: number;
  likes?: number | null;
  comments?: number | null;
  read_time_sec?: number | null;
};

export type ReportPreviewTopPost = {
  date?: string | null;
  text: string;
  views: number;
  likes?: number | null;
  comments?: number | null;
  url?: string | null;
};

export type ReportPreviewResponse = {
  platform: string;
  total_posts: number;
  avg_views: number;
  max_views: number;
  avg_likes?: number | null;
  max_likes?: number | null;
  avg_comments?: number | null;
  max_comments?: number | null;
  group_members?: number | null;
  channel?: string | null;
  points: ReportPreviewPoint[];
  top_posts: ReportPreviewTopPost[];
  all_posts: ReportPreviewTopPost[];
  recommendations: string;
  recommended_post_window?: string | null;
  activity_heatmap?: number[][] | null;
};

export async function apiReportPreview(
  token: string,
  payload: {
    platform: string;
    public_social_link_id?: string | null;
    municipality_name?: string | null;
    period?: "week" | "month" | "3months" | "6months" | "year" | "all";
    csv_path?: string | null;
  }
): Promise<ReportPreviewResponse> {
  return fetchJson<ReportPreviewResponse>("/api/report/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(payload),
  });
}

export async function apiReportRecommendations(
  token: string,
  payload: {
    platform: string;
    public_social_link_id?: string | null;
    municipality_name?: string | null;
    period?: "week" | "month" | "3months" | "6months" | "year" | "all";
  }
): Promise<{ recommendations: string }> {
  return fetchJson<{ recommendations: string }>("/api/report/recommendations", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(payload),
  });
}

export async function apiReportPdf(
  token: string,
  payload: {
    platform: string;
    public_social_link_id?: string | null;
    municipality_name?: string | null;
    period?: "week" | "month" | "3months" | "6months" | "year" | "all";
    csv_path?: string | null;
  }
): Promise<Blob> {
  return fetchBlob("/api/report/pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(payload),
  });
}

export type VkPosterResponse = {
  post_id: number;
  url: string;
};

/** Публикация на стену VK (токен и группа настраиваются на бэкенде). */
export async function vkPoster(token: string, payload: {
  message: string;
  attachments?: string | null;
  from_group?: boolean;
}): Promise<VkPosterResponse> {
  return fetchJson<VkPosterResponse>("/api/vk/poster", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({
      message: payload.message,
      attachments: payload.attachments ?? null,
      from_group: payload.from_group ?? true,
    }),
  });
}

export async function vkDeletePost(token: string, post_id: number): Promise<{ success: boolean }> {
  return fetchJson<{ success: boolean }>("/api/vk/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ post_id }),
  });
}

/** community/profile/post — VK, group/topic — Одноклассники. */
export type IngestResponse = {
  type: "community" | "profile" | "post" | "group" | "topic" | "channel";
  canonical_url: string;
  public_id: string | null;
  public_social_link_id: string | null;
  posts_imported: number;
  publications_imported: number;
  comments_imported: number;
  notes: string[] | null;
};

const OK_HOST_RE = /^(?:https?:\/\/)?(?:m\.|www\.)?(?:ok\.ru|odnoklassniki\.ru)(?:\/|$)/i;
const TELEGRAM_HOST_RE = /^(?:https?:\/\/)?(?:www\.)?(?:t\.me|telegram\.me)(?:\/|$)/i;

/** Ссылка адресована Одноклассникам, а не VK. */
export function isOkLink(url: string): boolean {
  return OK_HOST_RE.test(url.trim());
}

/** Ссылка адресована Telegram-каналу. */
export function isTelegramLink(url: string): boolean {
  return TELEGRAM_HOST_RE.test(url.trim());
}

/**
 * Импортирует площадку по ссылке. Соцсеть выбирается по хосту: у VK, OK и Telegram
 * разные эндпоинты, но одинаковые тело запроса и форма ответа.
 */
export async function ingestLink(
  token: string,
  payload: {
    url: string;
    max_posts?: number | null;
    fetch_comments?: boolean;
    date_from?: string | null;
    date_to?: string | null;
  }
): Promise<{ job_id: string }> {
  const body: Record<string, unknown> = {
    url: payload.url,
    fetch_comments: payload.fetch_comments ?? true,
  };
  if (payload.max_posts !== undefined && payload.max_posts !== null) {
    body.max_posts = payload.max_posts;
  }
  if (payload.date_from) body.date_from = payload.date_from;
  if (payload.date_to) body.date_to = payload.date_to;
  const endpoint = isTelegramLink(payload.url)
    ? "/api/telegram/ingest"
    : isOkLink(payload.url)
      ? "/api/ok/ingest"
      : "/api/vk/ingest";
  return fetchJson<{ job_id: string }>(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(body),
  });
}

export type VkPublicLink = {
  id: string;
  url: string | null;
  external_public_id: string | null;
  title: string | null;
  social_network_code?: string | null;
  social_network_name?: string | null;
  publications_count: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
  total_reposts: number;
  subscribers_count?: number;
  avg_views?: number;
  avg_engagement?: number;
  organic_reach?: number;
  metric_date?: string;
  first_comment_at?: string | null;
  last_comment_at?: string | null;
  /** Включён ли автопарсер по этой ссылке. */
  autoparse_enabled?: boolean;
  /** Когда автопарсер в последний раз проверял ссылку (ISO) или null. */
  last_autoparse_at?: string | null;
  /** Текст последней ошибки/причины пропуска автопарсера или null. */
  last_autoparse_error?: string | null;
};

export type VkPublicSummary = {
  id: string;
  name: string;
  description: string | null;
  region_id?: string | null;
  region_name?: string | null;
  municipality_name?: string | null;
  links: VkPublicLink[];
};

export type RegionOption = {
  id: string;
  name: string;
  code?: string | null;
};

export type AutoParseConfig = {
  enabled: boolean;
  interval_hours: number;
  lookback_days: number;
  check_interval_seconds: number;
  max_posts: number;
};

/** Текущие настройки автопарсера (период — глобальный, из БД). */
export async function apiGetAutoparseConfig(token: string): Promise<AutoParseConfig> {
  return fetchJson<AutoParseConfig>("/api/autoparse/config", {
    headers: { ...authHeaders(token) },
  });
}

/** Меняет период автопарсера (в часах). Доступно только суперадмину (403 иначе). */
export async function apiUpdateAutoparseConfig(
  token: string,
  intervalHours: number,
): Promise<AutoParseConfig> {
  return fetchJson<AutoParseConfig>("/api/autoparse/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ interval_hours: intervalHours }),
  });
}

export async function apiRefreshVkSubscribers(token: string): Promise<{ job_id: string }> {
  return fetchJson<{ job_id: string }>("/api/autoparse/subscribers/refresh", {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export async function apiGetVkPublics(token: string): Promise<VkPublicSummary[]> {
  return fetchJson<VkPublicSummary[]>("/api/analytics/publics", {
    headers: { ...authHeaders(token) },
  });
}

export async function apiGetRegions(token: string): Promise<RegionOption[]> {
  return fetchJson<RegionOption[]>("/api/analytics/regions", {
    headers: { ...authHeaders(token) },
  });
}

export async function apiUpdatePublicRegion(
  token: string,
  publicId: string,
  regionId: string | null,
  municipalityName: string | null = null,
): Promise<{ public_id: string; region_id: string | null; region_name: string | null; municipality_name: string | null }> {
  return fetchJson(`/api/analytics/publics/${publicId}/region`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ region_id: regionId, municipality_name: municipalityName }),
  });
}

export type PublicLocationInferenceResponse = {
  considered: number;
  updated_publics: number;
  updated_region: number;
  updated_municipality: number;
  unchanged: number;
};

export async function apiInferPublicLocations(token: string): Promise<PublicLocationInferenceResponse> {
  return fetchJson<PublicLocationInferenceResponse>("/api/analytics/publics/infer-location", {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export type Alert = {
  category: string;
  recent: number;
  prior: number;
  growth_pct: number | null;
  window_days: number;
};

export async function apiGetAlerts(
  token: string,
  publicSocialLinkId?: string | null,
  municipalityName?: string | null,
): Promise<Alert[]> {
  const q = new URLSearchParams();
  if (publicSocialLinkId) q.set("public_social_link_id", publicSocialLinkId);
  if (municipalityName) q.set("municipality_name", municipalityName);
  const qs = q.toString();
  return fetchJson<Alert[]>(`/api/analytics/alerts${qs ? `?${qs}` : ""}`, { headers: { ...authHeaders(token) } });
}

export type Incident = {
  problem: string;
  category: string;
  agency: string;
  mentions: number;
  answered: number;
  age_hours: number;
  status: "new" | "in_work" | "overdue";
};

export async function apiGetIncidents(
  token: string,
  publicSocialLinkId?: string | null,
  municipalityName?: string | null,
): Promise<Incident[]> {
  const q = new URLSearchParams();
  if (publicSocialLinkId) q.set("public_social_link_id", publicSocialLinkId);
  if (municipalityName) q.set("municipality_name", municipalityName);
  const qs = q.toString();
  return fetchJson<Incident[]>(`/api/analytics/incidents${qs ? `?${qs}` : ""}`, { headers: { ...authHeaders(token) } });
}

export type AgencyStat = {
  agency: string;
  incidents: number;
  mentions: number;
  answered: number;
  overdue: number;
  new: number;
  response_rate: number;
};

export async function apiGetAgencyRanking(
  token: string,
  publicSocialLinkId?: string | null,
  municipalityName?: string | null,
): Promise<AgencyStat[]> {
  const q = new URLSearchParams();
  if (publicSocialLinkId) q.set("public_social_link_id", publicSocialLinkId);
  if (municipalityName) q.set("municipality_name", municipalityName);
  const qs = q.toString();
  return fetchJson<AgencyStat[]>(`/api/analytics/agency-ranking${qs ? `?${qs}` : ""}`, { headers: { ...authHeaders(token) } });
}

export type PainMapPoint = {
  name: string;
  lat: number;
  lon: number;
  region?: string;
  municipality?: string;
  locality?: string;
  district: string;
  count: number;
  cases: string[];
};

export type AddressCaseDeleteResponse = {
  cases: string[];
  updated_analyses: number;
};

export type CaseComment = {
  text: string;
  date: string | null;
  url: string | null;
  comment_url: string | null;
  sentiment: string;
  public: string | null;
  category: string;
  subcategory: string;
  has_official_response: boolean;
  official_response_url: string | null;
  official_response_text: string | null;
  official_response_date: string | null;
};

export async function apiGetCaseComments(
  token: string,
  cases: string[],
  period = "week",
  publicSocialLinkId?: string | null,
  problemType?: string | null,
  municipalityName?: string | null,
): Promise<CaseComment[]> {
  return fetchJson<CaseComment[]>("/api/analytics/case-comments", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({
      cases,
      period,
      public_social_link_id: publicSocialLinkId ?? null,
      problem_type: problemType ?? null,
      municipality_name: municipalityName ?? null,
    }),
  });
}

export async function apiGetPainMap(
  token: string,
  period = "week",
  publicSocialLinkId?: string | null,
  problemType?: string | null,
  municipalityName?: string | null,
): Promise<PainMapPoint[]> {
  const qs = new URLSearchParams({ period });
  if (publicSocialLinkId) qs.set("public_social_link_id", publicSocialLinkId);
  if (problemType) qs.set("problem_type", problemType);
  if (municipalityName) qs.set("municipality_name", municipalityName);
  return fetchJson<PainMapPoint[]>(`/api/analytics/pain-map?${qs.toString()}`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiDeleteAddressCases(
  token: string,
  cases: string[],
): Promise<AddressCaseDeleteResponse> {
  return fetchJson<AddressCaseDeleteResponse>("/api/analytics/address-cases/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ cases }),
  });
}

export type GeoCacheProviderStatus = {
  yandex_configured: boolean;
  dadata_configured: boolean;
  priority: string[];
};

export type GeoCacheStatus = {
  path: string;
  absolute_path: string;
  exists: boolean;
  parent_exists: boolean;
  readable: boolean;
  writable: boolean;
  parent_writable: boolean;
  size_bytes: number | null;
  modified_at: string | null;
  total_entries: number;
  hit_entries: number;
  miss_entries: number;
  stale_miss_entries: number;
  malformed_entries: number;
  source_breakdown: Record<string, number>;
  sample_keys: string[];
  read_error: string | null;
  max_new_per_request: number;
  miss_ttl_seconds: number;
  timeout_seconds: number;
  providers: GeoCacheProviderStatus;
};

export type GeoCacheRotateResponse = {
  rotated: boolean;
  previous_path: string;
  backup_path: string | null;
  message: string;
  status_after: GeoCacheStatus;
};

export type AddressCaseGeocodingStats = {
  total_cases: number;
  geocoded_cases: number;
  not_geocoded_cases: number;
  rejected_cases: number;
  untried_cases: number;
  skipped_invalid_cases: number;
  total_mentions: number;
  geocoded_mentions: number;
  not_geocoded_mentions: number;
  rejected_mentions: number;
  untried_mentions: number;
  cache_hit_entries: number;
  cache_miss_entries: number;
  cache_total_entries: number;
  cache_read_error: string | null;
  cache_modified_at: string | null;
};

export type AddressCaseGeocodingBackfillResponse = {
  considered: number;
  already_cached: number;
  requests_made: number;
  geocoded: number;
  missed: number;
  fresh_miss_skipped: number;
  invalid_skipped: number;
  budget_exhausted: number;
  remaining: number;
};

export async function apiGetAddressCaseGeocodingStats(
  token: string,
): Promise<AddressCaseGeocodingStats> {
  return fetchJson<AddressCaseGeocodingStats>("/api/analytics/address-cases/geocoding-stats", {
    headers: { ...authHeaders(token) },
  });
}

export async function apiBackfillAddressCaseGeocoding(
  token: string,
): Promise<{ job_id: string }> {
  return fetchJson<{ job_id: string }>("/api/analytics/address-cases/geocoding-backfill", {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export async function apiRotateGeoCache(token: string): Promise<GeoCacheRotateResponse> {
  return fetchJson<GeoCacheRotateResponse>("/api/analytics/geo-cache/rotate", {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export async function apiExportAddressCases(
  token: string,
  opts: { dateFrom?: string; dateTo?: string; limit?: number } = {},
): Promise<Blob> {
  const q = new URLSearchParams();
  if (opts.dateFrom) q.set("date_from", opts.dateFrom);
  if (opts.dateTo) q.set("date_to", opts.dateTo);
  if (opts.limit) q.set("limit", String(opts.limit));
  const qs = q.toString();
  return fetchBlob(`/api/analytics/address-cases/export${qs ? `?${qs}` : ""}`, {
    headers: { ...authHeaders(token) },
  });
}

export type VkDefaultPublicResponse = {
  public_social_link_id: string | null;
  title: string | null;
  url: string | null;
  external_public_id: string | null;
};

export async function apiGetVkDefaultPublic(token: string): Promise<VkDefaultPublicResponse> {
  return fetchJson<VkDefaultPublicResponse>("/api/vk/default-public", {
    headers: { ...authHeaders(token) },
  });
}

export type DeleteImportedPublicResponse = {
  public_id: string;
  deleted_links: number;
  deleted_publications: number;
  deleted_comments: number;
  deleted_posts: number;
  snapshot_rebuilt: boolean;
};

export async function apiDeleteImportedPublic(token: string, publicId: string): Promise<DeleteImportedPublicResponse> {
  return fetchJson<DeleteImportedPublicResponse>(`/api/analytics/publics/${publicId}`, {
    method: "DELETE",
    headers: { ...authHeaders(token) },
  });
}

export type VkPublicationItem = {
  publication_id: string;
  url: string | null;
  external_post_id: string | null;
  published_at: string | null;
  title: string | null;
  text: string | null;
  public_id: string | null;
  views: number;
  likes: number;
  comments_count: number;
  reposts: number;
};

export async function apiGetVkPublications(
  token: string,
  opts?: { public_social_link_id?: string; limit?: number }
): Promise<VkPublicationItem[]> {
  const qs = new URLSearchParams();
  if (opts?.public_social_link_id) qs.set("public_social_link_id", opts.public_social_link_id);
  if (opts?.limit) qs.set("limit", String(opts.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return fetchJson<VkPublicationItem[]>(`/api/analytics/publications${suffix}`, {
    headers: { ...authHeaders(token) },
  });
}

// ─── Auth ────────────────────────────────────────────────────────────────────

export type AuthResponse = { access_token: string; token_type: string; email: string; name: string };
export type InvitationStatusResponse = {
  status: "pending" | "accepted" | "expired" | "invalid" | "unavailable";
  email: string | null;
  message: string;
};
export type MeResponse = {
  id: string;
  email: string;
  name: string;
  /** "superadmin" | "admin" | "minion" */
  role: string;
  /** Нужен для адресации /api/organizations/{id}/… и решения, показывать ли настройки. */
  organization_id: string | null;
  organization_name?: string | null;
  first_name: string;
  last_name: string;
};

export async function apiGetMe(token: string): Promise<MeResponse> {
  return fetchJson<MeResponse>("/api/auth/me", {
    headers: { ...authHeaders(token) },
  });
}

export async function authLogin(email: string, password: string): Promise<AuthResponse> {
  return httpClient.post<AuthResponse>("/api/auth/login", { email, password }, {
    headers: { "Content-Type": "application/json" },
    skipAuth: true,
  });
}

export async function authAcceptInvitation(token: string, password: string): Promise<AuthResponse> {
  return httpClient.post<AuthResponse>("/api/auth/invitations/accept", { token, password }, {
    headers: { "Content-Type": "application/json" },
    skipAuth: true,
  });
}

export async function authInvitationStatus(token: string): Promise<InvitationStatusResponse> {
  return httpClient.post<InvitationStatusResponse>("/api/auth/invitations/status", { token }, {
    headers: { "Content-Type": "application/json" },
    skipAuth: true,
  });
}

export async function authRequestPasswordReset(email: string): Promise<void> {
  return httpClient.post<void>("/api/auth/password-reset/request", { email }, {
    headers: { "Content-Type": "application/json" },
    skipAuth: true,
  });
}

export async function authConfirmPasswordReset(
  email: string,
  code: string,
  newPassword: string,
): Promise<void> {
  return httpClient.post<void>(
    "/api/auth/password-reset/confirm",
    { email, code, new_password: newPassword },
    { headers: { "Content-Type": "application/json" }, skipAuth: true },
  );
}

export async function apiChangeMyPassword(
  token: string,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  return fetchJson<void>("/api/auth/me/password", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

// ─── Posts (Content Events) ───────────────────────────────────────────────────

export type ApiPost = {
  id: string;
  title: string;
  origin?: string | null;
  text_draft: string | null;
  text_generated: string | null;
  tone: string;
  vk_post_id: string | null;
  vk_wall_url: string | null;
  status: string;
  scheduled_at?: string | null;
  published_at?: string | null;
  strategy_id?: string | null;
  created_at: string;
  publications?: ApiPublication[];
};

export type ApiPublication = {
  id: string;
  post_id: string;
  public_social_link_id: string;
  platform: string;
  public_title?: string | null;
  public_url?: string | null;
  status: string;
  scheduled_at?: string | null;
  published_at?: string | null;
  external_post_id?: string | null;
  url?: string | null;
  error_message?: string | null;
};

export async function apiGetPosts(token: string): Promise<ApiPost[]> {
  return fetchJson<ApiPost[]>(`/api/posts/?_ts=${Date.now()}`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiCreatePost(token: string, data: {
  title: string; text_draft: string; text_generated: string; tone: string; vk_post_id?: string | null; strategy_id?: string | null;
}): Promise<ApiPost> {
  return fetchJson<ApiPost>("/api/posts/", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
}

export async function apiUpdatePostVk(token: string, postId: string, vkPostId: string | null): Promise<ApiPost> {
  return fetchJson<ApiPost>(`/api/posts/${postId}/vk`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ vk_post_id: vkPostId }),
  });
}

export async function apiDeletePost(token: string, postId: string): Promise<void> {
  await fetchJson<unknown>(`/api/posts/${postId}`, {
    method: "DELETE",
    headers: { ...authHeaders(token) },
  });
}

export async function apiCreatePublication(token: string, postId: string, data: {
  platform: string;
  public_social_link_id?: string | null;
  scheduled_at?: string | null;
  status?: string;
  external_post_id?: string | null;
  url?: string | null;
  published_at?: string | null;
  error_message?: string | null;
}): Promise<ApiPost> {
  return fetchJson<ApiPost>(`/api/posts/${postId}/publications`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
}

export async function apiUpdatePublication(token: string, publicationId: string, data: {
  platform?: string;
  public_social_link_id?: string | null;
  scheduled_at?: string | null;
  status?: string;
  external_post_id?: string | null;
  url?: string | null;
  published_at?: string | null;
  error_message?: string | null;
}): Promise<ApiPost> {
  return fetchJson<ApiPost>(`/api/publications/${publicationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
}

export async function apiDeletePublication(token: string, publicationId: string): Promise<ApiPost> {
  return fetchJson<ApiPost>(`/api/publications/${publicationId}`, {
    method: "DELETE",
    headers: { ...authHeaders(token) },
  });
}

// ─── Calendar Events ──────────────────────────────────────────────────────────

export type ApiCalendarEvent = {
  id: string;
  title: string;
  origin?: string | null;
  date: string;
  start_time: string;
  end_time: string;
  description: string;
  status: string;
  platforms: string[];
  draft: string;
  tone: string;
  post_type: string;
  post_id?: string | null;
  info_event_id?: string | null;
  info_event_title?: string | null;
  inherited_pain_ids?: string[];
  inherited_pain_titles?: string[];
  publication_ids?: string[];
  public_social_link_ids?: string[];
  publication_urls?: Array<string | null>;
  day_total?: number;
};

export async function apiGetCalendarEvents(
  token: string,
  dateFrom: string | null = null,
  dateTo: string | null = null,
  perDay: number | null = null,
  publicIds: string[] = [],
  page?: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<ApiCalendarEvent[]> {
  // Просим показываемый период, а не всю историю: в месяце публикаций
  // десятки тысяч, и одним ответом они не помещаются. Для сетки хватает
  // нескольких записей на день плюс счётчик остальных.
  const q = new URLSearchParams({ timezone_name: Intl.DateTimeFormat().resolvedOptions().timeZone });
  if (dateFrom) q.set("date_from", dateFrom);
  if (dateTo) q.set("date_to", dateTo);
  if (perDay) q.set("per_day", String(perDay));
  if (publicIds.length) q.set("public_social_link_ids", publicIds.join(","));
  if (page) {
    q.set("limit", String(page.limit));
    q.set("offset", String(page.offset));
  }
  return fetchJson<ApiCalendarEvent[]>(`/api/calendar/?${q.toString()}`, {
    headers: { ...authHeaders(token) },
    signal,
  });
}

export async function apiGetCalendarEvent(token: string, postId: string): Promise<ApiCalendarEvent> {
  return fetchJson<ApiCalendarEvent>(`/api/calendar/${postId}`, { headers: authHeaders(token) });
}

export async function apiCreateCalendarEvent(token: string, data: {
  title: string; date: string; description: string;
  start_time: string; end_time: string; status: string; platforms: string[];
  public_social_link_ids?: string[];
  draft: string; tone: string; post_type: string; post_id?: string | null;
  info_event_id?: string | null;
}): Promise<ApiCalendarEvent> {
  return fetchJson<ApiCalendarEvent>("/api/calendar/", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
}

export async function apiUpdateCalendarEvent(token: string, eventId: string, data: {
  title: string; date: string; description: string;
  start_time: string; end_time: string; status: string; platforms: string[];
  public_social_link_ids?: string[];
  draft: string; tone: string; post_type: string; post_id?: string | null;
  info_event_id?: string | null;
}): Promise<ApiCalendarEvent> {
  return fetchJson<ApiCalendarEvent>(`/api/calendar/${eventId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
}

export async function apiDeleteCalendarEvent(token: string, eventId: string): Promise<void> {
  await fetchJson<unknown>(`/api/calendar/${eventId}`, {
    method: "DELETE",
    headers: { ...authHeaders(token) },
  });
}

/** Загружает фото в VK и возвращает строку вложения (photo{owner}_{id}). */
export type ApiInfoEvent = {
  id: string;
  title: string;
  description: string | null;
  event_date: string;
  location: string | null;
  source: string;
  external_id: string | null;
  created_at: string;
};

export type ApiInfoEventImportResponse = {
  imported_count: number;
  items: ApiInfoEvent[];
};

export async function apiGetEvents(token: string): Promise<ApiInfoEvent[]> {
  return fetchJson<ApiInfoEvent[]>("/api/events/", {
    headers: { ...authHeaders(token) },
  });
}

export async function apiCreateEventEntry(
  token: string,
  data: {
    title: string;
    description?: string | null;
    event_date: string;
    location?: string | null;
    external_id?: string | null;
  }
): Promise<ApiInfoEvent> {
  return fetchJson<ApiInfoEvent>("/api/events/", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
}

export async function apiUpdateEventEntry(
  token: string,
  eventId: string,
  data: {
    title: string;
    description?: string | null;
    event_date: string;
    location?: string | null;
    external_id?: string | null;
  }
): Promise<ApiInfoEvent> {
  return fetchJson<ApiInfoEvent>(`/api/events/${eventId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
}

export async function apiDeleteEventEntry(token: string, eventId: string): Promise<void> {
  await fetchJson<unknown>(`/api/events/${eventId}`, {
    method: "DELETE",
    headers: { ...authHeaders(token) },
  });
}

export async function apiImportEventsFile(token: string, file: File): Promise<ApiInfoEventImportResponse> {
  const form = new FormData();
  form.append("file", file);
  return httpClient.post<ApiInfoEventImportResponse>("/api/events/import", form, {
    headers: { ...authHeaders(token) },
  });
}

export async function vkUploadPhoto(token: string, file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const data = await httpClient.post<{ attachment: string }>("/api/vk/upload-photo", form, {
    headers: { ...authHeaders(token) },
  });
  return data.attachment;
}

// ─── Analytics / Pain Insights ───────────────────────────────────────────────

export type AnalyticsSummaryResponse = {
  snapshot_id: string;
  generated_at: string;
  global_summary: string | null;
  source_label: string;
  platforms: string[];
  pain_count: number;
  total_comment_count?: number;
  classified_comment_count?: number;
  relevant_comment_count: number;
  complaint_count: number;
  request_count: number;
  appeal_count: number;
  gratitude_count: number;
  other_count: number;
  filtered_count: number;
  unclassified_count?: number;
  recommended_post_window?: string | null;
  top_pains: string[];
  sentiment_breakdown: SentimentBreakdown;
  message_type_breakdown: MessageTypeBreakdown;
  relevance_breakdown: RelevanceBreakdown;
  category_breakdown: CategoryCountItem[];
  sla?: SlaStats;
};

export type SlaStats = {
  appeals: number;
  answered: number;
  response_rate: number;
  median_hours: number | null;
  avg_hours: number | null;
  within_sla_rate: number;
  sla_hours: number;
  official_total: number;
};

export type PainCommentExample = {
  text: string;
  url: string | null;
  publication_url: string | null;
  comment_id: string | null;
  message_type: string | null;
  sentiment: string | null;
};

export type SentimentBreakdown = {
  positive: number;
  neutral: number;
  negative: number;
};

export type MessageTypeBreakdown = {
  complaint: number;
  request: number;
  gratitude: number;
  offtopic: number;
  sarcasm: number;
};

export type RelevanceBreakdown = {
  relevant: number;
  irrelevant: number;
};

export type CategoryCountItem = {
  category: string;
  count: number;
  negative_count?: number;
  neutral_count?: number;
  positive_count?: number;
};

export type SubproblemCaseItem = {
  title: string;
  raw_title?: string | null;
  mentions_count: number;
  comment_examples: PainCommentExample[];
  sentiment_counts: SentimentBreakdown;
  message_type_counts: MessageTypeBreakdown;
  request_count: number;
  complaint_count: number;
  source_urls: string[];
};

export type SubproblemItem = {
  title: string;
  description: string | null;
  mentions_count: number;
  comment_examples: PainCommentExample[];
  sentiment_counts: SentimentBreakdown;
  message_type_counts: MessageTypeBreakdown;
  request_count: number;
  complaint_count: number;
  source_urls: string[];
  cases: SubproblemCaseItem[];
};

export type PainCaseRef = {
  title: string;
  raw_title?: string | null;
  mentions_count: number;
};

export type PainListItem = {
  id: string;
  title: string;
  category: string | null;
  subcategory?: string | null;
  mentions_count: number;
  publications_count: number;
  severity_level: string;
  status: string;
  comment_examples: PainCommentExample[];
  subproblems: string[];
  subproblem_count: number;
  top_cases?: PainCaseRef[];
  cases_count?: number;
  strategy_id?: string | null;
  communication_strategy?: string | null;
  strategy_preview: string | null;
  evidence_posts: string[];
};

export type ReactionGapEvent = {
  post_id: string;
  post_title: string | null;
  anchor_at: string;
  window_days: number;
  before_count: number;
  after_count: number;
  gap_pct: number | null;
};

export type ReactionGapSummary = {
  avg_gap_pct: number | null;
  measured_events: number;
  events: ReactionGapEvent[];
};

export type PainDetail = {
  id: string;
  title: string;
  description: string | null;
  category: string | null;
  subcategory?: string | null;
  mentions_count: number;
  publications_count: number;
  severity_level: string;
  status: string;
  comment_examples: PainCommentExample[];
  subproblems: string[];
  subproblem_items: SubproblemItem[];
  top_cases?: PainCaseRef[];
  cases_count?: number;
  sentiment_counts: SentimentBreakdown;
  message_type_counts: MessageTypeBreakdown;
  request_count: number;
  complaint_count: number;
  communication_strategy?: string | null;
  strategies: string[];
  strategy_ids: string[];
  evidence_posts: string[];
  reaction_gap?: ReactionGapSummary | null;
};

export type ApiModule = {
  id: string;
  public_id: string;
  name: string;
  goal: string | null;
  description: string | null;
  configuration: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ModuleCreatePayload = {
  name: string;
  goal?: string;
  description?: string;
};

export async function apiGetAnalyticsSummary(
  token: string,
  period: string = "week",
  sourceId: string | null = null,
  municipalityName: string | null = null,
): Promise<AnalyticsSummaryResponse> {
  const q = new URLSearchParams({ period });
  if (sourceId) q.set("public_social_link_id", sourceId);
  if (municipalityName) q.set("municipality_name", municipalityName);
  return fetchJson<AnalyticsSummaryResponse>(`/api/analytics/summary?${q.toString()}`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiGetPainList(
  token: string,
  period: string = "week",
  sourceId: string | null = null,
  municipalityName: string | null = null,
): Promise<PainListItem[]> {
  const q = new URLSearchParams({ period });
  if (sourceId) q.set("public_social_link_id", sourceId);
  if (municipalityName) q.set("municipality_name", municipalityName);
  return fetchJson<PainListItem[]>(`/api/analytics/pains?${q.toString()}`, {
    headers: { ...authHeaders(token) },
  });
}

export type RebuildNeededResponse = {
  needs_rebuild: boolean;
  reason: string;
  new_comments: number;
  pending_classification: number;
};

export type ReclassifyScope = "review" | "failed" | "unclassified" | "all";

export type ReclassifyResponse = {
  requeued: number;
};

export async function apiNeedsRebuild(token: string): Promise<RebuildNeededResponse> {
  return fetchJson<RebuildNeededResponse>(`/api/analytics/rebuild-needed`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiReclassifyVk(
  token: string,
  scope: ReclassifyScope = "review",
): Promise<ReclassifyResponse> {
  return fetchJson<ReclassifyResponse>("/api/analytics/reclassify-vk", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ scope }),
  });
}

export type PainTrendItem = {
  pain_id: string;
  /** Ряд по бакетам; размер бакета зависит от периода (см. bucket_days). */
  counts: number[];
  /** Дней в одном делении: 1 — сутки, 7 — неделя, 30 — месяц. */
  bucket_days: number;
};

export type PublicationPainBucket = {
  pain_id: string;
  pain_title: string;
  pain_category: string | null;
  comments_count: number;
};

export async function apiGetPublicationPainsByUrl(token: string, url: string): Promise<PublicationPainBucket[]> {
  const q = new URLSearchParams({ url });
  return fetchJson<PublicationPainBucket[]>(`/api/analytics/publications/pains-breakdown?${q.toString()}`, {
    headers: { ...authHeaders(token) },
  });
}

export type StrategyRegenerateResponse = {
  pain_id: string;
  strategy_id: string;
  description: string;
};

export async function apiRegeneratePainStrategy(token: string, painId: string): Promise<StrategyRegenerateResponse> {
  return fetchJson<StrategyRegenerateResponse>(`/api/analytics/pains/${painId}/regenerate-strategy`, {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export async function apiGetPainTrends(
  token: string,
  period: string = "week",
  sourceId: string | null = null,
  municipalityName: string | null = null,
): Promise<PainTrendItem[]> {
  const q = new URLSearchParams({ period });
  if (sourceId) q.set("public_social_link_id", sourceId);
  if (municipalityName) q.set("municipality_name", municipalityName);
  return fetchJson<PainTrendItem[]>(`/api/analytics/pains/trends?${q.toString()}`, {
    headers: { ...authHeaders(token) },
  });
}

export type PainCommentItem = {
  comment_id: string;
  text: string;
  url: string | null;
  publication_url: string | null;
  sentiment: string | null;
  message_type: string | null;
  is_official_response: boolean;
  comment_date: string | null;
  has_official_response: boolean;
  official_response_url: string | null;
  official_response_text: string | null;
  official_response_date: string | null;
};

export type PainCommentsPage = {
  items: PainCommentItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
};

export async function apiListPainComments(
  token: string,
  painId: string,
  opts: {
    subcategory?: string | null;
    sourceId?: string | null;
    municipalityName?: string | null;
    period?: string | null;
    limit?: number;
    offset?: number;
  } = {},
): Promise<PainCommentsPage> {
  const q = new URLSearchParams();
  if (opts.subcategory) q.set("subcategory", opts.subcategory);
  if (opts.sourceId) q.set("public_social_link_id", opts.sourceId);
  if (opts.municipalityName) q.set("municipality_name", opts.municipalityName);
  // «all» тоже отправляем: без параметра бэкенд подставляет неделю, и
  // карточка показывала недельные числа при выбранном «за всё время».
  if (opts.period) q.set("period", opts.period);
  q.set("limit", String(opts.limit ?? 20));
  q.set("offset", String(opts.offset ?? 0));
  return fetchJson<PainCommentsPage>(`/api/analytics/pains/${painId}/comments?${q.toString()}`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiGetPainDetail(
  token: string,
  painId: string,
  sourceId: string | null = null,
  period: string | null = null,
  municipalityName: string | null = null,
): Promise<PainDetail> {
  const q = new URLSearchParams();
  if (sourceId) q.set("public_social_link_id", sourceId);
  // Период отправляем всегда, включая «all»: иначе бэкенд возьмёт неделю.
  if (period) q.set("period", period);
  if (municipalityName) q.set("municipality_name", municipalityName);
  const qs = q.toString();
  return fetchJson<PainDetail>(`/api/analytics/pains/${painId}${qs ? `?${qs}` : ""}`, {
    headers: { ...authHeaders(token) },
  });
}

export type PainEventPostRef = {
  post_id: string;
  title: string;
  scheduled_at: string | null;
  status: string;
};

export type PainEventLink = {
  event_id: string;
  title: string;
  event_date: string;
  location: string | null;
  description: string | null;
  relation_type: string;
  posts?: PainEventPostRef[];
};

export type EventPainLink = {
  pain_id: string;
  pain_title: string;
  pain_category: string | null;
  relation_type: string;
};

export async function apiGetPainEvents(token: string, painId: string): Promise<PainEventLink[]> {
  return fetchJson<PainEventLink[]>(`/api/analytics/pains/${painId}/events`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiGetEventPains(token: string, eventId: string): Promise<EventPainLink[]> {
  return fetchJson<EventPainLink[]>(`/api/events/${eventId}/pains`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiLinkEventPains(
  token: string,
  eventId: string,
  painIds: string[],
  relationType: string = "addresses",
): Promise<EventPainLink[]> {
  return fetchJson<EventPainLink[]>(`/api/events/${eventId}/pains`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ pain_ids: painIds, relation_type: relationType }),
  });
}

export async function apiUnlinkEventPain(token: string, eventId: string, painId: string): Promise<void> {
  await httpClient.delete<void>(`/api/events/${eventId}/pains/${painId}`, {
    headers: { ...authHeaders(token) },
  });
}

export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type JobKind =
  | "vk_ingest"
  | "ok_ingest"
  | "analytics_rebuild"
  | "address_geocoding_backfill"
  | "vk_subscribers_refresh"
  | "publics_import";
export type JobInfo = {
  id: string;
  kind: JobKind;
  status: JobStatus;
  total: number | null;
  done: number;
  message: string;
  started_at: string;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  cancel_requested: boolean;
};

export async function apiGetJob(token: string, jobId: string): Promise<JobInfo> {
  return fetchJson<JobInfo>(`/api/jobs/${jobId}`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiCancelJob(token: string, jobId: string): Promise<{ ok: boolean; status?: string }> {
  return fetchJson<{ ok: boolean; status?: string }>(`/api/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

// Polling helper: ждёт пока job не завершится (completed/failed). onProgress
// дёргается на каждом тике (1.5s), даже если total=null — фронт сам решит как
// рисовать индикатор.
export async function waitForJob(
  token: string,
  jobId: string,
  onProgress?: (job: JobInfo) => void,
  { intervalMs = 1500 }: { intervalMs?: number } = {},
): Promise<JobInfo> {
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const job = await apiGetJob(token, jobId);
    onProgress?.(job);
    if (
      job.status === "completed" ||
      job.status === "failed" ||
      job.status === "cancelled"
    ) {
      return job;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export async function apiRebuildVkAnalytics(
  token: string,
  forceReclassify = false,
  period?: string | null,
  prefilter = true,
  incremental = false,
  publicSocialLinkId?: string | null,
): Promise<{ job_id: string }> {
  const params = new URLSearchParams({ force_reclassify: String(forceReclassify) });
  if (incremental) params.set("incremental", "true");
  // Период отправляем всегда, включая «all»: иначе бэкенд возьмёт неделю.
  if (period) params.set("period", period);
  if (!prefilter) params.set("prefilter", "false");
  if (publicSocialLinkId) params.set("public_social_link_id", publicSocialLinkId);
  return fetchJson<{ job_id: string }>(`/api/analytics/rebuild-vk?${params.toString()}`, {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export async function apiVkCommentCount(
  token: string,
  period?: string | null,
  publicSocialLinkId?: string | null,
): Promise<{ count: number; period: string | null }> {
  const params = new URLSearchParams();
  // Период отправляем всегда, включая «all»: иначе бэкенд возьмёт неделю.
  if (period) params.set("period", period);
  if (publicSocialLinkId) params.set("public_social_link_id", publicSocialLinkId);
  const qs = params.toString();
  return fetchJson<{ count: number; period: string | null }>(
    `/api/analytics/vk-comment-count${qs ? `?${qs}` : ""}`,
    { headers: { ...authHeaders(token) } },
  );
}

export type ClassificationQueuePublic = {
  public_id: string;
  name: string;
  pending: number;
  processing: number;
};

export type ClassificationQueue = {
  pending: number;
  processing: number;
  done: number;
  failed: number;
  failed_retrying?: number;
  failed_final?: number;
  needs_review?: number;
  in_progress: number;
  remaining?: number;
  paused: boolean;
  llm_ok?: boolean;
  rate_per_minute: number | null;
  eta_minutes: number | null;
  rate_source?: "recent" | "historical" | "single_batch_default" | "default" | string;
  rate_window_seconds?: number;
  rate_sample_size?: number;
  by_public: ClassificationQueuePublic[];
};

export async function apiClassificationQueue(token: string): Promise<ClassificationQueue> {
  return fetchJson<ClassificationQueue>(`/api/analytics/classification/queue`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiSkipPublicQueue(token: string, publicId: string): Promise<{ removed: number }> {
  return fetchJson(`/api/analytics/classification/queue/public/${publicId}/skip`, {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export async function apiPauseWorker(token: string): Promise<{ paused: boolean }> {
  return fetchJson(`/api/analytics/classification/worker/pause`, {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export async function apiResumeWorker(token: string): Promise<{ paused: boolean }> {
  return fetchJson(`/api/analytics/classification/worker/resume`, {
    method: "POST",
    headers: { ...authHeaders(token) },
  });
}

export type ClassificationReviewTaxonomy = {
  categories: string[];
  subcategories: Record<string, string[]>;
};

export type ClassificationReviewItem = {
  analysis_id: string;
  comment_id: string;
  text: string;
  summary: string | null;
  sentiment: string | null;
  message_type: string | null;
  hierarchy: Record<string, unknown>;
  public_name: string | null;
  publication_url: string | null;
  comment_date: string | null;
};

export type ClassificationReviewPage = {
  items: ClassificationReviewItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
};

export async function apiClassificationReviewTaxonomy(token: string): Promise<ClassificationReviewTaxonomy> {
  return fetchJson<ClassificationReviewTaxonomy>("/api/analytics/classification/review/taxonomy", {
    headers: { ...authHeaders(token) },
  });
}

export async function apiClassificationReview(
  token: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<ClassificationReviewPage> {
  const q = new URLSearchParams();
  q.set("limit", String(opts.limit ?? 25));
  q.set("offset", String(opts.offset ?? 0));
  return fetchJson<ClassificationReviewPage>(`/api/analytics/classification/review?${q.toString()}`, {
    headers: { ...authHeaders(token) },
  });
}

export async function apiResolveClassificationReview(
  token: string,
  analysisId: string,
  payload: { category: string; subcategory?: string; case?: string },
): Promise<{ resolved: boolean }> {
  return fetchJson<{ resolved: boolean }>(`/api/analytics/classification/review/${analysisId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(payload),
  });
}

export async function apiCreateModule(token: string, payload: ModuleCreatePayload): Promise<ApiModule> {
  return fetchJson<ApiModule>("/api/modules/create", {
    method: "POST",
    headers: {
      ...authHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function apiGetModules(token: string): Promise<ApiModule[]> {
  return fetchJson<ApiModule[]>("/api/modules", {
    headers: { ...authHeaders(token) },
  });
}
