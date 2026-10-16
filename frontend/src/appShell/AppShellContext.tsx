import { createContext, useContext, useEffect, type FormEvent, type ReactNode } from "react";
import type { Location, NavigateFunction } from "react-router-dom";

import { apiCreateModule, JWT_KEY, waitForJob } from "../api";
import { writeAnalyticsSettings } from "../app/analyticsSettings";
import { THEME_KEY } from "../app/constants";
import { apiCalendarEventToCalendarEvent, apiPostToContentEvent } from "../app/mappers";
import { buildSeriesPlanItems } from "../app/utils";
import {
  EVENT_STATUS,
  MESSAGE_STATUS,
  THEME,
  THEME_TRANSITION_MS,
} from "../constants";
import { queryKeys } from "../hooks/queryKeys";
import { onServerError, onTokenExpired } from "../lib/httpClient";
import { loadAnalyticsData as invalidateAnalyticsData } from "./analyticsController";
import { logoutAction, openAuthModal, shouldPromptInitialLogin } from "./authController";
import { TAB_ROUTE_MAP, type AppRouteTab } from "./routeConfig";
import { useAppShellData } from "./useAppShellData";
import { useAppShellState } from "./useAppShellState";

type OpenAuthOptions = { reset?: boolean };

type AppShellContextValue = {
  location: Location;
  navigate: NavigateFunction;
  shellState: ReturnType<typeof useAppShellState>;
  shellData: ReturnType<typeof useAppShellData>;
  openAuth: (mode: "login", options?: OpenAuthOptions) => void;
  navigateToTab: (tab: AppRouteTab) => void;
  logout: () => void;
  handleThemeToggle: () => void;
  handleModuleSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  loadAnalyticsData: (
    token: string,
    period?: string,
    sourceId?: string | null,
    municipalityName?: string | null,
    options?: { silent?: boolean },
  ) => Promise<void>;
  reloadCalendarFromBackend: () => Promise<void>;
  reloadContentFromBackend: () => Promise<void>;
};

const AppShellContext = createContext<AppShellContextValue | null>(null);

type AppShellProviderProps = {
  children: ReactNode;
  location: Location;
  navigate: NavigateFunction;
};

