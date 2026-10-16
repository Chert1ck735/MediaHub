// Настройки аналитики живут на странице «Настройки», а применяются на странице
// «Аналитика». Между этими экранами их держит shell-состояние, а между сессиями —
// localStorage: иначе тумблер, выставленный в настройках, сбрасывался бы на каждый
// перезаход, и пользователь не понимал бы, почему отчёт снова считается без LLM.

import { ANALYTICS_SETTINGS_KEY } from "./constants";

export type AnalyticsSettings = {
  deepLlmAnalysis: boolean;
  prefilterEnabled: boolean;
};

const DEFAULTS: AnalyticsSettings = {
  deepLlmAnalysis: false,
  prefilterEnabled: false,
};

export function readAnalyticsSettings(): AnalyticsSettings {
  try {
    const raw = localStorage.getItem(ANALYTICS_SETTINGS_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<AnalyticsSettings>;
    return {
      deepLlmAnalysis: parsed.deepLlmAnalysis === true,
      prefilterEnabled: parsed.prefilterEnabled === true,
    };
  } catch {
    return DEFAULTS;
  }
}

export function writeAnalyticsSettings(value: AnalyticsSettings): void {
  try {
    localStorage.setItem(ANALYTICS_SETTINGS_KEY, JSON.stringify(value));
  } catch {
    /* приватный режим / переполненное хранилище — настройка просто не переживёт сессию */
  }
}
