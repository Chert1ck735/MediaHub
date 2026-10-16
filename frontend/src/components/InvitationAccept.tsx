import { useEffect, useState, type FormEvent } from "react";

import { authAcceptInvitation, authInvitationStatus, JWT_KEY, type AuthResponse, type InvitationStatusResponse } from "../api";

export function InvitationAccept({
  token,
  onAccepted,
  onCancel,
}: {
  token: string;
  onAccepted: (result: AuthResponse) => void;
  onCancel: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusLoading, setStatusLoading] = useState(true);
  const [invitationStatus, setInvitationStatus] = useState<InvitationStatusResponse | null>(null);

  useEffect(() => {
    let alive = true;
    setStatusLoading(true);
    setMessage("");
    authInvitationStatus(token)
      .then((result) => {
        if (alive) setInvitationStatus(result);
      })
      .catch((error) => {
        if (!alive) return;
        setInvitationStatus({
          status: "invalid",
          email: null,
          message: error instanceof Error ? error.message : "Не удалось проверить приглашение.",
        });
      })
      .finally(() => {
        if (alive) setStatusLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [token]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirmation) {
      setMessage("Пароли не совпадают.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const result = await authAcceptInvitation(token, password);
      localStorage.setItem(JWT_KEY, result.access_token);
      onAccepted(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось принять приглашение");
    } finally {
      setLoading(false);
    }
  };

  const canAccept = invitationStatus?.status === "pending";

  return (
    <section className="auth-screen">
      <div className="auth-screen-bg" />
      <div className="auth-layout">
        <div className="auth-page">
          <div className="auth-page-top">
            <div className="auth-page-brand">
              <span className="auth-page-logo-mark">Σ</span>
              <span className="auth-page-logo-copy">
                <span className="auth-page-logo-text">СИГМА</span>
              </span>
            </div>
            <div className="auth-page-divider" />
            <h2 className="auth-page-title">Принять приглашение</h2>
          </div>
          {statusLoading ? (
            <p>Проверяем приглашение…</p>
          ) : canAccept ? (
            <>
              <p>
                Задайте пароль для своей учётной записи
                {invitationStatus?.email ? ` (${invitationStatus.email})` : ""}.
              </p>
              <form className="form auth-page-form" onSubmit={submit}>
                <label className="field-label">
                  Пароль
                  <input
                    type="password"
                    minLength={8}
                    maxLength={200}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    required
                  />
                </label>
                <label className="field-label">
                  Повторите пароль
                  <input
                    type="password"
                    minLength={8}
                    maxLength={200}
                    value={confirmation}
                    onChange={(event) => setConfirmation(event.target.value)}
                    autoComplete="new-password"
                    required
                  />
                </label>
                <button className="btn btn-primary" type="submit" disabled={loading}>
                  {loading ? "Активация…" : "Задать пароль и войти"}
                </button>
              </form>
            </>
          ) : (
            <div className="message success" style={{ marginTop: 12 }}>
              <strong>
                {invitationStatus?.status === "accepted"
                  ? "Аккаунт уже создан"
                  : "Приглашение недоступно"}
              </strong>
              <div style={{ marginTop: 6 }}>
                {invitationStatus?.message || "Перейдите к обычному входу."}
              </div>
              {invitationStatus?.email ? (
                <div style={{ marginTop: 6 }}>Почта: {invitationStatus.email}</div>
              ) : null}
            </div>
          )}
          {message ? <p className="message error">{message}</p> : null}
          <p className="switch-text">
            <button type="button" className="link-btn" onClick={onCancel}>
              Перейти к обычному входу
            </button>
          </p>
        </div>
      </div>
    </section>
  );
}
