// Тема оформления. Значения хранятся в localStorage (THEME_KEY) и используются
// как className-модификаторы в CSS, поэтому строковые ключи зафиксированы.

export const THEME = {
  DARK_RED: "dark-red",
  LIGHT_BLUE: "light-blue",
} as const;

export type ThemeMode = (typeof THEME)[keyof typeof THEME];
