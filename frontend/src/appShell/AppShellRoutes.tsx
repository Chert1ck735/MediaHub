import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "../components/ProtectedRoute";
import { logoutAction } from "./authController";
import { useAppShellContext } from "./AppShellContext";
import {
  AnalyticsPage,
  CalendarPage,
  ContentPage,
  EventsPage,
  GuidePage,
  HomePage,
  OrganizationsPage,
  OrganizationPage,
  SettingsPage,
} from "./routeConfig";

export function AppShellRoutes() {
  const {
    shellState,
    shellData,
    navigate,
    openAuth,
    navigateToTab,
    handleModuleSubmit,
  } = useAppShellContext();

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

  return (
    <Routes>
      <Route
        path="/"
        element={
          <HomePage
            authToken={shellState.authToken}
            reportSourceId={shellState.reportSourceId}
            navigateToTab={navigateToTab}
            openAuth={openAuth}
          />
        }
      />
      <Route
        element={
          <ProtectedRoute
            authToken={shellState.authToken}
            onRequireAuth={() => openAuth("login")}
          />
        }
      >
        <Route path="/guide" element={<GuidePage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/content" element={<ContentPage />} />
        <Route path="/events" element={<EventsPage />} />
        <Route
          path="/orgs"
          element={
            <OrganizationsPage
              moduleDescription={shellState.moduleDescription}
              moduleGoal={shellState.moduleGoal}
              moduleLoading={shellState.moduleLoading}
              moduleName={shellState.moduleName}
              moduleNameFocused={shellState.moduleNameFocused}
              moduleNameMatchesPublic={shellData.moduleNameMatchesPublic}
              moduleNameSuggestions={shellData.moduleNameSuggestions}
              modulePublicNames={shellData.modulePublicNames}
              modulesList={shellData.modulesList}
              normalizedModuleName={shellData.normalizedModuleName}
              reportSourcesLoading={shellData.reportSourcesLoading}
              setModuleDescription={shellState.setModuleDescription}
              setModuleGoal={shellState.setModuleGoal}
              setModuleLoading={shellState.setModuleLoading}
              setModuleName={shellState.setModuleName}
              setModuleNameFocused={shellState.setModuleNameFocused}
              setTimeoutSafe={shellState.setTimeoutSafe}
              handleModuleSubmit={handleModuleSubmit}
            />
          }
        />
        <Route path="/analytics" element={<AnalyticsPage />} />

        {/* Управление организацией — отдельная вкладка, а не подраздел настроек. */}
        <Route
          path="/organization"
          element={
            <OrganizationPage
              // Импорт площадки меняет их список — освежаем сразу, иначе
              // добавленный паблик не появится, пока не перезайдёшь.
              onIngested={() => void shellData.organizationsQuery.refetch()}
            />
          }
        />

        <Route path="/settings" element={<Navigate to="/settings/account" replace />} />
        {/* Старые адреса не ломаем: там теперь живёт раздел «Организация».
            Должны стоять ДО /settings/:section, иначе динамический маршрут их перехватит. */}
        <Route
          path="/settings/organization"
          element={<Navigate to="/organization" replace />}
        />
        <Route path="/settings/access" element={<Navigate to="/organization" replace />} />
        <Route
          path="/settings/:section"
          element={
            <SettingsPage
              authToken={shellState.authToken}
              currentUser={shellState.currentUser}
              deepLlmAnalysis={shellState.deepLlmAnalysis}
              setDeepLlmAnalysis={shellState.setDeepLlmAnalysis}
              prefilterEnabled={shellState.prefilterEnabled}
              setPrefilterEnabled={shellState.setPrefilterEnabled}
              onLogout={logout}
            />
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
