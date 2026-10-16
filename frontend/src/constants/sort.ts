// Опции сортировки списков. Значения отправляются в API / хранятся в URL,
// поэтому строковые ключи зафиксированы — менять без согласования с бэком нельзя.

export const INFO_EVENT_SORT = {
  EVENT_DATE_DESC: "event_date_desc",
  EVENT_DATE_ASC: "event_date_asc",
} as const;

export type InfoEventSort = (typeof INFO_EVENT_SORT)[keyof typeof INFO_EVENT_SORT];
