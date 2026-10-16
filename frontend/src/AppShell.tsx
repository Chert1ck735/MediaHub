import { Suspense, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useLocation, useNavigate } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { openAuthModal } from "./appShell/authController";
import { AppShellProvider, useAppShellContext } from "./appShell/AppShellContext";
import { AppShellModals } from "./appShell/AppShellModals";
import { AppShellRoutes } from "./appShell/AppShellRoutes";
import {
  RoutePageFallback,
  routeToTab,
  TAB_ROUTE_MAP,
  type AppRouteTab,
} from "./appShell/routeConfig";
import { QueueStatus } from "./components/analytics/QueueStatus";
import { THEME } from "./constants";
import { useClassificationQueue } from "./hooks/useClassificationQueue";
import { useMe } from "./hooks/useMe";

const PAGE_LABELS: Record<AppRouteTab, string> = {
  home: "Обзор", calendar: "Календарь публикаций", analytics: "Аналитика",
  content: "Студия контента", guide: "Руководство", organization: "Организация",
  organizations: "Модули", infopovody: "Инфоповоды", settings: "Настройки",
};

function AppShellFrame() {
  const { location, navigate, shellState, handleThemeToggle } = useAppShellContext();
  const activeTab = routeToTab(location.pathname);
  const meQuery = useMe(shellState.authToken);
  // Под логотипом показываем имя, а email — только как запасной вариант, пока
  // профиль не подгрузился.
  const userName = meQuery.data?.name || shellState.currentUser;
  // Пункт «Организация» видят только админы. Пока профиль не загружен — false,
  // то есть пункт не мигает у миньона на долю секунды.
  const isOrgAdmin =
    meQuery.data?.role === "admin" || meQuery.data?.role === "superadmin";
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // Индикатор фоновой классификации живёт в сайдбаре, а не в аналитике:
  // очередь общая для приложения, и её состояние важно на любой странице.
  const classification = useClassificationQueue(shellState.authToken);
  const authParam = new URLSearchParams(location.search).get("auth");
  const authOnly =
    shellState.authModalOpen ||
    (!shellState.authToken && (authParam === "login" || authParam === "register"));

  const navigateToTab = (tab: AppRouteTab) => navigate(TAB_ROUTE_MAP[tab]);

  const openAuth = (mode: "login", options?: { reset?: boolean }) =>
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

  return (
    <div
      className={`page ${authOnly ? "auth-only" : ""} theme-${shellState.themeMode} ${
        shellState.themeAnimating ? "theme-animating" : ""
      } ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}
    >
      {!authOnly && (
        <Sidebar
          activeTab={activeTab}
          onNavigate={navigateToTab}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed((v) => !v)}
          isOrgAdmin={isOrgAdmin}
          profile={
            shellState.currentUser ? (
              <button
                type="button"
                className={`app-profile${activeTab === "settings" ? " active" : ""}`}
                onClick={() => navigateToTab("settings")}
                title={`${userName} · Настройки`}
              >
                {userName}
              </button>
            ) : null
          }
          footer={
            <>
              {classification.queue && (
                <QueueStatus
                  queue={classification.queue}
                  onToggle={classification.toggleWorker}
                  collapsed={sidebarCollapsed}
                />
              )}
              {!shellState.currentUser && (
                <button
                  type="button"
                  className="app-profile-login"
                  onClick={() => openAuth("login")}
                  title="Войти"
                  aria-label="Войти"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3" />
                  </svg>
                  <span className="app-sidebar-label">Войти</span>
                </button>
              )}
              <button
                className="app-theme-toggle"
                type="button"
                onClick={handleThemeToggle}
                aria-label="Переключить тему"
              >
                {shellState.themeMode === THEME.DARK_RED ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" />
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="4" />
                    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                  </svg>
                )}
                <span className="app-sidebar-label">
                  {shellState.themeMode === THEME.DARK_RED ? "Тёмная тема" : "Светлая тема"}
                </span>
              </button>
            </>
          }
        />
      )}

      {!authOnly && (
        <div className="app-main-col">
          <header className="workspace-topbar">
            <div className="workspace-breadcrumb"><span>Рабочее пространство</span><span aria-hidden="true">/</span><strong>{PAGE_LABELS[activeTab]}</strong></div>
            <div className="workspace-topbar-actions">
              <time>{new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}</time>
            </div>
          </header>
          <AnimatePresence>
            {shellState.serverToastMessage && (
              <motion.div
                className="app-toast"
                initial={{ opacity: 0, y: -18 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={{ duration: 0.22 }}
                role="status"
                aria-live="polite"
              >
                <span>{shellState.serverToastMessage}</span>
                <button
                  type="button"
                  className="app-toast-close"
                  onClick={() => shellState.setServerToastMessage("")}
                  aria-label="Закрыть уведомление"
                >
                  Закрыть
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          <main className="container main">
            <Suspense fallback={<RoutePageFallback />}>
              <AppShellRoutes />
            </Suspense>
          </main>
        </div>
      )}

      <AppShellModals />
    </div>
  );
}

function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <AppShellProvider location={location} navigate={navigate}>
      <AppShellFrame />
    </AppShellProvider>
  );
}

export default AppShell;
