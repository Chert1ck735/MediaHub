import { useMemo } from "react";

/** Сколько публикаций дня приходит для ячейки месяца. */
const CALENDAR_CELL_EVENTS = 3;
import { useQueryClient } from "@tanstack/react-query";

import type { ApiInfoEvent } from "../api";
import { messageTypeLabel, relevanceLabel, sentimentLabel } from "../app/constants";
import { buildBarItems, formatChartDate, formatMetricValue, stripVkMentions, startOfWeek, parseInputDate } from "../app/utils";
import { INFO_EVENT_SORT } from "../constants";
import type { CalendarEvent, ContentEvent, ReportPeriod, ReportPlatform } from "../app/types";
import type { InfoEventSort } from "../constants";
import { useAnalyticsSummary } from "../hooks/useAnalyticsSummary";
import { useCalendarEvents, useCalendarDayEvents } from "../hooks/useCalendarEvents";
import { useDefaultVkPublic } from "../hooks/useDefaultVkPublic";
import { useEventPains } from "../hooks/useEventPains";
import { useEvents } from "../hooks/useEvents";
import { useMe } from "../hooks/useMe";
import { useModules } from "../hooks/useModules";
import { useOrganizations } from "../hooks/useOrganizations";
import { usePainComments } from "../hooks/usePainComments";
import { usePainDetail } from "../hooks/usePainDetail";
import { usePainEvents } from "../hooks/usePainEvents";
import { usePainList } from "../hooks/usePainList";
import { usePainTrends } from "../hooks/usePainTrends";
import { usePosts } from "../hooks/usePosts";
import { useReportPreview } from "../hooks/useReportPreview";

type Args = {
  pathname: string;
  authToken: string;
  currentUser: string;
  reportPeriod: ReportPeriod;
  reportSourceId: string | null;
  reportMunicipalityName: string | null;
  selectedPainId: string | null;
  selectedInfoEventId: string | null;
  selectedSubproblemTitle: string | null;
  smartPainId: string;
  smartSourceEventId: string;
  PAGE_SIZE: number;
  reportPlatform: ReportPlatform;
  chartPostsSort: "views_desc" | "views_asc" | "date_desc" | "date_asc";
  selectedChartRange: { from: string; to: string } | null;
  events: CalendarEvent[];
  contentEvents: ContentEvent[];
  infoEvents: ApiInfoEvent[];
  infoEventQuery: string;
  infoEventSort: InfoEventSort;
  moduleName: string;
  calendarDate?: Date;
  selectedDay?: string;
  selectedPublicIds?: string[];
};

