/** Раздел «[СУПЕРАДМИН] Редактирование организаций».
 *
 *  Здесь и только здесь организации заводятся, меняют тип и удаляются — эти три
 *  действия сервер разрешает лишь суперадмину (403 остальным независимо от
 *  того, что нарисовано в интерфейсе).
 *
 *  Выбор рабочей организации тоже тут: суперадмин работает не в одной, и все
 *  остальные разделы читают данные из той, что выбрана здесь.
 */
import { useState } from "react";

import {
  ORG_TYPE_LABELS,
  type Organization,
  type OrgType,
} from "../../api/organization";
import { KRASNOYARSK_MUNICIPALITIES } from "../../app/krasnoyarskMunicipalities";
import { useOrganizationMutations, useOrganizations, useRegions } from "../../hooks/useOrganization";
import {
  ConfirmDialog,
  EmptyBlock,
  ErrorBlock,
  LoadingBlock,
  mutationMessage,
} from "./shared";

type Draft = {
  id: string | null;
  name: string;
  type: OrgType;
  description: string;
  regionId: string;
  municipalityName: string;
  adminEmail: string;
  adminFirstName: string;
  adminLastName: string;
};

const emptyDraft = (): Draft => ({
  id: null,
  name: "",
  type: "government",
  description: "",
  regionId: "",
  municipalityName: "",
  adminEmail: "",
  adminFirstName: "",
  adminLastName: "",
});