export function AppShellProvider({ children, location, navigate }: AppShellProviderProps) {
  const shellState = useAppShellState();
  const shellData = useAppShellData({
    pathname: location.pathname,
    authToken: shellState.authToken,
    currentUser: shellState.currentUser,
    reportPeriod: shellState.reportPeriod,
    reportSourceId: shellState.reportSourceId,
    reportMunicipalityName: shellState.reportMunicipalityName,
    selectedPainId: shellState.selectedPainId,
    selectedInfoEventId: shellState.selectedInfoEventId,
    selectedSubproblemTitle: shellState.selectedSubproblemTitle,
    smartPainId: shellState.smartPainId,
    smartSourceEventId: shellState.smartSourceEventId,
    PAGE_SIZE: shellState.PAGE_SIZE,
    reportPlatform: shellState.reportPlatform,
    chartPostsSort: shellState.chartPostsSort,
    selectedChartRange: shellState.selectedChartRange,
    events: shellState.events,
    contentEvents: shellState.contentEvents,
    infoEvents: shellState.infoEvents,
    infoEventQuery: shellState.infoEventQuery,
    infoEventSort: shellState.infoEventSort,
    moduleName: shellState.moduleName,
    calendarDate: shellState.calendarDate,
    selectedDay: shellState.selectedDay,
    selectedPublicIds: shellState.selectedPublicIds,
  });

  const openAuth = (mode: "login", options?: OpenAuthOptions) =>
    openAuthModal(mode, options, {
      setAuthMode: shellState.setAuthMode,
      setEmail: shellState.setEmail,
      setPassword: shellState.setPassword,
      setAuthMessage: shellState.setAuthMessage,
      setAuthMessageType: shellState.setAuthMessageType,
      setAuthLoading: shellState.setAuthLoading,
      setAuthToken: shellState.setAuthToken,
      setCurrentUser: shellState.setCurrentUser,
      setAuthModalOpen: shellState.setAuthModalOpen,
      location,
      navigate,
    });

  const navigateToTab = (tab: AppRouteTab) => navigate(TAB_ROUTE_MAP[tab]);

  const logout = () => {
    logoutAction({
      setCurrentUser: shellState.setCurrentUser,
      setAuthToken: shellState.setAuthToken,
      setEvents: shellState.setEvents,
      setInfoEvents: shellState.setInfoEvents,
      setContentEvents: shellState.setContentEvents,
    });
    navigate({ pathname: "/", search: "?auth=login" }, { replace: true });
    openAuth("login");
  };

  const loadAnalyticsData = async (
    token: string,
    period: string = shellState.reportPeriod,
    sourceId: string | null = shellState.reportSourceId,
    municipalityName: string | null = shellState.reportMunicipalityName,
    options: { silent?: boolean } = {},
  ) =>
    invalidateAnalyticsData(
      {
        queryClient: shellData.queryClient,
        reportPeriod: shellState.reportPeriod,
        reportSourceId: shellState.reportSourceId,
        reportMunicipalityName: shellState.reportMunicipalityName,
      },
      token,
      period,
      sourceId,
      municipalityName,
      options,
    );

  const reloadCalendarFromBackend = async () => {
    if (!shellState.authToken) return;
    shellState.calendarReloadSeqRef.current += 1;
    await shellData.queryClient.invalidateQueries({
      queryKey: queryKeys.calendarEventsAll(shellState.authToken),
    });
  };

  const reloadContentFromBackend = async () => {
    if (!shellState.authToken) return;
    shellState.contentReloadSeqRef.current += 1;
    await shellData.queryClient.invalidateQueries({
      queryKey: queryKeys.posts(shellState.authToken),
    });
  };

  const handleModuleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!shellState.authToken) {
      openAuth("login");
      return;
    }
    if (!shellData.moduleNameMatchesPublic) {
      alert("Выберите существующее название паблика из списка.");
      return;
    }
    shellState.setModuleLoading(true);
    try {
      await apiCreateModule(shellState.authToken, {
        name: shellData.normalizedModuleName,
        goal: shellState.moduleGoal,
        description: shellState.moduleDescription,
      });
      await shellData.queryClient.invalidateQueries({
        queryKey: queryKeys.modules(shellState.authToken),
      });
      alert("Модуль успешно создан!");
      shellState.setModuleName("");
      shellState.setModuleNameFocused(false);
      shellState.setModuleGoal("");
      shellState.setModuleDescription("");
    } catch (error: any) {
      alert(`Ошибка: ${error.message}`);
    } finally {
      shellState.setModuleLoading(false);
    }
  };

  const handleThemeToggle = () => {
    if (shellState.themeSwitching) return;
    const nextTheme =
      shellState.themeToggleMode === THEME.LIGHT_BLUE ? THEME.DARK_RED : THEME.LIGHT_BLUE;
    shellState.setThemeSwitching(true);
    shellState.setThemeToggleMode(nextTheme);
    shellState.setTimeoutSafe(() => shellState.setThemeMode(nextTheme), 210);
    shellState.setTimeoutSafe(
      () => shellState.setThemeSwitching(false),
      THEME_TRANSITION_MS,
    );
  };

  useEffect(() => {
    shellState.setChartPostsLimit(10);
  }, [shellState.selectedChartRange, shellState.setChartPostsLimit]);

  useEffect(() => {
    if (!shellState.authToken) {
      shellState.setReportSourceId(null);
      return;
    }
    shellState.setReportSourceId((prev) => {
      if (!prev) return null;
      const links = shellData.reportSources
        .flatMap((item) => item.links)
        .filter((link) => (link.social_network_code || "").toLowerCase() === shellState.reportPlatform);
      const allowed = new Set(links.map((link) => link.id));
      return prev.split(",").filter((id) => allowed.has(id)).join(",") || null;
    });
  }, [
    shellData.reportSources,
    shellState.analyticsView,
    shellState.authToken,
    shellState.reportPlatform,
    shellState.setReportSourceId,
  ]);

  useEffect(() => {
    if (
      shellState.editingEventId ||
      shellState.eventStatus !== EVENT_STATUS.SCHEDULED
    ) {
      return;
    }
    const count = Math.max(1, Math.min(30, Math.trunc(shellState.eventSeriesCount || 1)));
    const step = Math.max(
      1,
      Math.min(240, Math.trunc(shellState.eventSeriesStepMinutes || 5)),
    );
    shellState.setEventSeriesItems((prev) =>
      buildSeriesPlanItems(
        count,
        step,
        shellState.eventTitle.trim(),
        shellState.eventDescription.trim(),
        shellState.eventPostType,
        prev,
      ),
    );
  }, [
    shellState.editingEventId,
    shellState.eventStatus,
    shellState.eventSeriesCount,
    shellState.eventSeriesStepMinutes,
    shellState.eventTitle,
    shellState.eventDescription,
    shellState.eventPostType,
    shellState.setEventSeriesItems,
  ]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const authParam = params.get("auth");
    if (authParam !== "login" && authParam !== "register") return;
    if (shellState.authToken) {
      params.delete("auth");
      params.delete("redirect");
      const nextSearch = params.toString();
      navigate(
        { pathname: location.pathname, search: nextSearch ? `?${nextSearch}` : "" },
        { replace: true },
      );
      return;
    }
    if (authParam === "register") {
      params.set("auth", "login");
      navigate(
        { pathname: location.pathname, search: `?${params.toString()}` },
        { replace: true },
      );
      return;
    }
    openAuth("login", { reset: false });
  }, [location.pathname, location.search, navigate, shellState.authToken]);

  useEffect(() => {
    if (shellState.initialAuthPromptedRef.current) return;
    if (!shouldPromptInitialLogin(shellState.currentUser)) return;
    shellState.initialAuthPromptedRef.current = true;
    openAuth("login");
  }, [shellState.currentUser]);

  useEffect(() => {
    return onTokenExpired(() => {
      shellState.setCurrentUser("");
      shellState.setAuthToken("");
      openAuth("login");
    });
  }, []);

  useEffect(() => {
    return onServerError((message) => {
      const seq = shellState.serverToastSeqRef.current + 1;
      shellState.serverToastSeqRef.current = seq;
      shellState.setServerToastMessage(message);
      shellState.setTimeoutSafe(() => {
        if (shellState.serverToastSeqRef.current === seq) {
          shellState.setServerToastMessage("");
        }
      }, 5000);
    });
  }, [shellState.setTimeoutSafe, shellState.serverToastSeqRef, shellState.setServerToastMessage]);

  useEffect(() => {
    if (!shellState.authToken || shellState.currentUser) return;
    if (shellData.meQuery.data) {
      shellState.setCurrentUser(shellData.meQuery.data.email);
      return;
    }
    if (shellData.meQuery.isError) {
      localStorage.removeItem(JWT_KEY);
      shellState.setAuthToken("");
    }
  }, [
    shellData.meQuery.data,
    shellData.meQuery.isError,
    shellState.authToken,
    shellState.currentUser,
    shellState.setAuthToken,
    shellState.setCurrentUser,
  ]);

  useEffect(() => {
    localStorage.setItem(THEME_KEY, shellState.themeMode);
  }, [shellState.themeMode]);

  useEffect(() => {
    writeAnalyticsSettings({
      deepLlmAnalysis: shellState.deepLlmAnalysis,
      prefilterEnabled: shellState.prefilterEnabled,
    });
  }, [shellState.deepLlmAnalysis, shellState.prefilterEnabled]);

  useEffect(() => {
    const detail = shellData.smartPainDetailQuery.data ?? null;
    shellState.setSmartPainDetail(detail);
    if (detail?.strategy_ids.length === 1) {
      shellState.setSmartStrategyId(detail.strategy_ids[0]);
    }
  }, [
    shellData.smartPainDetailQuery.data,
    shellState.setSmartPainDetail,
    shellState.setSmartStrategyId,
  ]);

  useEffect(() => {
    if (!shellState.authToken) return;
    let cancelled = false;
    let savedJobId: string | null = null;
    try {
      savedJobId = localStorage.getItem(shellState.ANALYTICS_JOB_KEY);
    } catch {}
    if (!savedJobId) return;
    (async () => {
      try {
        const finalJob = await waitForJob(
          shellState.authToken,
          savedJobId!,
          (job: unknown) => {
            if (!cancelled) shellState.setAnalyticsJob(job as any);
          },
        );
        if (cancelled) return;
        shellState.setAnalyticsJob(null);
        try {
          localStorage.removeItem(shellState.ANALYTICS_JOB_KEY);
        } catch {}
        if (finalJob.status === "completed") {
          await loadAnalyticsData(
            shellState.authToken,
            shellState.reportPeriod,
            shellState.reportSourceId,
            shellState.reportMunicipalityName,
            { silent: true },
          );
        }
      } catch {
        try {
          localStorage.removeItem(shellState.ANALYTICS_JOB_KEY);
        } catch {}
        if (!cancelled) shellState.setAnalyticsJob(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [shellState.authToken]);

  useEffect(() => {
    if (!shellState.infoEvents.length) {
      shellState.setSelectedInfoEventId(null);
      return;
    }
    if (
      !shellState.selectedInfoEventId ||
      !shellState.infoEvents.some((item) => item.id === shellState.selectedInfoEventId)
    ) {
      shellState.setSelectedInfoEventId(shellState.infoEvents[0].id);
    }
  }, [
    shellState.infoEvents,
    shellState.selectedInfoEventId,
    shellState.setSelectedInfoEventId,
  ]);

  useEffect(() => {
    if (!shellState.authToken) {
      shellState.deletedPostIdsRef.current.clear();
      shellState.calendarReloadSeqRef.current += 1;
      shellState.contentReloadSeqRef.current += 1;
      shellState.setInfoEvents([]);
      shellState.setSelectedInfoEventId(null);
      shellState.setSelectedPainId(null);
      shellState.setSelectedSubproblemTitle(null);
      return;
    }
  }, [shellState.authToken]);

  useEffect(() => {
    if (!shellState.authToken) return;
    // Сетка приходит по несколько записей на день, открытый день — целиком.
    // Складываем оба ответа, дубли убираем по идентификатору.
    const merged = new Map<string, (typeof shellData.calendarDayEvents)[number]>();
    for (const event of [
      ...(shellData.calendarEventsQuery.data ?? []),
      ...shellData.calendarDayEvents,
    ]) {
      merged.set(event.id, event);
    }
    shellState.setEvents(
      [...merged.values()]
        .filter((event) => {
          const postId = event.post_id ?? event.id;
          return (
            !shellState.deletedPostIdsRef.current.has(postId) &&
            !shellState.deletedPostIdsRef.current.has(event.id)
          );
        })
        .map(apiCalendarEventToCalendarEvent),
    );
  }, [
    shellData.calendarEventsQuery.data,
    shellData.calendarDayEvents,
    shellState.authToken,
    shellState.deletedPostIdsRef,
    shellState.setEvents,
  ]);

  useEffect(() => {
    if (!shellState.authToken || !shellData.postsQuery.data) return;
    shellState.setContentEvents(
      shellData.postsQuery.data
        .filter((post) => !shellState.deletedPostIdsRef.current.has(post.id))
        .map(apiPostToContentEvent),
    );
  }, [
    shellData.postsQuery.data,
    shellState.authToken,
    shellState.deletedPostIdsRef,
    shellState.setContentEvents,
  ]);

  useEffect(() => {
    if (!shellState.authToken) return;
    if (shellData.infoEventsQuery.data) {
      shellState.setInfoEvents(shellData.infoEventsQuery.data);
      return;
    }
    if (shellData.infoEventsQuery.isError) {
      shellState.setInfoEventMessageType(MESSAGE_STATUS.ERROR);
      shellState.setInfoEventMessage("Не удалось загрузить события");
    }
  }, [
    shellData.infoEventsQuery.data,
    shellData.infoEventsQuery.isError,
    shellState.authToken,
    shellState.setInfoEventMessage,
    shellState.setInfoEventMessageType,
    shellState.setInfoEvents,
  ]);

  useEffect(() => {
    if (!shellState.authToken) return;
    shellState.setSelectedPainId((prev) => {
      if (prev && shellData.painItems.some((pain) => pain.id === prev)) return prev;
      return shellData.painItems[0]?.id ?? null;
    });
  }, [shellData.painItems, shellState.authToken, shellState.setSelectedPainId]);

  useEffect(() => {
    if (!shellState.authToken || !shellState.selectedPainId) {
      shellState.setSelectedSubproblemTitle(null);
      return;
    }
    if (!shellData.selectedPainDetail) {
      shellState.setSelectedSubproblemTitle(null);
      return;
    }
    shellState.setSelectedSubproblemTitle((prev) =>
      prev &&
      shellData.selectedPainDetail?.subproblem_items.some((item) => item.title === prev)
        ? prev
        : shellData.selectedPainDetail?.subproblem_items[0]?.title ?? null,
    );
  }, [
    shellData.selectedPainDetail,
    shellState.authToken,
    shellState.selectedPainId,
    shellState.setSelectedSubproblemTitle,
  ]);

  useEffect(() => {
    if (!shellState.authToken || !shellState.selectedInfoEventId) {
      shellState.setEventPainPickerOpen(false);
    }
  }, [
    shellState.authToken,
    shellState.selectedInfoEventId,
    shellState.setEventPainPickerOpen,
  ]);

  useEffect(() => {
    if (!shellData.publicationTargetOptions.length) return;
    shellState.setContentPublishTargets((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const item of shellState.contentEvents) {
        if (next[item.id]) continue;
        const defaultTarget =
          item.vkPublicSocialLinkId ??
          shellData.defaultVkPublicLinkId ??
          shellData.publicationTargetOptions[0]?.id;
        if (defaultTarget) {
          next[item.id] = defaultTarget;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [
    shellData.defaultVkPublicLinkId,
    shellData.publicationTargetOptions,
    shellState.contentEvents,
    shellState.setContentPublishTargets,
  ]);

  useEffect(() => {
    shellState.setThemeAnimating(true);
    const timer = window.setTimeout(
      () => shellState.setThemeAnimating(false),
      THEME_TRANSITION_MS,
    );
    return () => window.clearTimeout(timer);
  }, [shellState.themeMode, shellState.setThemeAnimating]);

  return (
    <AppShellContext.Provider
      value={{
        location,
        navigate,
        shellState,
        shellData,
        openAuth,
        navigateToTab,
        logout,
        handleThemeToggle,
        handleModuleSubmit,
        loadAnalyticsData,
        reloadCalendarFromBackend,
        reloadContentFromBackend,
      }}
    >
      {children}
    </AppShellContext.Provider>
  );
}

export function useAppShellContext() {
  const value = useContext(AppShellContext);
  if (!value) {
    throw new Error("useAppShellContext must be used inside AppShellProvider");
  }
  return value;
}
