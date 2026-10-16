import { useRef, useState } from "react";

import type { ApiInfoEvent, JobInfo, PainDetail } from "../api";
import { readAnalyticsSettings } from "../app/analyticsSettings";
import {
  defaultInfoEventForm,
  SESSION_KEY,
  THEME_KEY,
} from "../app/constants";
import type {
  AnalyticsView,
  AuthMode,
  CalendarEvent,
  CalendarView,
  ContentEvent,
  EventStatus,
  InfoEventForm,
  MessageType,
  PainSeverityFilter,
  ReportPeriod,
  ReportPlatform,
  SeriesPlanItem,
  SmartEntryMode,
  ThemeMode,
} from "../app/types";
import {
  ANALYTICS_VIEW,
  CALENDAR_VIEW,
  EVENT_STATUS,
  INFO_EVENT_SORT,
  MESSAGE_STATUS,
  PAIN_COMMENTS_PAGE_SIZE,
  PAIN_SEVERITY_FILTER,
  REPORT_PERIOD,
  REPORT_PLATFORM,
  THEME,
} from "../constants";
import type { InfoEventSort } from "../constants";
import { useUnmountTimeoutSafe } from "../app/hooks/useUnmountTimeoutSafe";
import { getStoredToken } from "../api";
import { toInputDate } from "../app/utils";

