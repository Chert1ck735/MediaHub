/** Редактор прав конкретного пользователя внутри диалогового окна. */
import { useMemo, useState } from "react";

import {
  EDITABLE_PERMISSIONS,
  type GrantItem,
  type OrgUser,
  type Permission,
} from "../../api/organization";
import {
  useCommunities,
  useGrants,
  useReplaceGrants,
} from "../../hooks/useOrganization";
import { EmptyBlock, ErrorBlock, LoadingBlock, mutationMessage } from "./shared";

const grantKey = (grant: GrantItem) =>
  `${grant.resource_type}:${grant.resource_id}:${grant.permission}`;

export function UserAccessDialog({
  orgId,
  user,
  onClose,
}: {
  orgId: string;
  user: OrgUser;
  onClose: () => void;
}) {
  const communitiesQuery = useCommunities(orgId);
  const grantsQuery = useGrants(orgId, "user", user.id);
  const replace = useReplaceGrants(orgId);
  const [draft, setDraft] = useState<Set<string> | null>(null);
  const [saved, setSaved] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const serverKeys = useMemo(
    () => new Set((grantsQuery.data?.grants ?? []).map(grantKey)),
    [grantsQuery.data],
  );
  const current = draft ?? serverKeys;
  const isDirty = useMemo(() => {
    if (draft === null || draft.size !== serverKeys.size) return draft !== null;
    for (const key of draft) if (!serverKeys.has(key)) return true;
    return false;
  }, [draft, serverKeys]);

  const toggle = (communityId: string, permission: Permission) => {
    const key = `community:${communityId}:${permission}`;
    const next = new Set(current);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setDraft(next);
    setSaved(false);
  };

  const save = async () => {
    if (draft === null) return;
    setActionError(null);
    const grants: GrantItem[] = [...draft].map((key) => {
      const [, resourceId, permission] = key.split(":");
      return {
        resource_type: "community",
        resource_id: resourceId,
        permission: permission as Permission,
      };
    });
    try {
      await replace.mutateAsync({ subjectType: "user", subjectId: user.id, grants });
      setDraft(null);
      setSaved(true);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  const communities = communitiesQuery.data ?? [];
  const loading = communitiesQuery.isLoading || grantsQuery.isLoading;
  const queryError = communitiesQuery.error ?? grantsQuery.error;

  return (
    <div className="org-modal-backdrop" role="dialog" aria-modal="true">
      <div className="org-modal org-modal--wide">
        <h3 className="org-modal-title">Права доступа · {user.full_name}</h3>
        <p className="muted org-modal-lead">{user.email}</p>

        {actionError ? <p className="org-error-banner">{actionError}</p> : null}
        {loading ? <LoadingBlock label="Загружаем права…" /> : null}
        {queryError ? <ErrorBlock error={queryError} /> : null}
        {!loading && !queryError && communities.length === 0 ? (
          <EmptyBlock label="В организации пока нет площадок." />
        ) : null}
        {!loading && !queryError && communities.length > 0 ? (
          <div className="org-table-wrap">
            <table className="org-table">
              <thead>
                <tr>
                  <th>Площадка</th>
                  {EDITABLE_PERMISSIONS.map(({ key, label }) => (
                    <th key={key} className="org-cell-check">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {communities.map((community) => (
                  <tr key={community.id}>
                    <td>{community.name}</td>
                    {EDITABLE_PERMISSIONS.map(({ key: permission }) => (
                      <td key={permission} className="org-cell-check">
                        <input
                          type="checkbox"
                          checked={current.has(`community:${community.id}:${permission}`)}
                          onChange={() => toggle(community.id, permission)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="org-modal-actions org-access-actions">
          {isDirty ? <span className="org-dirty">Есть несохранённые изменения</span> : null}
          {saved ? <span className="org-saved">Сохранено</span> : null}
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Закрыть
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setDraft(null)}
            disabled={!isDirty || replace.isPending}
          >
            Отменить изменения
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={!isDirty || replace.isPending}
          >
            {replace.isPending ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </div>
    </div>
  );
}
