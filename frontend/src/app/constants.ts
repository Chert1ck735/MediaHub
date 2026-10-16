import type { EventStatus, InfoEventForm } from "./types";
import { toInputDate } from "./utils";

export const SESSION_KEY = "protechno_session";
export const THEME_KEY = "protechno_theme";
export const ANALYTICS_SETTINGS_KEY = "protechno_analytics_settings";
export const WEEK_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
export const MAX_ATTACHMENT_BYTES = 220 * 1024;
export const VK_MESSAGE_MAX = 3900;
export const SMART_POST_TYPES = [
  { value: "news", label: "Новость" },
  { value: "event", label: "Событие" },
  { value: "announcement", label: "Анонс" },
  { value: "congrats", label: "Поздравление" },
  { value: "product", label: "Продукт/сервис" },
  { value: "achievement", label: "Достижение" },
  { value: "education", label: "Обучение" },
  { value: "initiative", label: "Инициатива" },
] as const;

export const statusLabel: Record<EventStatus, string> = {
  draft: "Черновик",
  scheduled: "Запланирован",
  published: "Опубликован",
};

export const painPriorityLabel: Record<string, string> = {
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
  critical: "Критический",
};

export const sentimentLabel: Record<string, string> = {
  positive: "Позитивные",
  neutral: "Нейтральные",
  negative: "Негативные",
};

export const relevanceLabel: Record<string, string> = {
  relevant: "По теме",
  irrelevant: "Не по теме",
};

export const messageTypeLabel: Record<string, string> = {
  complaint: "Жалобы",
  request: "Запросы",
  gratitude: "Благодарности",
  offtopic: "Прочее",
  sarcasm: "Сарказм",
};

export const defaultInfoEventForm = (): InfoEventForm => ({
  title: "",
  eventDate: toInputDate(new Date()),
  location: "",
  description: "",
});
