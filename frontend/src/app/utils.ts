import { DEFAULT_EVENT_SLOT_MS } from "../constants";
import type { SeriesPlanItem } from "./types";


export const createClientId = (): string => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0"));
    return [
      hex.slice(0, 4).join(""),
      hex.slice(4, 6).join(""),
      hex.slice(6, 8).join(""),
      hex.slice(8, 10).join(""),
      hex.slice(10, 16).join(""),
    ].join("-");
  }

  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
};

export const formatMetricValue = (value: number | null | undefined): string => {
  if (value == null || Number.isNaN(value)) return "—";
  const hasFraction = Math.abs(value % 1) > 0.001;
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: hasFraction ? 1 : 0 }).format(value);
};

export const formatChartDate = (value: string): string => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
};

export const cropText = (value: string, max = 140): string => {
  const normalized = stripVkMentions(value);
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max).trim()}…`;
};

/** Чистит VK-разметку `[id123|Иван]` только для показа — в БД текст не трогаем.
 *
 *  После выреза обращения остаётся висячая пунктуация («[id|Иван], запишитесь»
 *  → «, запишитесь»), поэтому подчищаем пробел перед знаком, дубли знаков и
 *  пунктуацию в начале строки.
 */
export const stripVkMentions = (value: string): string => {
  if (!value) return "";
  return value
    .replace(/\[[^\]]+\]/g, "")
    .replace(/\s+([,.!?;:])/g, "$1")
    .replace(/([,;:])\s*(?=[,.!?;:])/g, "")
    .replace(/^[\s,;:.!?]+/, "")
    .replace(/\s+/g, " ")
    .trim();
};

export const cropTitleWords = (value: string, maxWords = 5): string => {
  const words = value.replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  if (words.length <= maxWords) return words.join(" ");
  return `${words.slice(0, maxWords).join(" ")}…`;
};

export const localCalendarToUtcPayload = (date: string, time: string): { date: string; time: string } => {
  const local = new Date(`${date}T${time}:00`);
  return {
    date: `${local.getUTCFullYear()}-${String(local.getUTCMonth() + 1).padStart(2, "0")}-${String(local.getUTCDate()).padStart(2, "0")}`,
    time: `${String(local.getUTCHours()).padStart(2, "0")}:${String(local.getUTCMinutes()).padStart(2, "0")}`,
  };
};

export const utcCalendarToLocal = (date: string, time: string): { date: string; time: string } => {
  const utc = new Date(`${date}T${time}:00Z`);
  return {
    date: toInputDate(utc),
    time: `${String(utc.getHours()).padStart(2, "0")}:${String(utc.getMinutes()).padStart(2, "0")}`,
  };
};

export const shiftDateTime = (date: string, time: string, minutesToAdd: number): { date: string; time: string } => {
  const base = new Date(`${date}T${time}:00`);
  if (Number.isNaN(base.getTime())) return { date, time };
  base.setMinutes(base.getMinutes() + minutesToAdd);
  return {
    date: toInputDate(base),
    time: `${String(base.getHours()).padStart(2, "0")}:${String(base.getMinutes()).padStart(2, "0")}`,
  };
};

export const buildSeriesPlanItems = (
  count: number,
  stepMinutes: number,
  baseTitle: string,
  baseDescription: string,
  basePostType: string,
  existing: SeriesPlanItem[] = [],
): SeriesPlanItem[] =>
  Array.from({ length: count }, (_, index) => {
    const prev = existing[index];
    return {
      id: prev?.id ?? createClientId(),
      index,
      title: prev?.title ?? (count > 1 ? `${baseTitle} · ${index + 1}/${count}` : baseTitle),
      description: prev?.description ?? baseDescription,
      postType: prev?.postType ?? basePostType,
      offsetMinutes: prev?.offsetMinutes ?? index * stepMinutes,
    };
  });

export function readFileAsDataURL(file: File, maxBytes: number): Promise<string> {
  return new Promise((resolve, reject) => {
    if (file.size > maxBytes) {
      reject(new Error(`Файл больше ${Math.round(maxBytes / 1024)} КБ`));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
    reader.readAsDataURL(file);
  });
}

export function cleanGeneratedPostText(value: string): string {
  return value
    .replace(/^\s*(вот\s+(ваш|готовый)\s+пост|ниже\s+пост|готовый\s+пост|пост\s+для\s+публикации)\s*:\s*/gim, "")
    .replace(/\*\*\s*(Заголовок-крючок|Тело поста|Профит|Призыв к действию(?:\s*\(CTA\))?|CTA)\s*:\s*\*\*/gi, "")
    .replace(/^\s*(Заголовок-крючок|Тело поста|Профит|Призыв к действию(?:\s*\(CTA\))?|CTA)\s*:\s*/gim, "")
    .replace(/\*\*/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function dataUrlToFile(dataUrl: string, filename: string): File | null {
  try {
    const [header, base64] = dataUrl.split(",");
    if (!header || !base64) return null;
    const mimeMatch = header.match(/data:([^;]+);base64/i);
    const mime = mimeMatch ? mimeMatch[1] : "image/jpeg";
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    const safeName = filename && /\.[a-z0-9]+$/i.test(filename)
      ? filename
      : `${filename || "photo"}.${mime.split("/")[1] || "jpg"}`;
    return new File([bytes], safeName, { type: mime });
  } catch {
    return null;
  }
}

export const toInputDate = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

export const parseInputDate = (value: string): Date => {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
};

export const startOfWeek = (date: Date): Date => {
  const result = new Date(date);
  const day = result.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  result.setDate(result.getDate() + diff);
  result.setHours(0, 0, 0, 0);
  return result;
};

export function buildBarItems<T extends string>(items: Array<{ key: T; label: string; count: number; accent?: string }>) {
  const filtered = items.filter((item) => item.count > 0);
  const maxCount = Math.max(1, ...filtered.map((item) => item.count), 0);
  return filtered.map((item) => ({
    ...item,
    width: `${Math.max(14, Math.round((item.count / maxCount) * 100))}%`,
  }));
}

export const buildCalendarUrl = (title: string, date: string, time: string) => {
  const [year, month, day] = date.split("-").map(Number);
  const [hours, minutes] = time.split(":").map(Number);
  const start = new Date(year, month - 1, day, hours, minutes);
  const end = new Date(start.getTime() + DEFAULT_EVENT_SLOT_MS);
  const fmt = (value: Date) =>
    `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}` +
    `T${String(value.getHours()).padStart(2, "0")}:${String(value.getMinutes()).padStart(2, "0")}:00`;
  const params = new URLSearchParams({
    name: title,
    from: fmt(start),
    to: fmt(end),
    description: "Событие создано в сервисе СИГМА",
  });
  return `https://calendar.yandex.ru/event/create?${params.toString()}`;
};
