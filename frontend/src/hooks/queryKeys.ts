export const queryKeys = {
  me: (token: string | null) => ["me", token] as const,
  organizations: (token: string | null) => ["organizations", token] as const,
  posts: (token: string | null) => ["posts", token] as const,
  calendarEvents: (
    token: string | null,
    dateFrom: string | null = null,
    dateTo: string | null = null,
    perDay: number | null = null,
    publics = "",
  ) => ["calendar-events", token, dateFrom, dateTo, perDay, publics] as const,
  // Все окна сразу: после создания или удаления публикации устаревает
  // не только показанный месяц.
  calendarEventsAll: (token: string | null) => ["calendar-events", token] as const,
  events: (token: string | null) => ["events", token] as const,
  modules: (token: string | null) => ["modules", token] as const,
  defaultVkPublic: (token: string | null) => ["default-vk-public", token] as const,
  analyticsSummary: (token: string | null, period: string, sourceId: string | null, municipalityName: string | null) =>
    ["analytics-summary", token, period, sourceId, municipalityName] as const,
  painList: (token: string | null, period: string, sourceId: string | null, municipalityName: string | null) =>
    ["pain-list", token, period, sourceId, municipalityName] as const,
  painTrends: (token: string | null, period: string, sourceId: string | null, municipalityName: string | null) =>
    ["pain-trends", token, period, sourceId, municipalityName] as const,
  painDetail: (token: string | null, painId: string | null, sourceId: string | null, period: string, municipalityName: string | null) =>
    ["pain-detail", token, painId, sourceId, period, municipalityName] as const,
  painEvents: (token: string | null, painId: string | null) => ["pain-events", token, painId] as const,
  eventPains: (token: string | null, eventId: string | null) => ["event-pains", token, eventId] as const,
  painComments: (
    token: string | null,
    painId: string | null,
    subcategory: string | null,
    sourceId: string | null,
    period: string,
    limit: number,
    municipalityName: string | null,
  ) => ["pain-comments", token, painId, subcategory, sourceId, period, limit, municipalityName] as const,
  reportPreview: (
    token: string | null,
    platform: string,
    sourceId: string | null,
    period: string,
    municipalityName: string | null,
  ) => ["report-preview", token, platform, sourceId, period, municipalityName] as const,
  reportRecommendations: (
    token: string | null,
    platform: string,
    sourceId: string | null,
    period: string,
    municipalityName: string | null,
  ) => ["report-recommendations", token, platform, sourceId, period, municipalityName] as const,
  publicationPainsByUrl: (token: string | null, url: string | null) =>
    ["publication-pains-by-url", token, url] as const,
  alerts: (token: string | null, sourceId: string | null) => ["alerts", token, sourceId] as const,
  classificationQueue: (token: string | null) => ["classification-queue", token] as const,
};
