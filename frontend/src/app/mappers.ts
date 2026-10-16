import type { ApiCalendarEvent, ApiPost } from "../api";
import { parseInputDate, utcCalendarToLocal } from "./utils";
import type { CalendarEvent, ContentEvent, EventStatus } from "./types";

export function apiPostToContentEvent(post: ApiPost): ContentEvent {
  const vkPublication = (post.publications ?? []).find((publication) => publication.platform?.toLowerCase() === "vk");
  const publicationLabels = (post.publications ?? []).map((publication) => {
    const title = publication.public_title?.trim();
    const url = publication.public_url?.trim();
    if (title) return title;
    if (url) return url.replace(/^https?:\/\//, "");
    return publication.platform.toUpperCase();
  });

  return {
    id: post.id,
    title: post.title,
    origin: post.origin ?? null,
    prompt: post.text_draft ?? "",
    tone: post.tone ?? "",
    generatedText: post.text_generated ?? "",
    status: post.status,
    createdAt: post.created_at,
    strategyId: post.strategy_id ?? null,
    vkWallUrl: post.vk_wall_url ?? undefined,
    vkPostId: post.vk_post_id ? Number(post.vk_post_id) : undefined,
    publicationIds: (post.publications ?? []).map((publication) => publication.id),
    vkPublicationId: vkPublication?.id,
    publicationLabels,
    vkPublicSocialLinkId: vkPublication?.public_social_link_id,
  };
}

export function apiCalendarEventToCalendarEvent(event: ApiCalendarEvent): CalendarEvent {
  const localStart = utcCalendarToLocal(event.date, event.start_time);
  const localEnd = utcCalendarToLocal(event.date, event.end_time);

  return {
    id: event.id,
    title: event.title,
    origin: event.origin ?? null,
    date: localStart.date,
    startTime: localStart.time,
    endTime: localEnd.time,
    description: event.description,
    status: event.status as EventStatus,
    platforms: event.platforms,
    draft: event.draft ?? "",
    tone: event.tone ?? "",
    postType: event.post_type ?? "",
    postId: event.post_id ?? undefined,
    publicationIds: event.publication_ids ?? [],
    publicSocialLinkIds: event.public_social_link_ids ?? [],
    publicationUrls: event.publication_urls ?? [],
    dayTotal: event.day_total ?? 0,
    infoEventId: event.info_event_id ?? null,
    infoEventTitle: event.info_event_title ?? null,
    inheritedPainIds: event.inherited_pain_ids ?? [],
    inheritedPainTitles: event.inherited_pain_titles ?? [],
  };
}

export function focusCalendarOnDate(
  date: string,
  setSelectedDay: (value: string) => void,
  setCalendarDate: (value: Date) => void,
) {
  setSelectedDay(date);
  setCalendarDate(parseInputDate(date));
}
