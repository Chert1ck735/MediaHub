import {
  apiGetVkDefaultPublic,
  authLogin,
  JWT_KEY,
  getStoredToken,
} from "../api";
import { SESSION_KEY } from "../app/constants";
import { MESSAGE_STATUS } from "../constants";

export function openAuthModal(mode: "login", options: { reset?: boolean } | undefined, ctx: any) {
  const shouldReset = options?.reset ?? true;
  ctx.setAuthMode(mode);
  if (shouldReset) {
    ctx.setEmail("");
    ctx.setPassword("");
    ctx.setAuthMessage("");
    ctx.setAuthMessageType(MESSAGE_STATUS.IDLE);
  }
  ctx.setAuthModalOpen(true);
}

export async function submitAuth(event: any, ctx: any) {
  event.preventDefault();
  const normalizedEmail = ctx.email.trim().toLowerCase();
  const trimmedPassword = ctx.password.trim();

  if (!normalizedEmail || !trimmedPassword) {
    ctx.setAuthMessageType(MESSAGE_STATUS.ERROR);
    ctx.setAuthMessage("Пожалуйста, заполните все поля.");
    return;
  }
  ctx.setAuthLoading(true);
  try {
    const res = await authLogin(normalizedEmail, trimmedPassword);

    localStorage.setItem(JWT_KEY, res.access_token);
    if (ctx.rememberMe) {
      localStorage.setItem(SESSION_KEY, res.email);
      sessionStorage.removeItem(SESSION_KEY);
    } else {
      sessionStorage.setItem(SESSION_KEY, res.email);
      localStorage.removeItem(SESSION_KEY);
    }
    ctx.setAuthToken(res.access_token);
    ctx.setCurrentUser(res.email);
    ctx.setAuthMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setAuthMessage("Вход выполнен. Добро пожаловать!");
    try {
      await apiGetVkDefaultPublic(res.access_token);
    } catch {
      // Не блокируем вход, если дефолтный VK-паблик сейчас не удалось получить/создать.
    }
    ctx.setAuthModalOpen(false);
    ctx.setPassword("");
    const redirectPath = new URLSearchParams(ctx.location.search).get("redirect") ?? "/";
    ctx.navigate(redirectPath, { replace: true });
  } catch (err) {
    ctx.setAuthMessageType(MESSAGE_STATUS.ERROR);
    ctx.setAuthMessage(err instanceof Error ? err.message : "Ошибка сервера");
  } finally {
    ctx.setAuthLoading(false);
  }
}

export function logoutAction(ctx: any) {
  localStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(JWT_KEY);
  ctx.setCurrentUser("");
  ctx.setAuthToken("");
  ctx.setEvents([]);
  ctx.setInfoEvents([]);
  ctx.setContentEvents([]);
}

export function shouldPromptInitialLogin(currentUser: string) {
  return !currentUser && !getStoredToken();
}
