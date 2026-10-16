/** Раздел «Организация» — навигация слева, содержимое справа.
 *
 *  Была стена аккордеонов, до этого — шесть вкладок. Теперь список разделов
 *  слева (как на странице настроек): что где лежит, видно сразу, а на экране в
 *  каждый момент — ровно один раздел.
 *
 *  Активный раздел не монтирует остальные, поэтому их запросы не летят, пока
 *  туда не зашли.
 *
 *  Роль проверяется и здесь, и на сервере. Клиентская проверка — про UX,
 *  безопасность обеспечивает 403.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getStoredToken } from "../../api";
import { useMe } from "../../hooks/useMe";
import { useOrganizations } from "../../hooks/useOrganization";
import VkIngestPanel from "../../VkIngestPanel";
import { MyOrganizationSection } from "./MyOrganizationSection";
import { SuperadminOrgsSection } from "./SuperadminOrgsSection";
import { UsersTab } from "./UsersTab";
import { Forbidden, LoadingBlock } from "./shared";

type SectionId =
  | "superadmin-orgs"
  | "my-org"
  | "users"
  | "communities";

type SectionDef = {
  id: SectionId;
  label: string;
  /** Раздел виден только суперадмину. */
  superadminOnly?: boolean;
};

const SECTIONS: SectionDef[] = [
  { id: "superadmin-orgs", label: "[СУПЕРАДМИН] Редактирование организаций", superadminOnly: true },
  { id: "my-org", label: "Моя организация" },
  { id: "users", label: "Пользователи" },
  { id: "communities", label: "Площадки" },
];

function sectionFromSearch(params: URLSearchParams): SectionId | null {
  const value = params.get("section") || params.get("tab");
  return value === "communities" ? "communities" : null;
}

export type OrganizationPageProps = {
  onIngested?: () => void | Promise<void>;
};

export function OrganizationPage({ onIngested }: OrganizationPageProps) {
  const token = getStoredToken();
  const me = useMe(token);
  const [searchParams] = useSearchParams();

  // Организация, с которой работают разделы. null = своя (из профиля).
  const [pickedOrgId, setPickedOrgId] = useState<string | null>(null);
  const [section, setSection] = useState<SectionId>(() => sectionFromSearch(searchParams) ?? "my-org");

  useEffect(() => {
    const next = sectionFromSearch(searchParams);
    if (next && next !== section) setSection(next);
  }, [searchParams, section]);

  const orgsQuery = useOrganizations();

  if (me.isLoading) return <LoadingBlock label="Проверяем доступ…" />;
  if (me.isError || !me.data) {
    return <Forbidden hint="Не удалось определить пользователя. Войдите заново." />;
  }

  const { role, organization_id: ownOrgId } = me.data;
  if (role !== "admin" && role !== "superadmin") return <Forbidden />;
  if (!ownOrgId) return <Forbidden hint="Пользователь не привязан к организации." />;

  const isSuperadmin = role === "superadmin";
  const orgId = pickedOrgId ?? ownOrgId;
  const currentOrg = (orgsQuery.data ?? []).find((org) => org.id === orgId);

  const visibleSections = SECTIONS.filter((s) => !s.superadminOnly || isSuperadmin);

  return (
    <div className="tab-content org-page">
      <div className="section-header">
        <h2>Организация</h2>
      </div>

      <div className="org-layout">
        <nav className="org-nav" aria-label="Разделы организации">
          {visibleSections.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`org-nav-link${section === item.id ? " active" : ""}${
                item.superadminOnly ? " is-superadmin" : ""
              }`}
              onClick={() => setSection(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="org-content">
          {section === "superadmin-orgs" && isSuperadmin ? (
            <SuperadminOrgsSection
              currentOrgId={ownOrgId}
              selectedOrgId={orgId}
              onSelect={(id) => {
                setPickedOrgId(id);
                setSection("users"); // следующий шаг — завести людей
              }}
            />
          ) : null}

          {section === "my-org" ? (
            <MyOrganizationSection
              organization={currentOrg}
              isSuperadmin={isSuperadmin}
            />
          ) : null}

          {section === "users" ? (
            <UsersTab orgId={orgId} isSuperadmin={isSuperadmin} />
          ) : null}

          {section === "communities" ? (
            <div className="org-section">
              {/* Добавление площадок переехало сюда из аналитики: это
                  управление организацией, а не аналитика. Состояние данных
                  по площадкам живёт в самой панели (таблица), поэтому
                  отдельных карточек-дубликатов ниже больше нет. */}
              <VkIngestPanel
                token={token}
                orgId={orgId}
                onIngested={onIngested}
              />
            </div>
          ) : null}

        </div>
      </div>
    </div>
  );
}
