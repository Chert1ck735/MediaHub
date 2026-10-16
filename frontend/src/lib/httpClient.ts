/**
 * Централизованный HTTP-клиент. Один входной адаптер над браузерным fetch'ем.
 *
 * Зачем: до этой обёртки каждая из ~43 функций в src/api.ts руками собирала
 * заголовки (Content-Type, Authorization), руками делала JSON.stringify,
 * руками вытягивала токен из localStorage и руками разбирала тело ответа.
 * Дублирование = шанс что в каком-то одном месте отстанет от других и
 * протечёт баг.
 *
 * Тут:
 *   * один источник `Authorization` (JWT из localStorage по ключу JWT_KEY);
 *   * один источник `Content-Type: application/json` для тел-объектов;
 *   * один обработчик 401 → выкидываем токен и оповещаем приложение, чтобы
 *     показать форму логина (без жёсткого window.location.href, чтобы
 *     React-стейт не рассинхронился);
 *   * один обработчик 5xx / network failure → оповещаем приложение, чтобы
 *     показать toast (App.tsx подпишется в useEffect);
 *   * один разбор ошибочного payload через normalizeErrorDetail
 *     (понятный текст про упавший PostgreSQL, который раньше дублировался
 *     в fetchJson / fetchBlob).
 *
 * Что НЕ изменилось:
 *   * базовый URL по-прежнему берётся из `VITE_API_BASE_URL` или пуст
 *     (Vite proxy на /api → localhost:8000);
 *   * относительные пути / абсолютные обрабатываются ровно как в apiUrl()
 *     раньше — поведение совместимо с уже существующим кодом.
 */
import { JWT_KEY } from "./httpClientConstants";

const TOKEN_EXPIRED_EVENT = "httpClient:tokenExpired";
const SERVER_ERROR_EVENT = "httpClient:serverError";
const ABSOLUTE_URL_RE = /^[a-z][a-z\d+\-.]*:\/\//i;

/** Глобально оповещаем приложение, что токен истёк. App.tsx должен слушать
 *  это событие и сбрасывать authToken / открывать форму логина. */
function emitTokenExpired(): void {
  window.dispatchEvent(new CustomEvent(TOKEN_EXPIRED_EVENT));
}

/** Глобально оповещаем приложение об ошибке сервера (5xx или нет связи).
 *  App.tsx показывает toast — без этого пользователь видит «упал запрос»,
 *  но не понимает в чём дело. */
function emitServerError(message: string): void {
  window.dispatchEvent(new CustomEvent(SERVER_ERROR_EVENT, { detail: { message } }));
}