export function useAppShellState() {
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [calendarModalOpen, setCalendarModalOpen] = useState(false);
  const [infoEventModalOpen, setInfoEventModalOpen] = useState(false);
  const [calendarView, setCalendarView] = useState<CalendarView>(CALENDAR_VIEW.MONTH);
  const [calendarDate, setCalendarDate] = useState<Date>(new Date());
  const [selectedDay, setSelectedDay] = useState<string>(toInputDate(new Date()));
  // Фильтр календаря по пабликам: уходит в запрос, поэтому живёт здесь,
  // а не внутри страницы.
  const [selectedPublicIds, setSelectedPublicIds] = useState<string[]>([]);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [infoEvents, setInfoEvents] = useState<ApiInfoEvent[]>([]);
  const [contentEvents, setContentEvents] = useState<ContentEvent[]>([]);
  const [infoEventsImporting, setInfoEventsImporting] = useState(false);
  const [infoEventCreating, setInfoEventCreating] = useState(false);
  const [editingInfoEventId, setEditingInfoEventId] = useState<string | null>(null);
  const [infoEventMessage, setInfoEventMessage] = useState("");
  const [infoEventMessageType, setInfoEventMessageType] = useState<MessageType>(MESSAGE_STATUS.IDLE);
  const [infoEventQuery, setInfoEventQuery] = useState("");
  const [infoEventSort, setInfoEventSort] = useState<InfoEventSort>(INFO_EVENT_SORT.EVENT_DATE_DESC);
  const [selectedInfoEventId, setSelectedInfoEventId] = useState<string | null>(null);
  const [infoEventForm, setInfoEventForm] = useState<InfoEventForm>(() => defaultInfoEventForm());
  const [contentMessage, setContentMessage] = useState("");
  const [contentMessageType, setContentMessageType] = useState<MessageType>(MESSAGE_STATUS.IDLE);
  const [editingEventId, setEditingEventId] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [authMessage, setAuthMessage] = useState("");
  const [authMessageType, setAuthMessageType] = useState<MessageType>(MESSAGE_STATUS.IDLE);
  const [authLoading, setAuthLoading] = useState(false);
  const [authToken, setAuthToken] = useState<string>(() => getStoredToken());
  const [currentUser, setCurrentUser] = useState<string>(() => {
    return localStorage.getItem(SESSION_KEY) ?? sessionStorage.getItem(SESSION_KEY) ?? "";
  });
  const [eventTitle, setEventTitle] = useState("Планёрка медиакоманды");
  const [eventDate, setEventDate] = useState("");
  const [eventTime, setEventTime] = useState("10:00");
  const [eventDescription, setEventDescription] = useState("Событие медиахаба");
  const [eventStatus, setEventStatus] = useState<EventStatus>(EVENT_STATUS.SCHEDULED);
  const [eventPlatforms, setEventPlatforms] = useState<string[]>([]);
  const [eventDraft, setEventDraft] = useState("");
  const [eventTone, setEventTone] = useState("");
  const [eventPostType, setEventPostType] = useState("");
  const [eventInfoEventId, setEventInfoEventId] = useState<string | null>(null);
  const [eventSeriesCount, setEventSeriesCount] = useState(1);
  const [eventSeriesStepMinutes, setEventSeriesStepMinutes] = useState(5);
  const [eventSeriesItems, setEventSeriesItems] = useState<SeriesPlanItem[]>([]);
  const [calendarGenerating, setCalendarGenerating] = useState(false);
  const [calendarGenerationProgress, setCalendarGenerationProgress] = useState(0);
  const [calendarMessage, setCalendarMessage] = useState("");
  const [calendarMessageType, setCalendarMessageType] = useState<MessageType>(MESSAGE_STATUS.IDLE);
  const [smartEventOpen, setSmartEventOpen] = useState(false);
  const [smartEntryMode, setSmartEntryMode] = useState<SmartEntryMode>("content");
  const [smartTitle, setSmartTitle] = useState("");
  const [smartPrompt, setSmartPrompt] = useState("");
  const [smartTone, setSmartTone] = useState("");
  const [smartPostType, setSmartPostType] = useState("");
  const [smartSourceEventId, setSmartSourceEventId] = useState("");
  const [smartEventDate, setSmartEventDate] = useState("");
  const [smartPlatforms, setSmartPlatforms] = useState<string[]>([]);
  const [contentPublishTargets, setContentPublishTargets] = useState<Record<string, string>>({});
  const [smartScheduleEnabled, setSmartScheduleEnabled] = useState(false);
  const [smartScheduleDate, setSmartScheduleDate] = useState("");
  const [smartScheduleTime, setSmartScheduleTime] = useState("10:00");
  const [smartGenerated, setSmartGenerated] = useState("");
  const [smartLlmLoading, setSmartLlmLoading] = useState(false);
  const [smartMessage, setSmartMessage] = useState("");
  const [smartMessageType, setSmartMessageType] = useState<MessageType>(MESSAGE_STATUS.IDLE);
  const [smartPainId, setSmartPainId] = useState("");
  const [smartStrategyId, setSmartStrategyId] = useState("");
  const [smartPainDetail, setSmartPainDetail] = useState<PainDetail | null>(null);
  const [smartImageFile, setSmartImageFile] = useState<File | null>(null);
  const [smartImagePreview, setSmartImagePreview] = useState<string | null>(null);
  const smartFileInputRef = useRef<HTMLInputElement | null>(null);
  const infoImportInputRef = useRef<HTMLInputElement | null>(null);
  const [publishToVk, setPublishToVk] = useState(false);
  const [vkPublishing, setVkPublishing] = useState(false);
  const [publishingItemId, setPublishingItemId] = useState<string | null>(null);
  const [deletingVkItemId, setDeletingVkItemId] = useState<string | null>(null);
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === THEME.DARK_RED ? THEME.DARK_RED : THEME.LIGHT_BLUE;
  });
  const [themeToggleMode, setThemeToggleMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === THEME.DARK_RED ? THEME.DARK_RED : THEME.LIGHT_BLUE;
  });
  const [reportPlatform, setReportPlatform] = useState<ReportPlatform>(REPORT_PLATFORM.VK);
  const [reportSourceId, setReportSourceId] = useState<string | null>(null);
  const [reportMunicipalityName, setReportMunicipalityName] = useState<string | null>(null);
  // Неделя по умолчанию: срез за свежий период отвечает на «что происходит
  // сейчас». Полная история остаётся в селекте периода.
  const [reportPeriod, setReportPeriod] = useState<ReportPeriod>(REPORT_PERIOD.WEEK);
  const [reportLoading, setReportLoading] = useState(false);
  const [deepLlmAnalysis, setDeepLlmAnalysis] = useState(() => readAnalyticsSettings().deepLlmAnalysis);
  const [prefilterEnabled, setPrefilterEnabled] = useState(() => readAnalyticsSettings().prefilterEnabled);
  const [selectedChartRange, setSelectedChartRange] = useState<{ from: string; to: string } | null>(null);
  const [chartPostsSort, setChartPostsSort] = useState<"views_desc" | "views_asc" | "date_desc" | "date_asc">("views_desc");
  const [chartPostsLimit, setChartPostsLimit] = useState(10);
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set());
  const [reportPdfLoading, setReportPdfLoading] = useState(false);
  const [reportMessage, setReportMessage] = useState("");
  const [reportMessageType, setReportMessageType] = useState<MessageType>(MESSAGE_STATUS.IDLE);
  const [serverToastMessage, setServerToastMessage] = useState("");
  const [selectedPainId, setSelectedPainId] = useState<string | null>(null);
  const [painEventPickerOpen, setPainEventPickerOpen] = useState(false);
  const [painEventPickerQuery, setPainEventPickerQuery] = useState("");
  const [painSeverityFilter, setPainSeverityFilter] = useState<PainSeverityFilter>(PAIN_SEVERITY_FILTER.ALL);
  const [strategyRegenLoading, setStrategyRegenLoading] = useState<string | null>(null);
  const [strategyRegenError, setStrategyRegenError] = useState<string | null>(null);
  const [eventPainPickerOpen, setEventPainPickerOpen] = useState(false);
  const [selectedSubproblemTitle, setSelectedSubproblemTitle] = useState<string | null>(null);
  const PAGE_SIZE = PAIN_COMMENTS_PAGE_SIZE;
  const [analyticsView, setAnalyticsView] = useState<AnalyticsView>(ANALYTICS_VIEW.PAINS);
  const [analyticsJob, setAnalyticsJob] = useState<JobInfo | null>(null);
  const ANALYTICS_JOB_KEY = "media-events:active-analytics-job";
  const [themeAnimating, setThemeAnimating] = useState(false);
  const [themeSwitching, setThemeSwitching] = useState(false);
  const initialAuthPromptedRef = useRef(false);
  const calendarReloadSeqRef = useRef(0);
  const contentReloadSeqRef = useRef(0);
  const deletedPostIdsRef = useRef<Set<string>>(new Set());
  const serverToastSeqRef = useRef(0);
  const setTimeoutSafe = useUnmountTimeoutSafe();
  const [moduleName, setModuleName] = useState("");
  const [moduleGoal, setModuleGoal] = useState("");
  const [moduleDescription, setModuleDescription] = useState("");
  const [moduleLoading, setModuleLoading] = useState(false);
  const [moduleNameFocused, setModuleNameFocused] = useState(false);

  return {
    authModalOpen,
    setAuthModalOpen,
    calendarModalOpen,
    setCalendarModalOpen,
    infoEventModalOpen,
    setInfoEventModalOpen,
    calendarView,
    setCalendarView,
    calendarDate,
    setCalendarDate,
    selectedDay,
    selectedPublicIds,
    setSelectedPublicIds,
    setSelectedDay,
    events,
    setEvents,
    infoEvents,
    setInfoEvents,
    contentEvents,
    setContentEvents,
    infoEventsImporting,
    setInfoEventsImporting,
    infoEventCreating,
    setInfoEventCreating,
    editingInfoEventId,
    setEditingInfoEventId,
    infoEventMessage,
    setInfoEventMessage,
    infoEventMessageType,
    setInfoEventMessageType,
    infoEventQuery,
    setInfoEventQuery,
    infoEventSort,
    setInfoEventSort,
    selectedInfoEventId,
    setSelectedInfoEventId,
    infoEventForm,
    setInfoEventForm,
    contentMessage,
    setContentMessage,
    contentMessageType,
    setContentMessageType,
    editingEventId,
    setEditingEventId,
    authMode,
    setAuthMode,
    email,
    setEmail,
    password,
    setPassword,
    showPassword,
    setShowPassword,
    rememberMe,
    setRememberMe,
    authMessage,
    setAuthMessage,
    authMessageType,
    setAuthMessageType,
    authLoading,
    setAuthLoading,
    authToken,
    setAuthToken,
    currentUser,
    setCurrentUser,
    eventTitle,
    setEventTitle,
    eventDate,
    setEventDate,
    eventTime,
    setEventTime,
    eventDescription,
    setEventDescription,
    eventStatus,
    setEventStatus,
    eventPlatforms,
    setEventPlatforms,
    eventDraft,
    setEventDraft,
    eventTone,
    setEventTone,
    eventPostType,
    setEventPostType,
    eventInfoEventId,
    setEventInfoEventId,
    eventSeriesCount,
    setEventSeriesCount,
    eventSeriesStepMinutes,
    setEventSeriesStepMinutes,
    eventSeriesItems,
    setEventSeriesItems,
    calendarGenerating,
    setCalendarGenerating,
    calendarGenerationProgress,
    setCalendarGenerationProgress,
    calendarMessage,
    setCalendarMessage,
    calendarMessageType,
    setCalendarMessageType,
    smartEventOpen,
    setSmartEventOpen,
    smartEntryMode,
    setSmartEntryMode,
    smartTitle,
    setSmartTitle,
    smartPrompt,
    setSmartPrompt,
    smartTone,
    setSmartTone,
    smartPostType,
    setSmartPostType,
    smartSourceEventId,
    setSmartSourceEventId,
    smartEventDate,
    setSmartEventDate,
    smartPlatforms,
    setSmartPlatforms,
    contentPublishTargets,
    setContentPublishTargets,
    smartScheduleEnabled,
    setSmartScheduleEnabled,
    smartScheduleDate,
    setSmartScheduleDate,
    smartScheduleTime,
    setSmartScheduleTime,
    smartGenerated,
    setSmartGenerated,
    smartLlmLoading,
    setSmartLlmLoading,
    smartMessage,
    setSmartMessage,
    smartMessageType,
    setSmartMessageType,
    smartPainId,
    setSmartPainId,
    smartStrategyId,
    setSmartStrategyId,
    smartPainDetail,
    setSmartPainDetail,
    smartImageFile,
    setSmartImageFile,
    smartImagePreview,
    setSmartImagePreview,
    smartFileInputRef,
    infoImportInputRef,
    publishToVk,
    setPublishToVk,
    vkPublishing,
    setVkPublishing,
    publishingItemId,
    setPublishingItemId,
    deletingVkItemId,
    setDeletingVkItemId,
    themeMode,
    setThemeMode,
    themeToggleMode,
    setThemeToggleMode,
    reportPlatform,
    setReportPlatform,
    reportSourceId,
    setReportSourceId,
    reportMunicipalityName,
    setReportMunicipalityName,
    reportPeriod,
    setReportPeriod,
    reportLoading,
    setReportLoading,
    deepLlmAnalysis,
    setDeepLlmAnalysis,
    prefilterEnabled,
    setPrefilterEnabled,
    selectedChartRange,
    setSelectedChartRange,
    chartPostsSort,
    setChartPostsSort,
    chartPostsLimit,
    setChartPostsLimit,
    expandedCases,
    setExpandedCases,
    reportPdfLoading,
    setReportPdfLoading,
    reportMessage,
    setReportMessage,
    reportMessageType,
    setReportMessageType,
    serverToastMessage,
    setServerToastMessage,
    selectedPainId,
    setSelectedPainId,
    painEventPickerOpen,
    setPainEventPickerOpen,
    painEventPickerQuery,
    setPainEventPickerQuery,
    painSeverityFilter,
    setPainSeverityFilter,
    strategyRegenLoading,
    setStrategyRegenLoading,
    strategyRegenError,
    setStrategyRegenError,
    eventPainPickerOpen,
    setEventPainPickerOpen,
    selectedSubproblemTitle,
    setSelectedSubproblemTitle,
    PAGE_SIZE,
    analyticsView,
    setAnalyticsView,
    analyticsJob,
    setAnalyticsJob,
    ANALYTICS_JOB_KEY,
    themeAnimating,
    setThemeAnimating,
    themeSwitching,
    setThemeSwitching,
    initialAuthPromptedRef,
    calendarReloadSeqRef,
    contentReloadSeqRef,
    deletedPostIdsRef,
    serverToastSeqRef,
    setTimeoutSafe,
    moduleName,
    setModuleName,
    moduleGoal,
    setModuleGoal,
    moduleDescription,
    setModuleDescription,
    moduleLoading,
    setModuleLoading,
    moduleNameFocused,
    setModuleNameFocused,
  };
}
