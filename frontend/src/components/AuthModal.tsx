import { useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";

import { authConfirmPasswordReset, authRequestPasswordReset } from "../api";
import { MESSAGE_STATUS } from "../constants";

import type { MessageType } from "../app/types";

export type AuthModalProps = {
  open: boolean;
  authTitle: string;
  authLoading: boolean;
  authMessage: string;
  authMessageType: MessageType;
  email: string;
  password: string;
  showPassword: boolean;
  rememberMe: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onSetEmail: Dispatch<SetStateAction<string>>;
  onSetPassword: Dispatch<SetStateAction<string>>;
  onSetShowPassword: Dispatch<SetStateAction<boolean>>;
  onSetRememberMe: Dispatch<SetStateAction<boolean>>;
};

export function AuthModal({
  open,
  authTitle,
  authLoading,
  authMessage,
  authMessageType,
  email,
  password,
  showPassword,
  rememberMe,
  onSubmit,
  onSetEmail,
  onSetPassword,
  onSetShowPassword,
  onSetRememberMe,
}: AuthModalProps) {
  const [resetOpen, setResetOpen] = useState(false);

  if (!open) return null;

  if (resetOpen) {
    return <PasswordResetScreen authTitle={authTitle} onBack={() => setResetOpen(false)} />;
  }

  const togglePasswordVisibility = () => onSetShowPassword((value) => !value);

  return (
    <section className="auth-screen">
      <div className="auth-screen-bg" />
      <div className="auth-layout">
        <aside className="auth-value">
          <p className="badge">СИГМА</p>
          <h2 className="auth-value-title">Мониторинг и анализ пабликов</h2>
          <p className="auth-value-lead">
            Возвращайтесь в единое рабочее пространство и продолжайте с того места, где остановились.
          </p>
          <div className="auth-value-list">
            <p>Единый контур: идеи, генерация, публикация</p>
            <p>Прозрачные статусы и быстрый цикл контента</p>
            <p>Без лишних шагов и лишнего интерфейса</p>
          </div>
          <div className="auth-value-metrics">
            <div>
              <strong>&lt; 1 мин</strong>
              <span>вход в работу</span>
            </div>
            <div>
              <strong>3 шага</strong>
              <span>от идеи до поста</span>
            </div>
          </div>
        </aside>

        <div className="auth-page">
          <div className="auth-page-top">
            <div className="auth-page-brand" aria-label={authTitle}>
              <span className="auth-page-logo-mark">Σ</span>
              <span className="auth-page-logo-copy">
                <span className="auth-page-logo-text">СИГМА</span>
                <span className="auth-page-logo-note">Система интеллектуального анализа пабликов</span>
              </span>
            </div>
            <div className="auth-page-divider" />
            <h2 className="auth-page-title">{authTitle}</h2>
          </div>
          <form className="form auth-page-form" onSubmit={onSubmit}>
            <label className="field-label">
              <span>Электронная почта</span>
              <span className="email-input-row">
                <input
                  type="email"
                  value={email}
                  onChange={(event) => onSetEmail(event.target.value)}
                  placeholder="name@mail.com"
                  required
                />
              </span>
            </label>
            <label className="field-label">
              Пароль
              <div className="password-input-wrap">
                <input
                  type={showPassword ? "text" : "password"}
                  minLength={8}
                  value={password}
                  onChange={(event) => onSetPassword(event.target.value)}
                  placeholder="Пароль"
                  required
                />
                <PasswordToggle showPassword={showPassword} onToggle={togglePasswordVisibility} />
              </div>
            </label>
            <label className="checkbox-line">
              <input type="checkbox" checked={rememberMe} onChange={(event) => onSetRememberMe(event.target.checked)} />
              Запомнить меня на этом устройстве
            </label>
            <button className="btn btn-primary" type="submit">
              {authLoading ? "Проверка..." : "Войти"}
            </button>
            <button type="button" className="auth-link" onClick={() => setResetOpen(true)}>
              Забыли пароль?
            </button>
          </form>
          <p className={`message ${authMessageType}`}>{authMessage}</p>
        </div>
      </div>
    </section>
  );
}

function PasswordResetScreen({ authTitle, onBack }: { authTitle: string; onBack: () => void }) {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<MessageType>(MESSAGE_STATUS.IDLE);

  const fail = (err: unknown) => {
    setMessageType(MESSAGE_STATUS.ERROR);
    setMessage(err instanceof Error ? err.message : "Ошибка сервера");
  };

  const requestCode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    try {
      await authRequestPasswordReset(email.trim().toLowerCase());
      setStep("code");
      setMessageType(MESSAGE_STATUS.SUCCESS);
      // Успех не означает, что адрес существует: сервер отвечает одинаково всем.
      setMessage("Если такая почта зарегистрирована, код отправлен. Проверьте письмо.");
    } catch (err) {
      fail(err);
    } finally {
      setLoading(false);
    }
  };

  const confirmReset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    try {
      await authConfirmPasswordReset(email.trim().toLowerCase(), code.trim(), password);
      setMessageType(MESSAGE_STATUS.SUCCESS);
      setMessage("Пароль изменён. Войдите с новым паролем.");
      setTimeout(onBack, 1500);
    } catch (err) {
      fail(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="auth-screen">
      <div className="auth-screen-bg" />
      <div className="auth-layout">
        <div className="auth-page">
          <div className="auth-page-top">
            <div className="auth-page-brand" aria-label={authTitle}>
              <span className="auth-page-logo-mark">Σ</span>
              <span className="auth-page-logo-copy">
                <span className="auth-page-logo-text">СИГМА</span>
                <span className="auth-page-logo-note">Восстановление доступа</span>
              </span>
            </div>
            <div className="auth-page-divider" />
            <h2 className="auth-page-title">Смена пароля</h2>
          </div>

          {step === "email" ? (
            <form className="form auth-page-form" onSubmit={requestCode}>
              <label className="field-label">
                <span>Электронная почта</span>
                <span className="email-input-row">
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="name@mail.com"
                    required
                  />
                </span>
              </label>
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? "Отправка..." : "Получить код"}
              </button>
              <button type="button" className="auth-link" onClick={onBack}>
                Вернуться ко входу
              </button>
            </form>
          ) : (
            <form className="form auth-page-form" onSubmit={confirmReset}>
              <label className="field-label">
                <span>Код из письма</span>
                <span className="email-input-row">
                  <input
                    inputMode="numeric"
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    placeholder="123456"
                    maxLength={6}
                    required
                  />
                </span>
              </label>
              <label className="field-label">
                <span>Новый пароль</span>
                <span className="email-input-row">
                  <input
                    type="password"
                    minLength={8}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="Минимум 8 символов"
                    required
                  />
                </span>
              </label>
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? "Сохранение..." : "Сменить пароль"}
              </button>
              <button type="button" className="auth-link" onClick={() => setStep("email")}>
                Запросить код заново
              </button>
            </form>
          )}
          <p className={`message ${messageType}`}>{message}</p>
        </div>
      </div>
    </section>
  );
}

function PasswordToggle({ showPassword, onToggle }: { showPassword: boolean; onToggle: () => void }) {
  const label = showPassword ? "Скрыть пароль" : "Показать пароль";

  return (
    <button type="button" className="password-toggle" aria-label={label} title={label} onClick={onToggle}>
      {showPassword ? (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 3l18 18" />
          <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
          <path d="M9.9 4.4A10.8 10.8 0 0 1 12 4c5 0 8.6 4.1 10 8a12.4 12.4 0 0 1-3 4.6" />
          <path d="M6.4 6.5A12.7 12.7 0 0 0 2 12c1.4 3.9 5 8 10 8 1.5 0 2.9-.4 4.1-1" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M2 12s3.6-8 10-8 10 8 10 8-3.6 8-10 8S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      )}
    </button>
  );
}
