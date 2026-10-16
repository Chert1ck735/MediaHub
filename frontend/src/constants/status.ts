// Статус UI-сообщений (форма авторизации, smart-event-modal). Управляет
// какую плашку показать пользователю — success / error / нейтрально.

export const MESSAGE_STATUS = {
  SUCCESS: "success",
  ERROR: "error",
  IDLE: "idle",
} as const;

export type MessageType = (typeof MESSAGE_STATUS)[keyof typeof MESSAGE_STATUS];

export const CALENDAR_VIEW = {
  MONTH: "month",
  WEEK: "week",
} as const;

export type CalendarView = (typeof CALENDAR_VIEW)[keyof typeof CALENDAR_VIEW];

export const EVENT_STATUS = {
  DRAFT: "draft",
  SCHEDULED: "scheduled",
  PUBLISHED: "published",
} as const;

export type EventStatus = (typeof EVENT_STATUS)[keyof typeof EVENT_STATUS];

export const REPORT_PLATFORM = {
  VK: "vk",
  DZEN: "dzen",
  TELEGRAM: "telegram",
  OK: "ok",
} as const;

export type ReportPlatform = (typeof REPORT_PLATFORM)[keyof typeof REPORT_PLATFORM];

export const REPORT_PERIOD = {
  WEEK: "week",
  MONTH: "month",
  THREE_MONTHS: "3months",
  SIX_MONTHS: "6months",
  YEAR: "year",
  ALL: "all",
} as const;

export type ReportPeriod = (typeof REPORT_PERIOD)[keyof typeof REPORT_PERIOD];

export const ANALYTICS_VIEW = {
  PAINS: "pains",
  POSTS: "posts",
  DYNAMICS: "dynamics",
  MAP: "map",
  INCIDENTS: "incidents",
} as const;

export type AnalyticsView = (typeof ANALYTICS_VIEW)[keyof typeof ANALYTICS_VIEW];

export const PAIN_SEVERITY_FILTER = {
  ALL: "all",
  CRITICAL: "critical",
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
} as const;

export type PainSeverityFilter = (typeof PAIN_SEVERITY_FILTER)[keyof typeof PAIN_SEVERITY_FILTER];
