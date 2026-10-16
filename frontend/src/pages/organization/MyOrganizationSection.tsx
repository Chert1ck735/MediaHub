/** Раздел «Моя организация» — реквизиты, без вложенных рамок.
 *
 *  Раньше здесь была матрёшка: карточка внутри блока внутри секции. Три рамки
 *  вокруг четырёх полей. Теперь плоский список «поле → значение» и форма правки
 *  прямо на месте.
 *
 *  Тип организации админ менять не может — это решает суперадмин (сервер вернёт
 *  403). Поэтому поле показано, но заблокировано, а не спрятано: скрывать его
 *  значило бы делать вид, что типа не существует.
 */
import { useState } from "react";

import { KRASNOYARSK_MUNICIPALITIES } from "../../app/krasnoyarskMunicipalities";
import { ORG_TYPE_LABELS, type Organization } from "../../api/organization";
import { useOrganizationMutations, useRegions } from "../../hooks/useOrganization";
import { EmptyBlock, mutationMessage } from "./shared";

export function MyOrganizationSection({
  organization,
  isSuperadmin,
}: {
  organization: Organization | undefined;
  isSuperadmin: boolean;
}) {
  const { update } = useOrganizationMutations();
  const regionsQuery = useRegions();

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [regionId, setRegionId] = useState("");
  const [municipalityName, setMunicipalityName] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  if (!organization) {
    return <EmptyBlock label="Организация не найдена." />;
  }

  const regions = regionsQuery.data ?? [];
  const isKrasnoyarskRegion = (candidateRegionId: string) =>
    regions.find((region) => region.id === candidateRegionId)?.name === "Красноярский край";

  const startEdit = () => {
    setName(organization.name);
    setDescription(organization.description ?? "");
    setRegionId(organization.region_id ?? "");
    setMunicipalityName(organization.municipality_name ?? "");
    setActionError(null);
    setEditing(true);
  };

  const save = async () => {
    setActionError(null);
    try {
      await update.mutateAsync({
        orgId: organization.id,
        payload: {
          name,
          description: description || null,
          region_id: regionId || null,
          municipality_name: isKrasnoyarskRegion(regionId)
            ? municipalityName || null
            : null,
        },
      });
      setEditing(false);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  return (
    <div className="org-section org-organization-card">
      {actionError ? <p className="org-error-banner">{actionError}</p> : null}

      {editing ? (
        <div className="org-form">
          <label className="org-field">
            <span>Название</span>
            <input
              className="input"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="org-field">
            <span>Описание</span>
            <textarea
              className="input"
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label className="org-field">
            <span>Регион</span>
            <select
              className="input"
              value={regionId}
              onChange={(event) => {
                const nextRegionId = event.target.value;
                setRegionId(nextRegionId);
                if (!isKrasnoyarskRegion(nextRegionId)) {
                  setMunicipalityName("");
                }
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
          {isKrasnoyarskRegion(regionId) ? (
            <label className="org-field">
              <span>Муниципалитет</span>
              <select
                className="input"
                value={municipalityName}
                onChange={(event) => setMunicipalityName(event.target.value)}
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
          <label className="org-field">
            <span>Тип</span>
            <input
              className="input"
              value={ORG_TYPE_LABELS[organization.type]}
              disabled
            />
            <span className="muted org-hint">
              {isSuperadmin
                ? "Тип меняется в разделе «Редактирование организаций»."
                : "Тип организации может изменить только суперадминистратор."}
            </span>
          </label>

          <div className="org-form-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setEditing(false)}
              disabled={update.isPending}
            >
              Отмена
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void save()}
              disabled={update.isPending || !name.trim()}
            >
              {update.isPending ? "Сохраняем…" : "Сохранить"}
            </button>
          </div>
        </div>
      ) : (
        <>
          <button
            type="button"
            className="org-edit-button"
            onClick={startEdit}
            aria-label="Изменить организацию"
            title="Изменить"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 20h4l10.5-10.5a2.8 2.8 0 0 0-4-4L4 16v4Z" />
              <path d="m13.5 6.5 4 4" />
            </svg>
          </button>
          <dl className="org-defs">
            <div>
              <dt>Название</dt>
              <dd>{organization.name}</dd>
            </div>
            <div>
              <dt>Тип</dt>
              <dd>{ORG_TYPE_LABELS[organization.type]}</dd>
            </div>
            <div>
              <dt>Описание</dt>
              <dd>{organization.description || "—"}</dd>
            </div>
            <div>
              <dt>Регион</dt>
              <dd>{organization.region_name || "—"}</dd>
            </div>
            <div>
              <dt>Муниципалитет</dt>
              <dd>{organization.municipality_name || "—"}</dd>
            </div>
            <div>
              <dt>Сотрудников</dt>
              <dd>{organization.user_count}</dd>
            </div>
            <div>
              <dt>Площадок</dt>
              <dd>{organization.community_count}</dd>
            </div>
          </dl>
        </>
      )}
    </div>
  );
}
