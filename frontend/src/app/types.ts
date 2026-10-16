import type { EventStatus } from "../constants/status";

export type AuthMode = "login";


// Перенесено в src/constants/status.ts; здесь оставлен re-export, чтобы не
// ломать существующие импорты `import { MessageType } from "./types"`.
export type { MessageType } from "../constants/status";

export type { CalendarView } from "../constants/status";

export type { EventStatus } from "../constants/status";

// Перенесено в src/constants/theme.ts; здесь re-export для совместимости.
export type { ThemeMode } from "../constants/theme";

export type { ReportPeriod } from "../constants/status";
export type { ReportPlatform } from "../constants/status";

export type { AnalyticsView } from "../constants/status";
export type { PainSeverityFilter } from "../constants/status";

export type SmartEntryMode = "content" | "calendar";

export type CalendarEvent = {
  id: string;
  title: string;
  origin?: string | null;
  date: string;
  startTime: string;
  endTime: string;
  description: string;
  status: EventStatus;
  platforms: string[];
  draft: string;
  tone: string;
  postType: string;
  postId?: string;
  publicationIds?: string[];
  publicSocialLinkIds?: string[];
  publicationUrls?: Array<string | null>;
  // Всего публикаций в этом дне: в ответе их несколько на день.
  dayTotal?: number;
  infoEventId?: string | null;
  infoEventTitle?: string | null;
  inheritedPainIds?: string[];
  inheritedPainTitles?: string[];
};

export type ContentEvent = {
  id: string;
  title: string;
  origin?: string | null;
  prompt: string;
  tone: string;
  generatedText: string;
  status?: string;
  attachmentName?: string;
  attachmentDataUrl?: string;
  createdAt: string;
  strategyId?: string | null;
  vkWallUrl?: string;
  vkPostId?: number;
  vkPublishError?: string;
  publicationIds?: string[];
  vkPublicationId?: string;
  publicationLabels?: string[];
  vkPublicSocialLinkId?: string;
};

export type SeriesPlanItem = {
  id: string;
  index: number;
  title: string;
  description: string;
  postType: string;
  offsetMinutes: number;
};

export type InfoEventForm = {
  title: string;
  eventDate: string;
  location: string;
  description: string;
};
