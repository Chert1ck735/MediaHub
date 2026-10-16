import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import type { AppRouteTab } from "../appShell/routeConfig";

type Item = {
  tab: AppRouteTab;
  label: string;
  icon: ReactNode;
  /** Пункт видят только админ и суперадмин. Это UX, а не защита: сервер
   *  отвечает 403 на прямой заход независимо от того, что нарисовано в меню. */
  adminOnly?: boolean;
};

const I = (d: string) => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const ITEMS: Item[] = [
  { tab: "home", label: "Главная", icon: I("M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10") },
  { tab: "guide", label: "Руководство", icon: I("M4 19.5A2.5 2.5 0 016.5 17H20M4 4.5A2.5 2.5 0 016.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15zM8 7h8M8 11h8M8 15h5") },
  { tab: "calendar", label: "История публикаций", icon: I("M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2") },
  { tab: "analytics", label: "Аналитика", icon: I("M4 20V10M10 20V4M16 20v-7M22 20H2") },
  { tab: "content", label: "Создание поста", icon: I("M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z") },
  {
    tab: "organization",
    label: "Организация",
    adminOnly: true,
    // Иконка «люди»: раздел про пользователей, группы и доступы.
    icon: I("M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"),
  },
  {
    tab: "settings",
    label: "Настройки",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
      </svg>
    ),
  },
];

type Props = {
  activeTab: string;
  onNavigate: (tab: AppRouteTab) => void;
  collapsed: boolean;
  onToggle: () => void;
  profile?: ReactNode;
  footer?: ReactNode;
  /** Админ ли текущий пользователь. По умолчанию false — то есть при неизвестной
   *  роли админские пункты НЕ показываем (безопасный дефолт, а не наоборот). */
  isOrgAdmin?: boolean;
};

export function Sidebar({
  activeTab,
  onNavigate,
  collapsed,
  onToggle,
  profile,
  footer,
  isOrgAdmin = false,
}: Props) {
  const items = ITEMS.filter((item) => !item.adminOnly || isOrgAdmin).map(item => ({
    ...item,
    label: item.tab === "calendar" ? "Календарь публикаций" : item.tab === "content" ? "Студия контента" : item.label,
  }));
  return (
    <aside className={`app-sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="app-sidebar-top">
        <Link className="app-sidebar-logo-mark" to="/" aria-label="На главную">
          Σ
        </Link>
        <div className="app-sidebar-identity">
          <Link className="app-sidebar-logo-text" to="/">
            СИГМА
          </Link>
          {profile}
        </div>
      </div>
      <p className="sidebar-nav-caption">Рабочее пространство</p>
      <nav className="app-sidebar-nav" aria-label="Основная навигация">
        {items.map((it) => (
          <button
            key={it.tab}
            type="button"
            className={`app-sidebar-item${activeTab === it.tab ? " active" : ""}`}
            onClick={() => onNavigate(it.tab)}
            title={collapsed ? it.label : undefined}
            aria-label={it.label}
            aria-current={activeTab === it.tab ? "page" : undefined}
          >
            <span className="app-sidebar-icon">{it.icon}</span>
            <span className="app-sidebar-label">{it.label}</span>
          </button>
        ))}
      </nav>
      <div className="app-sidebar-bottom">
        {footer && <div className="app-sidebar-footer">{footer}</div>}
        <button
          type="button"
          className="app-sidebar-toggle"
          onClick={onToggle}
          aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
          title={collapsed ? "Развернуть меню" : "Свернуть меню"}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d={collapsed ? "M9 6l6 6-6 6" : "M15 6l-6 6 6 6"} />
          </svg>
          <span className="app-sidebar-label">Свернуть</span>
        </button>
      </div>
    </aside>
  );
}