export function SuperadminOrgsSection({
  currentOrgId,
  selectedOrgId,
  onSelect,
}: {
  /** Организация самого суперадмина — её нельзя удалить (отрежет сам себя). */
  currentOrgId: string;
  selectedOrgId: string;
  onSelect: (orgId: string) => void;
}) {
  const query = useOrganizations();
  const regionsQuery = useRegions();
  const { create, update, remove } = useOrganizationMutations();

  const [draft, setDraft] = useState<Draft | null>(null);
  const [toRemove, setToRemove] = useState<Organization | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const busy = create.isPending || update.isPending || remove.isPending;
  const regions = regionsQuery.data ?? [];
  const isKrasnoyarskRegion = (regionId: string) =>
    regions.find((region) => region.id === regionId)?.name === "Красноярский край";

  const submit = async () => {
    if (!draft) return;
    setActionError(null);
    try {
      if (draft.id) {
        await update.mutateAsync({
          orgId: draft.id,
          payload: {
            name: draft.name,
            type: draft.type,
            description: draft.description || null,
            region_id: draft.regionId || null,
            municipality_name: isKrasnoyarskRegion(draft.regionId)
              ? draft.municipalityName || null
              : null,
          },
        });
      } else {
        const created = await create.mutateAsync({
          name: draft.name,
          type: draft.type,
          description: draft.description || null,
          region_id: draft.regionId || null,
          municipality_name: isKrasnoyarskRegion(draft.regionId)
            ? draft.municipalityName || null
            : null,
          admin_email: draft.adminEmail || null,
          admin_first_name: draft.adminFirstName || null,
          admin_last_name: draft.adminLastName || null,
        });
        // Следующий шаг сценария — завести в неё людей, поэтому сразу делаем её
        // рабочей, а не заставляем искать в списке.
        onSelect(created.id);
      }
      setDraft(null);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  const doRemove = async (org: Organization) => {
    setActionError(null);
    try {
      await remove.mutateAsync(org.id);
      if (selectedOrgId === org.id) onSelect(currentOrgId);
      setToRemove(null);
    } catch (error) {
      setActionError(mutationMessage(error));
      setToRemove(null);
    }
  };

  if (query.isLoading) return <LoadingBlock label="Загружаем организации…" />;
  if (query.isError) {
    return <ErrorBlock error={query.error} onRetry={() => void query.refetch()} />;
  }

  const organizations = query.data ?? [];
  const visibleOrganizations = (() => {
    const needle = search.trim().toLocaleLowerCase("ru");
    if (!needle) return organizations;
    return organizations.filter((org) =>
      `${org.name} ${ORG_TYPE_LABELS[org.type]}`.toLocaleLowerCase("ru").includes(needle),
    );
  })();

  return (
    <div className="org-section">
      <div className="org-tab-head org-superadmin-orgs-head">
        <div className="org-filters org-superadmin-orgs-search">
          <input
            type="search"
            className="input"
            placeholder="Поиск организаций"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setDraft(emptyDraft())}
        >
          Создать организацию
        </button>
      </div>

      {actionError ? <p className="org-error-banner">{actionError}</p> : null}

      {organizations.length === 0 ? (
        <EmptyBlock label="Организаций пока нет. Создайте первую." />
      ) : visibleOrganizations.length === 0 ? (
        <EmptyBlock label="По вашему запросу организаций не найдено." />
      ) : (
        <div className="org-table-wrap">
          <table className="org-table">
            <thead>
              <tr>
                <th>Организация</th>
                <th>Тип</th>
                <th>Территория</th>
                <th>Сотрудников</th>
                <th>Площадок</th>
                <th aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {visibleOrganizations.map((org) => {
                const active = org.id === selectedOrgId;
                const own = org.id === currentOrgId;
                return (
                  <tr key={org.id} className={active ? "org-row-active" : ""}>
                    <td>
                      {org.name}
                      {own ? <span className="muted"> · ваша</span> : null}
                    </td>
                    <td>{ORG_TYPE_LABELS[org.type]}</td>
                    <td>
                      {org.region_name || "—"}
                      {org.municipality_name ? (
                        <span className="muted"> · {org.municipality_name}</span>
                      ) : null}
                    </td>
                    <td>{org.user_count}</td>
                    <td>{org.community_count}</td>
                    <td className="org-row-actions">
                      {active ? (
                        <span className="muted">рабочая</span>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => onSelect(org.id)}
                        >
                          Работать с ней
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() =>
                          setDraft({
                            id: org.id,
                            name: org.name,
                            type: org.type,
                            description: org.description ?? "",
                            regionId: org.region_id ?? "",
                            municipalityName: org.municipality_name ?? "",
                            adminEmail: "",
                            adminFirstName: "",
                            adminLastName: "",
                          })
                        }
                      >
                        Изменить
                      </button>
                      {/* Свою организацию удалить нельзя — сервер вернёт 409,
                          поэтому и кнопку не показываем. */}
                      {own ? null : (
                        <button
                          type="button"
                          className="btn btn-danger-ghost"
                          onClick={() => setToRemove(org)}
                        >
                          Удалить
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {draft ? (
        <div className="org-modal-backdrop" role="dialog" aria-modal="true">
          <div className="org-modal">
            <h3 className="org-modal-title">
              {draft.id ? "Изменить организацию" : "Новая организация"}
            </h3>
            <div className="org-modal-body org-form">
              <label className="org-field">
                <span>Название</span>
                <input
                  className="input"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </label>
              <label className="org-field">
                <span>Тип</span>
                <select
                  className="input"
                  value={draft.type}
                  onChange={(e) => setDraft({ ...draft, type: e.target.value as OrgType })}
                >
                  {(Object.keys(ORG_TYPE_LABELS) as OrgType[]).map((type) => (
                    <option key={type} value={type}>
                      {ORG_TYPE_LABELS[type]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="org-field">
                <span>Описание</span>
                <textarea
                  className="input"
                  rows={2}
                  value={draft.description}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                />
              </label>
              <label className="org-field">
                <span>Регион</span>
                <select
                  className="input"
                  value={draft.regionId}
                  onChange={(e) => {
                    const regionId = e.target.value;
                    setDraft({
                      ...draft,
                      regionId,
                      municipalityName: isKrasnoyarskRegion(regionId)
                        ? draft.municipalityName
                        : "",
                    });
                  }}
                >
                  <option value="">Не задан</option>
                  {regions.map((region) => (
                    <option key={region.id} value={region.id}>
                      {region.name}
                    </option>
                  ))}
                </select>
              </label>
              {isKrasnoyarskRegion(draft.regionId) ? (
                <label className="org-field">
                  <span>Муниципалитет</span>
                  <select
                    className="input"
                    value={draft.municipalityName}
                    onChange={(e) =>
                      setDraft({ ...draft, municipalityName: e.target.value })
                    }
                  >
                    <option value="">Не задан</option>
                    {KRASNOYARSK_MUNICIPALITIES.map((municipality) => (
                      <option key={municipality.label} value={municipality.label}>
                        {municipality.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              {!draft.id ? (
                <>
                  <p className="org-form-divider">
                    Администратор <span className="muted">— необязательно</span>
                  </p>
                  <label className="org-field">
                    <span>Email администратора</span>
                    <input
                      className="input"
                      type="email"
                      value={draft.adminEmail}
                      onChange={(e) => setDraft({ ...draft, adminEmail: e.target.value })}
                    />
                  </label>
                  <label className="org-field">
                    <span>Имя</span>
                    <input
                      className="input"
                      value={draft.adminFirstName}
                      onChange={(e) =>
                        setDraft({ ...draft, adminFirstName: e.target.value })
                      }
                    />
                  </label>
                  <label className="org-field">
                    <span>Фамилия</span>
                    <input
                      className="input"
                      value={draft.adminLastName}
                      onChange={(e) =>
                        setDraft({ ...draft, adminLastName: e.target.value })
                      }
                    />
                  </label>
                  <p className="muted">
                    Организацией без администратора сможет управлять только суперадмин.
                    Администратор будет создан со статусом «Приглашён».
                  </p>
                </>
              ) : null}
            </div>
            <div className="org-modal-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setDraft(null)}
                disabled={busy}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void submit()}
                disabled={busy || !draft.name.trim()}
              >
                {busy ? "Сохраняем…" : "Сохранить"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {toRemove ? (
        <ConfirmDialog
          title="Удалить организацию?"
          description={
            <>
              <p>«{toRemove.name}» будет удалена безвозвратно.</p>
              <p className="org-warning">
                Вместе с ней исчезнут её сотрудники ({toRemove.user_count}), площадки (
                {toRemove.community_count}) и все выданные права.
              </p>
            </>
          }
          busy={remove.isPending}
          onCancel={() => setToRemove(null)}
          onConfirm={() => void doRemove(toRemove)}
        />
      ) : null}
    </div>
  );
}
