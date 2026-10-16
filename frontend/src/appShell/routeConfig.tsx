import { lazy } from "react";

export type AppRouteTab =
  | "home"
  | "guide"
  | "calendar"
  | "content"
  | "infopovody"
  | "organizations"
  | "organization"
  | "analytics"
  | "settings";

export const TAB_ROUTE_MAP: Record<AppRouteTab, string> = {
  home: "/",
  guide: "/guide",
  calendar: "/calendar",
  content: "/content",
  infopovody: "/events",
  // "organizations" — это про МОДУЛИ (историческое имя), не про организацию.
  organizations: "/orgs",
  // Всё про организацию: обзор площадок, пользователи, группы, права, импорт.
  // Раньше жило внутри настроек — вынесено наверх отдельной вкладкой.
  organization: "/organization",
  analytics: "/analytics",
  settings: "/settings/account",
};

export const HomePage = lazy(() => import("../pages/HomePage").then((module) => ({ default: module.HomePage })));
export const GuidePage = lazy(() => import("../pages/GuidePage").then((module) => ({ default: module.GuidePage })));
export const CalendarPage = lazy(() =>
  import("./routes/CalendarRoute").then((module) => ({ default: module.CalendarRoute }))
);
export const ContentPage = lazy(() =>
  import("./routes/ContentRoute").then((module) => ({ default: module.ContentRoute }))
);
export const EventsPage = lazy(() =>
  import("./routes/EventsRoute").then((module) => ({ default: module.EventsRoute }))
);
export const OrganizationsPage = lazy(() =>
  import("../pages/OrganizationsPage").then((module) => ({ default: module.OrganizationsPage }))
);
export const AnalyticsPage = lazy(() =>
  import("./routes/AnalyticsRoute").then((module) => ({ default: module.AnalyticsRoute }))
);
export const SettingsPage = lazy(() =>
  import("../pages/SettingsPage").then((module) => ({ default: module.SettingsPage }))
);
export const OrganizationPage = lazy(() =>
  import("../pages/organization/OrganizationPage").then((module) => ({
    default: module.OrganizationPage,
  }))
);

export function RoutePageFallback() {
  return (
    <div className="content-page">
      <div className="content-page-head">
        <div>
          <h2 className="content-page-title">Загрузка страницы...</h2>
          <p className="muted content-page-lead">Подготавливаем раздел и подтягиваем его код.</p>
        </div>
      </div>
    </div>
  );
}

export function routeToTab(pathname: string): AppRouteTab {
  switch (pathname) {
    case "/guide":
      return "guide";
    case "/calendar":
      return "calendar";
    case "/content":
      return "content";
    case "/events":
      return "infopovody";
    case "/orgs":
      return "organizations";
    case "/organization":
      return "organization";
    case "/analytics":
      return "analytics";
    default:
      return pathname.startsWith("/settings") ? "settings" : "home";
  }
}

/** В настройках остаётся только личное и прикладное.
 *
 *  Всё про организацию (площадки, пользователи, группы, права, импорт) уехало
 *  в отдельную вкладку /organization: это управление организацией, а не
 *  настройки приложения, и прятать его в «Настройках» было неверно. */
export const SETTINGS_SECTIONS = [
  { slug: "account", label: "Аккаунт" },
  { slug: "analytics", label: "Настройки аналитики" },
  { slug: "classification-review", label: "Проверка категорий" },
  { slug: "address-cases-export", label: "Адресные кейсы" },
  { slug: "autoparse", label: "Автопарсинг" },
] as const;

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]["slug"];
