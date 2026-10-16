/** Вкладка «Пользователи»: таблица, поиск, фильтры, действия. */
import { useMemo, useState } from "react";

import {
  ROLE_LABELS,
  STATUS_LABELS,
  exportUsers,
  saveBlob,
  type OrgUser,
  type UserRole,
  type UserStatus,
} from "../../api/organization";
import { useDebounce } from "../../hooks/useDebounce";
import {
  useUserMutations,
  useUsers,
} from "../../hooks/useOrganization";
import { ImportTab } from "./ImportTab";
import { UserAccessDialog } from "./PermissionsTab";
import {
  ConfirmDialog,
  EmptyBlock,
  ErrorBlock,
  LoadingBlock,
  mutationMessage,
} from "./shared";

const PAGE_SIZE = 25;

type Draft = {
  id: string | null;
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole;
};

const emptyDraft = (): Draft => ({
  id: null,
  email: "",
  first_name: "",
  last_name: "",
  role: "minion",
});

export function UsersTab({ orgId, isSuperadmin }: { orgId: string; isSuperadmin: boolean }) {
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const [status, setStatus] = useState<UserStatus | "">("");
  const [page, setPage] = useState(1);

  // Дебаунс поиска: без него запрос улетает на каждую букву.
  const debouncedSearch = useDebounce(search, 300);

  const filters = useMemo(
    () => ({ search: debouncedSearch, role, status, page, pageSize: PAGE_SIZE }),
    [debouncedSearch, role, status, page],
  );

  const usersQuery = useUsers(orgId, filters);
  const { create, update, block, remove, resendInvitation } = useUserMutations(orgId);

  const [draft, setDraft] = useState<Draft | null>(null);
  const [createMode, setCreateMode] = useState<"manual" | "import">("manual");
  const [toRemove, setToRemove] = useState<OrgUser | null>(null);
  const [accessFor, setAccessFor] = useState<OrgUser | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const doExport = async () => {
    setActionError(null);
    setExporting(true);
    try {
      const blob = await exportUsers(orgId, "xlsx");
      saveBlob(blob, "users.xlsx");
    } catch (error) {
      setActionError(mutationMessage(error));
    } finally {
      setExporting(false);
    }
  };

  const openCreate = () => {
    setCreateMode("manual");
    setDraft(emptyDraft());
  };

  if (usersQuery.isLoading) return <LoadingBlock label="Загружаем пользователей…" />;
  if (usersQuery.isError) {
    return <ErrorBlock error={usersQuery.error} onRetry={() => void usersQuery.refetch()} />;
  }

  const data = usersQuery.data!;
  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const busy = create.isPending || update.isPending || block.isPending || remove.isPending || resendInvitation.isPending;

  const submitDraft = async () => {
    if (!draft) return;
    setActionError(null);
    setActionNotice(null);
    try {
      if (draft.id) {
        await update.mutateAsync({
          userId: draft.id,
          payload: {
            email: draft.email,
            first_name: draft.first_name,
            last_name: draft.last_name,
            role: draft.role,
          },
        });
      } else {
        await create.mutateAsync({
          email: draft.email,
          first_name: draft.first_name,
          last_name: draft.last_name,
          role: draft.role,
        });
        setActionNotice(`Приглашение отправлено на ${draft.email}.`);
      }
      setDraft(null);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  const runAction = async (fn: () => Promise<unknown>, successMessage?: string) => {
    setActionError(null);
    setActionNotice(null);
    try {
      await fn();
      if (successMessage) setActionNotice(successMessage);
      setToRemove(null);
    } catch (error) {
      setActionError(mutationMessage(error));
    }
  };

  return (
    <section className="org-tab">
      <header className="org-tab-head org-users-head">
        <div className="org-filters org-users-filters">
          <input
            type="search"
            className="input"
            placeholder="Поиск по ФИО или email"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1); // новый поиск — всегда с первой страницы
            }}
          />
          <select
            className="input"
            value={role}
            onChange={(event) => {
              setRole(event.target.value as UserRole | "");
              setPage(1);
            }}
          >
            <option value="">Все роли</option>
            <option value="admin">Администратор</option>
            <option value="minion">Пользователь</option>
            {isSuperadmin ? <option value="superadmin">Суперадминистратор</option> : null}
          </select>
          <select
            className="input"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as UserStatus | "");
              setPage(1);
            }}
          >
            <option value="">Все статусы</option>
            <option value="active">Активен</option>
            <option value="blocked">Заблокирован</option>
            <option value="invited">Приглашён</option>
          </select>
        </div>
        <div className="org-head-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={openCreate}
          >
            Добавить пользователя
          </button>
        </div>
      </header>

      {actionError ? <p className="org-error-banner">{actionError}</p> : null}
      {actionNotice ? <p className="message success">{actionNotice}</p> : null}

      {data.items.length === 0 ? (
        <EmptyBlock label="Пользователи не найдены. Измените фильтры или добавьте нового." />
      ) : (
        <div className="org-table-wrap org-users-table-wrap">
          <table className="org-table org-users-table">
            <thead>
              <tr>
                <th>ФИО</th>
                <th>Email</th>
                <th>Роль</th>
                <th>Статус</th>
                <th>Площадок</th>
                <th aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {data.items.map((user) => {
                // Действия админа над суперадмином скрываем — сервер их всё
                // равно отклонит 403.
                const locked = user.role === "superadmin" && !isSuperadmin;
                return (
                  <tr key={user.id}>
                    <td>{user.full_name}</td>
                    <td className="org-cell-muted">{user.email}</td>
                    <td>
                      {locked ? (
                        ROLE_LABELS[user.role]
                      ) : (
                        // Роль меняется прямо в строке — отдельная форма ради
                        // одного поля только мешает. Понижение последнего
                        // активного админа сервер отклонит с 409, и текст
                        // ошибки покажется баннером выше.
                        <select
                          className="input input-inline"
                          value={user.role}
                          disabled={busy}
                          onChange={(event) =>
                            void runAction(() =>
                              update.mutateAsync({
                                userId: user.id,
                                payload: { role: event.target.value as UserRole },
                              }),
                            )
                          }
                        >
                          <option value="minion">{ROLE_LABELS.minion}</option>
                          <option value="admin">{ROLE_LABELS.admin}</option>
                          {isSuperadmin ? (
                            <option value="superadmin">{ROLE_LABELS.superadmin}</option>
                          ) : null}
                        </select>
                      )}
                    </td>
                    <td>
                      <span className={`org-badge org-badge--${user.status}`}>
                        {STATUS_LABELS[user.status]}
                      </span>
                    </td>
                    <td>{user.accessible_communities_count}</td>
                    <td className="org-row-actions">
                      {locked ? (
                        <span className="muted">—</span>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() =>
                              setDraft({
                                id: user.id,
                                email: user.email,
                                first_name: user.first_name,
                                last_name: user.last_name,
                                role: user.role,
                              })
                            }
                          >
                            Изменить
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => setAccessFor(user)}
                          >
                            Доступ
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost"
                            disabled={busy}
                            onClick={() =>
                              void runAction(() =>
                                block.mutateAsync({
                                  userId: user.id,
                                  blocked: user.status !== "blocked",
                                }),
                              )
                            }
                          >
                            {user.status === "blocked" ? "Разблокировать" : "Заблокировать"}
                          </button>
                          {user.status === "invited" ? (
                            <button
                              type="button"
                              className="btn btn-ghost"
                              disabled={busy}
                              onClick={() => void runAction(
                                () => resendInvitation.mutateAsync(user.id),
                                `Приглашение повторно отправлено на ${user.email}.`,
                              )}
                            >
                              Отправить приглашение ещё раз
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="btn btn-danger-ghost"
                            onClick={() => setToRemove(user)}
                          >
                            Удалить
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <button
        type="button"
        className="btn btn-secondary org-xlsx-export"
        onClick={() => void doExport()}
        disabled={exporting}
      >
        {exporting ? "Готовим файл…" : "Экспортировать таблицу в XLSX"}
      </button>

      {totalPages > 1 ? (
        <footer className="org-pagination">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Назад
          </button>
          <span className="muted">
            {page} из {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Вперёд
          </button>
        </footer>
      ) : null}

      {draft ? (
        <div className="org-modal-backdrop" role="dialog" aria-modal="true">
          <div className={`org-modal${draft.id ? "" : " org-modal--import"}`}>
            <h3 className="org-modal-title">
              {draft.id ? "Изменить пользователя" : "Новый пользователь"}
            </h3>
            {!draft.id ? (
              <div className="org-create-mode" role="tablist" aria-label="Способ добавления">
                <button
                  type="button"
                  className={createMode === "manual" ? "active" : ""}
                  onClick={() => setCreateMode("manual")}
                >
                  Вручную
                </button>
                <button
                  type="button"
                  className={createMode === "import" ? "active" : ""}
                  onClick={() => setCreateMode("import")}
                >
                  Из файла
                </button>
              </div>
            ) : null}

            {draft.id || createMode === "manual" ? (
              <>
                <div className="org-modal-body org-form">
                  <label className="org-field">
                    <span>Email</span>
                    <input
                      className="input"
                      type="email"
                      value={draft.email}
                      onChange={(e) => setDraft({ ...draft, email: e.target.value })}
                    />
                  </label>
                  <label className="org-field">
                    <span>Имя</span>
                    <input
                      className="input"
                      value={draft.first_name}
                      onChange={(e) => setDraft({ ...draft, first_name: e.target.value })}
                    />
                  </label>
                  <label className="org-field">
                    <span>Фамилия</span>
                    <input
                      className="input"
                      value={draft.last_name}
                      onChange={(e) => setDraft({ ...draft, last_name: e.target.value })}
                    />
                  </label>
                  <label className="org-field">
                    <span>Роль</span>
                    <select
                      className="input"
                      value={draft.role}
                      onChange={(e) => setDraft({ ...draft, role: e.target.value as UserRole })}
                    >
                      <option value="minion">Пользователь</option>
                      <option value="admin">Администратор</option>
                      {isSuperadmin ? (
                        <option value="superadmin">Суперадминистратор</option>
                      ) : null}
                    </select>
                  </label>
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
                    onClick={() => void submitDraft()}
                    disabled={busy || !draft.email || !draft.first_name}
                  >
                    {busy ? "Сохраняем…" : "Сохранить"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <ImportTab orgId={orgId} embedded />
                <div className="org-modal-actions">
                  <button type="button" className="btn btn-ghost" onClick={() => setDraft(null)}>
                    Закрыть
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}

      {toRemove ? (
        <ConfirmDialog
          title="Удалить пользователя?"
          description={
            <p>
              {toRemove.full_name} будет удалён вместе со всеми выданными ему правами.
              Действие необратимо.
            </p>
          }
          busy={remove.isPending}
          onCancel={() => setToRemove(null)}
          onConfirm={() => void runAction(() => remove.mutateAsync(toRemove.id))}
        />
      ) : null}

      {accessFor ? (
        <UserAccessDialog
          orgId={orgId}
          user={accessFor}
          onClose={() => setAccessFor(null)}
        />
      ) : null}
    </section>
  );
}