/** Подписка на «токен истёк». Возвращает функцию-отписку. */
export function onTokenExpired(handler: () => void): () => void {
  const listener = () => handler();
  window.addEventListener(TOKEN_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(TOKEN_EXPIRED_EVENT, listener);
}

/** Подписка на «сервер не отвечает». Возвращает функцию-отписку. */
export function onServerError(handler: (message: string) => void): () => void {
  const listener = (event: Event) => {
    const message = (event as CustomEvent<{ message: string }>).detail?.message ?? "";
    handler(message);
  };
  window.addEventListener(SERVER_ERROR_EVENT, listener);
  return () => window.removeEventListener(SERVER_ERROR_EVENT, listener);
}

function apiUrl(path: string): string {
  if (ABSOLUTE_URL_RE.test(path) || path.startsWith("//")) return path;
  const base = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
  if (!path.startsWith("/")) return `${base}/${path}`;
  return base ? `${base}${path}` : path;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(JWT_KEY) ?? "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Понятный текст ошибки. Раньше эта же функция жила в api.ts; перенёс её
 *  целиком, поведение идентично — оставляем спец-сообщение про PostgreSQL,
 *  потому что в dev'e это типичная боль. */
function normalizeErrorDetail(detail: string): string {
  try {
    const parsed = JSON.parse(detail) as { detail?: string; traceback?: string };
    const raw = parsed.detail?.trim() || detail;
    if (
      raw.includes("Connect call failed") ||
      raw.includes("127.0.0.1', 5432") ||
      raw.includes("::1', 5432")
    ) {
      return "База данных PostgreSQL недоступна. Проверьте, что Postgres запущен и слушает localhost:5432.";
    }
    return raw;
  } catch {
    if (
      detail.includes("Connect call failed") ||
      detail.includes("127.0.0.1', 5432") ||
      detail.includes("::1', 5432")
    ) {
      return "База данных PostgreSQL недоступна. Проверьте, что Postgres запущен и слушает localhost:5432.";
    }
    return detail;
  }
}

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  signal?: AbortSignal;
  /** Тело запроса. Объект — будет завернут в JSON.stringify, FormData /
   *  Blob — отправляется как есть без Content-Type. */
  body?: unknown;
  /** Доп-заголовки. Перекрывают дефолтные (Content-Type, Authorization). */
  headers?: Record<string, string>;
  /** Если true — Authorization не подставляется. Нужно редко (публичные
   *  эндпоинты login / register). */
  skipAuth?: boolean;
  /** Если true — возвращаем Response.blob() вместо JSON. */
  expectBlob?: boolean;
  /** Если true — возвращаем Response.text() без JSON.parse. */
  expectText?: boolean;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && value.constructor === Object;
}

function buildRequestInit(method: HttpMethod, options: RequestOptions): RequestInit {
  const headers: Record<string, string> = {
    ...(options.skipAuth ? {} : authHeaders()),
    ...(options.headers ?? {}),
  };

  let body: BodyInit | undefined;
  if (options.body !== undefined && options.body !== null) {
    if (options.body instanceof FormData || options.body instanceof Blob) {
      // FormData сам выставляет multipart boundary в Content-Type, поэтому
      // не трогаем заголовки; Blob — caller сам знает что делает.
      body = options.body;
    } else if (isPlainObject(options.body) || Array.isArray(options.body)) {
      body = JSON.stringify(options.body);
      if (!headers["Content-Type"]) headers["Content-Type"] = "application/json";
    } else if (typeof options.body === "string") {
      body = options.body;
    } else {
      // unexpected тип — поднимаем явно, чем молча ронять fetch на runtime.
      throw new TypeError("httpClient: неподдерживаемый тип body");
    }
  }

  return { method, headers, body, cache: "no-store", signal: options.signal };
}

async function readErrorBody(res: Response): Promise<string> {
  try {
    return (await res.text()) || res.statusText;
  } catch {
    return res.statusText;
  }
}

async function execute<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), buildRequestInit(method, options));
  } catch (error) {
    // TypeError здесь = network failure (CORS, нет соединения, прокси упал).
    if (error instanceof TypeError) {
      const message =
        "Не удалось связаться с сервером. Проверьте соединение и повторите запрос.";
      emitServerError(message);
      throw new Error(message);
    }
    throw error;
  }

  if (!res.ok) {
    if (res.status === 401) {
      // Токен истёк / отозван. Чистим JWT и оповещаем приложение, чтобы
      // показалась форма логина. Без жёсткого window.location, потому что
      // React-роутер должен сам решить куда вести.
      localStorage.removeItem(JWT_KEY);
      emitTokenExpired();
    } else if (res.status >= 500) {
      emitServerError(`Сервер ответил ${res.status}. Попробуйте ещё раз через минуту.`);
    }
    if (res.status === 414 || res.status === 431) {
      const message = "Запрос слишком большой. Уменьшите число выбранных площадок и повторите запрос.";
      emitServerError(message);
      throw new Error(message);
    }
    const detail = await readErrorBody(res);
    throw new Error(normalizeErrorDetail(detail || `HTTP ${res.status}`));
  }

  if (options.expectBlob) {
    return (await res.blob()) as unknown as T;
  }

  const text = await res.text();
  if (!text.trim()) return undefined as T;
  if (options.expectText) return text as T;
  const contentType = res.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return text as T;
  }
  return JSON.parse(text) as T;
}

export const httpClient = {
  get: <T>(path: string, options?: Omit<RequestOptions, "body">) =>
    execute<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    execute<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    execute<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    execute<T>("PATCH", path, { ...options, body }),
  delete: <T = void>(path: string, options?: Omit<RequestOptions, "body">) =>
    execute<T>("DELETE", path, options),
  getBlob: (path: string, options?: Omit<RequestOptions, "body" | "expectBlob">) =>
    execute<Blob>("GET", path, { ...options, expectBlob: true }),
  postBlob: (path: string, body?: unknown, options?: Omit<RequestOptions, "body" | "expectBlob">) =>
    execute<Blob>("POST", path, { ...options, body, expectBlob: true }),
  getText: (path: string, options?: Omit<RequestOptions, "body" | "expectText">) =>
    execute<string>("GET", path, { ...options, expectText: true }),
  postText: (path: string, body?: unknown, options?: Omit<RequestOptions, "body" | "expectText">) =>
    execute<string>("POST", path, { ...options, body, expectText: true }),
};