export function useAppShellData({
  pathname,
  authToken,
  currentUser,
  reportPeriod,
  reportSourceId,
  reportMunicipalityName,
  selectedPainId,
  selectedInfoEventId,
  selectedSubproblemTitle,
  smartPainId,
  smartSourceEventId,
  PAGE_SIZE,
  reportPlatform,
  chartPostsSort,
  selectedChartRange,
  events,
  contentEvents,
  infoEvents,
  infoEventQuery,
  infoEventSort,
  moduleName,
  calendarDate,
  selectedDay,
  selectedPublicIds,
}: Args) {
  const queryClient = useQueryClient();
  const isCalendarRoute = pathname === "/calendar" || pathname === "/calendar/";
  const calendarToken = isCalendarRoute ? authToken : null;
  const backgroundToken = isCalendarRoute ? null : authToken;
  const meQuery = useMe(authToken && !currentUser ? authToken : null);
  const organizationsQuery = useOrganizations(authToken);
  const postsQuery = usePosts(backgroundToken);
  // Границы показываемого периода с запасом в неделю: в сетке месяца видны
  // хвосты соседних месяцев, и без запаса они были бы пустыми.
  const [calendarFrom, calendarTo] = useMemo(() => {
    const base = calendarDate ?? new Date();
    const from = startOfWeek(new Date(base.getFullYear(), base.getMonth(), 1));
    const to = new Date(from);
    to.setDate(to.getDate() + 42);
    to.setMilliseconds(-1);
    return [from.toISOString(), to.toISOString()];
  }, [calendarDate]);
  // Сетке месяца хватает пары записей на день: их видно в ячейке, остальное
  // прячется под «+N ещё». Иначе за месяц пришлось бы тянуть десятки тысяч.
  const calendarEventsQuery = useCalendarEvents(
    calendarToken, calendarFrom, calendarTo, CALENDAR_CELL_EVENTS, selectedPublicIds,
  );
  // Открытый день грузим целиком — под сеткой показывается его список.
  const [dayFrom, dayTo] = useMemo(() => {
    if (!selectedDay) return [null, null];
    const from = parseInputDate(selectedDay);
    const to = new Date(from);
    to.setDate(to.getDate() + 1);
    to.setMilliseconds(-1);
    return [from.toISOString(), to.toISOString()];
  }, [selectedDay]);
  const calendarDayQuery = useCalendarDayEvents(calendarToken, dayFrom, dayTo, selectedPublicIds);
  const calendarDayEvents = useMemo(() => calendarDayQuery.data?.pages.flat() ?? [], [calendarDayQuery.data]);
  const infoEventsQuery = useEvents(authToken);
  const modulesQuery = useModules(authToken);
  const defaultVkPublicQuery = useDefaultVkPublic(authToken);
  const analyticsSummaryQuery = useAnalyticsSummary(backgroundToken, reportPeriod, reportSourceId, reportMunicipalityName);
  const painListQuery = usePainList(backgroundToken, reportPeriod, reportSourceId, reportMunicipalityName);
  const painTrendsQuery = usePainTrends(backgroundToken, reportPeriod, reportSourceId, reportMunicipalityName);
  const painDetailQuery = usePainDetail(
    backgroundToken,
    selectedPainId,
    reportSourceId,
    reportPeriod,
    reportMunicipalityName,
  );
  const smartPainDetailQuery = usePainDetail(
    authToken,
    smartPainId || null,
    reportSourceId,
    reportPeriod,
    reportMunicipalityName,
  );
  const painEventsQuery = usePainEvents(authToken, selectedPainId);
  const eventPainsQuery = useEventPains(authToken, selectedInfoEventId);
  const painCommentsQuery = usePainComments(authToken, selectedPainId, {
    subcategory: selectedSubproblemTitle,
    sourceId: reportSourceId,
    municipalityName: reportMunicipalityName,
    period: reportPeriod,
    limit: PAGE_SIZE,
  });
  const reportPreviewQuery = useReportPreview(
    backgroundToken,
    reportPlatform,
    reportSourceId,
    reportPeriod,
    reportMunicipalityName,
    true,
  );

  const authTitle = "Вход";
  const reportSourcesData = authToken ? organizationsQuery.data ?? [] : [];
  const reportSourcesLoadingState = organizationsQuery.isFetching;
  const modulesData = authToken ? modulesQuery.data ?? [] : [];
  const defaultVkPublicLinkIdData = authToken ? defaultVkPublicQuery.data?.public_social_link_id ?? null : null;
  const analyticsSummaryData = authToken ? analyticsSummaryQuery.data ?? null : null;
  const painItemsData = authToken ? painListQuery.data ?? [] : [];
  const painTrendsData = useMemo(
    () => Object.fromEntries((painTrendsQuery.data ?? []).map((item) => [item.pain_id, item.counts])),
    [painTrendsQuery.data],
  );
  const selectedPainDetailData = authToken ? painDetailQuery.data ?? null : null;
  const painEventsData = authToken ? painEventsQuery.data ?? [] : [];
  const eventPainsData = authToken ? eventPainsQuery.data ?? [] : [];
  const paginatedCommentsData = useMemo(
    () => painCommentsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [painCommentsQuery.data],
  );
  const paginatedTotalData = painCommentsQuery.data?.pages[0]?.total ?? 0;
  const paginatedLoadingState = painCommentsQuery.isFetching;
  const reportPreviewData = reportPreviewQuery.data ?? null;
  const dataLoadingState = Boolean(authToken) && (
    postsQuery.isLoading ||
    calendarEventsQuery.isLoading ||
    infoEventsQuery.isLoading ||
    modulesQuery.isLoading ||
    defaultVkPublicQuery.isLoading ||
    analyticsSummaryQuery.isLoading ||
    painListQuery.isLoading ||
    painTrendsQuery.isLoading
  );
  // Общий флаг выше ждёт любой из восьми запросов, поэтому раздел стоит из-за
  // чужих данных. Ниже — флаги по разделам, каждый ждёт только своё.
  const contentLoading = Boolean(authToken) && postsQuery.isLoading;
  const analyticsPageLoading = Boolean(authToken) && (
    analyticsSummaryQuery.isLoading || painListQuery.isLoading || painTrendsQuery.isLoading
  );
  const calendarPageLoading = Boolean(authToken) && (
    calendarEventsQuery.isLoading
  );
  // Переключение месяца и открытие дня идут поверх показанных данных:
  // isLoading при этом не поднимается, а ждать пользователю приходится.
  const calendarFetching = Boolean(authToken) && (
    calendarEventsQuery.isFetching || calendarDayQuery.isFetching
  );
  const analyticsLoadingState =
    analyticsSummaryQuery.isFetching || painListQuery.isFetching || painTrendsQuery.isFetching;
  const infoEventsLoadingState = infoEventsQuery.isFetching;
  const infoEventsLoading = infoEventsLoadingState;
  const dataLoading = dataLoadingState;
  const analyticsLoading = analyticsLoadingState;
  const modulesList = modulesData;
  const defaultVkPublicLinkId = defaultVkPublicLinkIdData;
  const painTrends = painTrendsData;
  const selectedPainDetail = authToken && selectedPainId ? selectedPainDetailData : null;
  const painEvents = authToken && selectedPainId ? painEventsData : [];
  const eventPains = authToken && selectedInfoEventId ? eventPainsData : [];
  const paginatedComments = authToken && selectedPainId ? paginatedCommentsData : [];
  const paginatedTotal = authToken && selectedPainId ? paginatedTotalData : 0;
  const paginatedLoading =
    Boolean(authToken && selectedPainId) && (paginatedLoadingState || painCommentsQuery.isFetchingNextPage);
  const reportPreview = reportPreviewData;
  const reportPreviewFetching = reportPreviewQuery.isFetching;
  const refetchReportPreview = reportPreviewQuery.refetch;

  const analyticsSentimentBars = useMemo(() => {
    if (!analyticsSummaryData) return [];
    return buildBarItems([
      { key: "positive", label: sentimentLabel.positive, count: analyticsSummaryData.sentiment_breakdown.positive, accent: "success" },
      { key: "neutral", label: sentimentLabel.neutral, count: analyticsSummaryData.sentiment_breakdown.neutral, accent: "neutral" },
      { key: "negative", label: sentimentLabel.negative, count: analyticsSummaryData.sentiment_breakdown.negative, accent: "critical" },
    ]);
  }, [analyticsSummaryData]);

  const analyticsRelevanceBars = useMemo(() => {
    if (!analyticsSummaryData) return [];
    return buildBarItems([
      { key: "relevant", label: relevanceLabel.relevant, count: analyticsSummaryData.relevance_breakdown.relevant, accent: "accent" },
      { key: "irrelevant", label: relevanceLabel.irrelevant, count: analyticsSummaryData.relevance_breakdown.irrelevant, accent: "neutral" },
    ]);
  }, [analyticsSummaryData]);

  const analyticsMessageTypeBars = useMemo(() => {
    if (!analyticsSummaryData) return [];
    return buildBarItems([
      // числа считает бэкенд одним определением; здесь не суммировать
      // красный/зелёный зарезервированы за тональностью — типы нейтральным синим
      { key: "appeal", label: "Обращения", count: analyticsSummaryData.appeal_count, accent: "neutral" },
      { key: "gratitude", label: messageTypeLabel.gratitude, count: analyticsSummaryData.gratitude_count, accent: "neutral" },
      { key: "other", label: "Прочее", count: analyticsSummaryData.other_count, accent: "neutral" },
    ]);
  }, [analyticsSummaryData]);

  const analyticsCategoryBars = useMemo(() => {
    if (!analyticsSummaryData) return [];
    const items = analyticsSummaryData.category_breakdown.slice(0, 6);
    const maxCount = items.reduce((max: number, item: any) => Math.max(max, item.count), 0) || 1;
    return items.map((item: any, index: number) => {
      const neg = item.negative_count ?? 0;
      const neu = item.neutral_count ?? 0;
      const pos = item.positive_count ?? 0;
      const total = neg + neu + pos || item.count;
      const negPct = total ? Math.round((neg / total) * 100) : 0;
      return {
        key: `${item.category}-${index}`,
        label: item.category,
        count: item.count,
        widthPct: Math.round((item.count / maxCount) * 100),
        negPct: total ? (neg / total) * 100 : 0,
        neuPct: total ? (neu / total) * 100 : 0,
        posPct: total ? (pos / total) * 100 : 100,
        negativeShare: negPct,
      };
    });
  }, [analyticsSummaryData]);

  const selectedSubproblem = useMemo(() => {
    if (!selectedPainDetail?.subproblem_items?.length) return null;
    // null = чип «Все»: показываем комментарии всей боли, без фильтра подкатегории
    if (!selectedSubproblemTitle) return null;
    return selectedPainDetail.subproblem_items.find((item: any) => item.title === selectedSubproblemTitle) ?? null;
  }, [selectedPainDetail, selectedSubproblemTitle]);

  const homeUpcomingEvents = useMemo(() => {
    return [...events]
      .sort((left, right) => {
        const leftDate = new Date(`${left.date}T${left.startTime}:00`).getTime();
        const rightDate = new Date(`${right.date}T${right.startTime}:00`).getTime();
        return leftDate - rightDate;
      })
      .slice(0, 4);
  }, [events]);

  const homeRecentContent = useMemo(() => {
    return [...contentEvents]
      .sort((left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime())
      .slice(0, 4);
  }, [contentEvents]);

  const filteredInfoEvents = useMemo(() => {
    const query = infoEventQuery.trim().toLowerCase();
    const filtered = !query
      ? infoEvents
      : infoEvents.filter((item) =>
          [item.title, item.description ?? "", item.location ?? ""].join(" ").toLowerCase().includes(query)
        );
    return [...filtered].sort((left, right) => {
      const leftTime = new Date(left.event_date).getTime();
      const rightTime = new Date(right.event_date).getTime();
      const safeLeft = Number.isNaN(leftTime) ? 0 : leftTime;
      const safeRight = Number.isNaN(rightTime) ? 0 : rightTime;
      return infoEventSort === INFO_EVENT_SORT.EVENT_DATE_ASC ? safeLeft - safeRight : safeRight - safeLeft;
    });
  }, [infoEventQuery, infoEvents, infoEventSort]);

  const selectedInfoEvent = useMemo(() => {
    if (!selectedInfoEventId) return filteredInfoEvents[0] ?? infoEvents[0] ?? null;
    return infoEvents.find((item) => item.id === selectedInfoEventId) ?? filteredInfoEvents[0] ?? infoEvents[0] ?? null;
  }, [filteredInfoEvents, infoEvents, selectedInfoEventId]);

  const selectedSmartSourceEvent = useMemo(() => {
    if (!smartSourceEventId) return null;
    return infoEvents.find((item) => item.id === smartSourceEventId) ?? null;
  }, [infoEvents, smartSourceEventId]);

  const infoEventStats = useMemo(() => {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const endOfToday = startOfToday + 24 * 60 * 60 * 1000;
    const endOfWeek = startOfToday + 7 * 24 * 60 * 60 * 1000;
    let today = 0;
    let week = 0;
    for (const eventItem of infoEvents) {
      const eventTime = new Date(eventItem.event_date).getTime();
      if (Number.isNaN(eventTime)) continue;
      if (eventTime >= startOfToday && eventTime < endOfToday) today += 1;
      if (eventTime >= startOfToday && eventTime < endOfWeek) week += 1;
    }
    return [
      { label: "Сегодня", count: today },
      { label: "За неделю", count: week },
      { label: "Всего", count: infoEvents.length },
    ];
  }, [infoEvents]);

  const homeRiskHighlights = useMemo(() => {
    if (!analyticsSummaryData) return [];
    return analyticsSummaryData.top_pains.slice(0, 4);
  }, [analyticsSummaryData]);

  const homeQuickWins = useMemo(() => {
    if (!painItemsData.length) return [];
    return painItemsData.flatMap((item) => item.comment_examples.map((example: any) => stripVkMentions(example.text))).slice(0, 4);
  }, [painItemsData]);

  const reportTopPosts = useMemo(() => reportPreview?.top_posts.slice(0, 5) ?? [], [reportPreview]);
  const chartRangePosts = useMemo(() => {
    if (!selectedChartRange || !reportPreview) return [];
    const from = selectedChartRange.from.substring(0, 10);
    const to = selectedChartRange.to.substring(0, 10);
    const list = (reportPreview.all_posts ?? []).filter((post: any) => {
      const date = (post.date ?? "").substring(0, 10);
      return date && date >= from && date <= to;
    });
    const byViews = (a: any, b: any) => (a.views || 0) - (b.views || 0);
    const byDate = (a: any, b: any) =>
      (a.date ?? "") < (b.date ?? "") ? -1 : (a.date ?? "") > (b.date ?? "") ? 1 : 0;
    return list.sort((a: any, b: any) => {
      switch (chartPostsSort) {
        case "views_asc": return byViews(a, b);
        case "date_desc": return byDate(b, a);
        case "date_asc": return byDate(a, b);
        default: return byViews(b, a);
      }
    });
  }, [selectedChartRange, reportPreview, chartPostsSort]);
  const reportAllPostsSorted = useMemo(() => {
    if (!reportPreview) return [];
    const list = [...(reportPreview.all_posts ?? [])];
    const byViews = (a: any, b: any) => (a.views || 0) - (b.views || 0);
    const byDate = (a: any, b: any) =>
      (a.date ?? "") < (b.date ?? "") ? -1 : (a.date ?? "") > (b.date ?? "") ? 1 : 0;
    return list.sort((a: any, b: any) => {
      switch (chartPostsSort) {
        case "views_asc": return byViews(a, b);
        case "date_desc": return byDate(b, a);
        case "date_asc": return byDate(a, b);
        default: return byViews(b, a);
      }
    });
  }, [reportPreview, chartPostsSort]);

  const reportDateRange = useMemo(() => {
    const points = reportPreview?.points ?? [];
    if (!points.length) return "Даты публикаций не определены";
    const first = points[0];
    const last = points[points.length - 1];
    return `${formatChartDate(first.date)} — ${formatChartDate(last.date)}`;
  }, [reportPreview]);

  const reportMetricTotals = useMemo(() => {
    if (!reportPreview) return null;
    const posts = reportPreview.total_posts || 0;
    const points = reportPreview.points ?? [];
    const hasPoints = points.length > 0;
    const hasLikes = points.some((point) => point.likes != null) || reportPreview.avg_likes != null;
    const hasComments = points.some((point) => point.comments != null) || reportPreview.avg_comments != null;
    return {
      views: hasPoints
        ? points.reduce((sum, point) => sum + (point.views || 0), 0)
        : Math.round((reportPreview.avg_views || 0) * posts),
      likes: hasPoints
        ? points.reduce((sum, point) => sum + (point.likes || 0), 0)
        : reportPreview.avg_likes != null
          ? Math.round(reportPreview.avg_likes * posts)
          : null,
      comments: hasPoints
        ? points.reduce((sum, point) => sum + (point.comments || 0), 0)
        : reportPreview.avg_comments != null
          ? Math.round(reportPreview.avg_comments * posts)
          : null,
      hasLikes,
      hasComments,
    };
  }, [reportPreview]);

  const reportAverageEngagement = useMemo(() => {
    if (!reportMetricTotals || reportMetricTotals.views <= 0) return null;
    const interactions = (reportMetricTotals.likes ?? 0) + (reportMetricTotals.comments ?? 0);
    if (interactions <= 0) return null;
    return Number(((interactions / reportMetricTotals.views) * 100).toFixed(1));
  }, [reportMetricTotals]);

  const reportTrend = useMemo(() => {
    const points = reportPreview?.points ?? [];
    if (points.length < 2) return null;
    const values = points.map((point) => point.views);
    const splitIndex = Math.max(1, Math.floor(values.length / 2));
    const left = values.slice(0, splitIndex);
    const right = values.slice(splitIndex);
    if (!left.length || !right.length) return null;
    const leftAvg = left.reduce((sum, value) => sum + value, 0) / left.length;
    const rightAvg = right.reduce((sum, value) => sum + value, 0) / right.length;
    const diff = rightAvg - leftAvg;
    const pct = leftAvg > 0 ? Number(((diff / leftAvg) * 100).toFixed(1)) : null;
    if (Math.abs(diff) < 1) return { label: "Стабильно", tone: "steady", pct };
    if (diff > 0) return { label: "Рост охвата", tone: "up", pct };
    return { label: "Снижение охвата", tone: "down", pct };
  }, [reportPreview]);

  const reportOverviewCards = useMemo(() => {
    if (!reportPreview) return [];
    const posts = reportPreview.total_posts || 0;
    const totalViews = reportMetricTotals?.views ?? 0;
    const totalLikes = reportMetricTotals?.hasLikes ? reportMetricTotals.likes : null;
    const totalComments = reportMetricTotals?.hasComments ? reportMetricTotals.comments : null;
    const cards = [
      { label: "Постов в выборке", value: formatMetricValue(posts), accent: "accent" },
      { label: "Всего просмотров", value: formatMetricValue(totalViews), accent: "neutral" },
    ];
    if (totalLikes != null) {
      cards.push({ label: "Всего лайков", value: formatMetricValue(totalLikes), accent: "success" });
    }
    if (totalComments != null) {
      cards.push({ label: "Всего комментариев", value: formatMetricValue(totalComments), accent: "info" });
    }
    if (reportPreview.group_members != null) {
      cards.push({ label: "Подписчиков", value: formatMetricValue(reportPreview.group_members), accent: "success" });
    }
    if (reportAverageEngagement != null) {
      cards.push({ label: "Средний ER по реакциям", value: `${formatMetricValue(reportAverageEngagement)}%`, accent: "accent" });
    }
    return cards;
  }, [reportAverageEngagement, reportMetricTotals, reportPreview]);

  const reportSourceOptions = useMemo(() => {
    const options: Array<{ id: string; label: string; platform: string; platformLabel: string }> = [];
    for (const publicItem of reportSourcesData) {
      for (const link of publicItem.links) {
        const platform = (link.social_network_code || "unknown").toLowerCase();
        options.push({
          id: link.id,
          label: `${publicItem.name}${link.url ? ` (${link.url.replace(/^https?:\/\//, "")})` : ""}`,
          platform,
          platformLabel: link.social_network_name || link.social_network_code || platform,
        });
      }
    }
    return options;
  }, [reportSourcesData]);

  const reportPlatformOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const option of reportSourceOptions) {
      if (!option.platform || option.platform === "unknown") continue;
      if (!seen.has(option.platform)) {
        seen.set(option.platform, option.platformLabel);
      }
    }
    return Array.from(seen, ([code, label]) => ({ code, label }));
  }, [reportSourceOptions]);

  const modulePublicNames = useMemo(
    () =>
      Array.from(
        new Set(
          reportSourcesData
            .map((item) => item.name.trim())
            .filter(Boolean),
        ),
      ).sort((left, right) => left.localeCompare(right, "ru")),
    [reportSourcesData],
  );

  const normalizedModuleName = moduleName.trim();
  const moduleNameMatchesPublic = modulePublicNames.includes(normalizedModuleName);
  const moduleNameSuggestions = useMemo(() => {
    if (!normalizedModuleName) {
      return modulePublicNames.slice(0, 5);
    }
    const query = normalizedModuleName.toLocaleLowerCase("ru");
    return modulePublicNames
      .filter((name) => name.toLocaleLowerCase("ru").includes(query))
      .slice(0, 5);
  }, [modulePublicNames, normalizedModuleName]);
  const publicationTargetOptions = reportSourceOptions;

  return {
    queryClient,
    meQuery,
    organizationsQuery,
    postsQuery,
    calendarEventsQuery,
    calendarDayQuery,
    calendarDayEvents,
    infoEventsQuery,
    modulesQuery,
    defaultVkPublicQuery,
    analyticsSummaryQuery,
    painListQuery,
    painTrendsQuery,
    painDetailQuery,
    smartPainDetailQuery,
    painEventsQuery,
    eventPainsQuery,
    painCommentsQuery,
    reportPreviewQuery,
    authTitle,
    infoEventsLoading,
    dataLoading,
    contentLoading,
    analyticsPageLoading,
    calendarPageLoading,
    calendarFetching,
    analyticsLoading,
    reportSources: reportSourcesData,
    reportSourcesLoading: reportSourcesLoadingState,
    modulesList,
    defaultVkPublicLinkId,
    analyticsSummary: analyticsSummaryData,
    painItems: painItemsData,
    painTrends,
    selectedPainDetail,
    painEvents,
    eventPains,
    paginatedComments,
    paginatedTotal,
    paginatedLoading,
    reportPreview,
    analyticsSentimentBars,
    analyticsRelevanceBars,
    analyticsMessageTypeBars,
    analyticsCategoryBars,
    selectedSubproblem,
    homeUpcomingEvents,
    homeRecentContent,
    filteredInfoEvents,
    selectedInfoEvent,
    selectedSmartSourceEvent,
    infoEventStats,
    homeRiskHighlights,
    homeQuickWins,
    reportTopPosts,
    chartRangePosts,
    reportAllPostsSorted,
    reportPreviewFetching,
    refetchReportPreview,
    reportDateRange,
    reportAverageEngagement,
    reportTrend,
    reportOverviewCards,
    reportSourceOptions,
    reportPlatformOptions,
    modulePublicNames,
    normalizedModuleName,
    moduleNameMatchesPublic,
    moduleNameSuggestions,
    publicationTargetOptions,
  };
}
