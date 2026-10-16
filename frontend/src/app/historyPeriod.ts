/** Период истории при первом добавлении площадки: «за N дней/недель/месяцев».
 *
 *  Используется и ручным добавлением ссылки, и импортом из таблицы, чтобы
 *  оба пути тянули прошлое одинаково.
 */
export type HistoryUnit = "days" | "weeks" | "months";

export const HISTORY_UNITS: { value: HistoryUnit; label: string }[] = [
  { value: "days", label: "дней" },
  { value: "weeks", label: "недель" },
  { value: "months", label: "месяцев" },
];

export function historyDateFrom(amount: number, unit: HistoryUnit): Date {
  const date = new Date();
  const n = Math.max(1, Math.trunc(amount) || 1);
  if (unit === "days") date.setDate(date.getDate() - n);
  else if (unit === "weeks") date.setDate(date.getDate() - n * 7);
  else date.setMonth(date.getMonth() - n);
  return date;
}
