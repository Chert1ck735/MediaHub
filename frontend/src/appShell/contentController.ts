import { apiCreatePublication, apiDeletePost, apiUpdatePostVk, apiUpdatePublication, vkDeletePost, vkPoster, vkUploadPhoto } from "../api";
import { apiPostToContentEvent } from "../app/mappers";
import { EVENT_STATUS, MESSAGE_STATUS, REPORT_PLATFORM } from "../constants";
import { dataUrlToFile } from "../app/utils";

export async function removeContentEventAction(id: string, ctx: any) {
  const previousContent = ctx.contentEvents;
  const previousEvents = ctx.events;
  ctx.deletedPostIdsRef.current.add(id);
  ctx.calendarReloadSeqRef.current += 1;
  ctx.contentReloadSeqRef.current += 1;
  ctx.setContentEvents((prev: any[]) => prev.filter((item) => item.id !== id));
  ctx.setEvents((prev: any[]) => prev.filter((event) => event.id !== id && event.postId !== id));

  if (!ctx.authToken) return;

  try {
    await apiDeletePost(ctx.authToken, id);
  } catch (err) {
    ctx.deletedPostIdsRef.current.delete(id);
    ctx.setContentEvents(previousContent);
    ctx.setEvents(previousEvents);
    ctx.setContentMessageType(MESSAGE_STATUS.ERROR);
    ctx.setContentMessage(err instanceof Error ? err.message : "Не удалось удалить пост.");
  }
}

export async function publishContentEventToVkAction(item: any, imageFile: File | null | undefined, ctx: any) {
  const body = item.generatedText.trim() || item.prompt.trim();
  const text = body ? `${item.title}\n\n${body}` : item.title;
  const message = text.slice(0, ctx.VK_MESSAGE_MAX);
  if (!message.trim()) {
    throw new Error("Пустой текст для VK.");
  }
  let attachments: string | null = null;
  if (imageFile) {
    attachments = await vkUploadPhoto(ctx.authToken, imageFile);
  }
  const vk = await vkPoster(ctx.authToken, { message, attachments, from_group: true });
  return { url: vk.url, postId: vk.post_id };
}

export async function syncPublishedVkPostAction(postId: string, publicationId: string | undefined, publicSocialLinkId: string | undefined, vk: { url: string; postId: number }, ctx: any) {
  const publishedAt = new Date().toISOString();
  if (publicationId) {
    return apiUpdatePublication(ctx.authToken, publicationId, {
      public_social_link_id: publicSocialLinkId ?? null,
      status: EVENT_STATUS.PUBLISHED,
      external_post_id: String(vk.postId),
      url: vk.url,
      published_at: publishedAt,
    });
  }
  return apiCreatePublication(ctx.authToken, postId, {
    platform: REPORT_PLATFORM.VK,
    public_social_link_id: publicSocialLinkId ?? null,
    status: EVENT_STATUS.PUBLISHED,
    external_post_id: String(vk.postId),
    url: vk.url,
    published_at: publishedAt,
  });
}

export async function republishContentEventAction(id: string, ctx: any) {
  const target = ctx.contentEvents.find((item: any) => item.id === id);
  if (!target) return;
  ctx.setPublishingItemId(id);
  try {
    const imageFile = target.attachmentDataUrl
      ? dataUrlToFile(target.attachmentDataUrl, target.attachmentName ?? "photo.jpg")
      : null;
    const selectedPublicSocialLinkId = target.vkPublicSocialLinkId ?? ctx.contentPublishTargets[id];
    if (!selectedPublicSocialLinkId) {
      ctx.setContentMessageType(MESSAGE_STATUS.ERROR);
      ctx.setContentMessage("Выберите паблик для публикации.");
      return;
    }
    const vk = await publishContentEventToVkAction(target, imageFile, ctx);
    if (ctx.authToken) {
      try {
        const syncedPost = await syncPublishedVkPostAction(id, target.vkPublicationId, selectedPublicSocialLinkId, vk, ctx);
        ctx.setContentEvents((prev: any[]) =>
          prev.map((item) =>
            item.id === id
              ? {
                  ...apiPostToContentEvent(syncedPost),
                  attachmentName: item.attachmentName,
                  attachmentDataUrl: item.attachmentDataUrl,
                  vkPublishError: undefined,
                }
              : item,
          ),
        );
        await ctx.reloadCalendarFromBackend();
      } catch {
        try { await apiUpdatePostVk(ctx.authToken, id, String(vk.postId)); } catch {}
      }
    }
    ctx.setContentEvents((prev: any[]) =>
      prev.map((item) =>
        item.id === id ? { ...item, vkWallUrl: vk.url, vkPostId: vk.postId, vkPublishError: undefined } : item,
      ),
    );
    ctx.setContentMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setContentMessage("Пост опубликован в VK.");
  } catch (err) {
    const errorText = err instanceof Error ? err.message : "Ошибка VK (проверьте бэкенд: токен, группа, proxy).";
    ctx.setContentEvents((prev: any[]) =>
      prev.map((item) => (item.id === id ? { ...item, vkPublishError: errorText } : item)),
    );
    ctx.setContentMessageType(MESSAGE_STATUS.ERROR);
    ctx.setContentMessage(`Не удалось опубликовать в VK: ${errorText}`);
  } finally {
    ctx.setPublishingItemId(null);
  }
}

export async function deleteVkPostForContentAction(id: string, ctx: any) {
  const target = ctx.contentEvents.find((item: any) => item.id === id);
  if (!target || !target.vkPostId) {
    ctx.setContentMessageType(MESSAGE_STATUS.ERROR);
    ctx.setContentMessage("Не найден post_id для удаления в VK.");
    return;
  }
  ctx.setDeletingVkItemId(id);
  try {
    const res = await vkDeletePost(ctx.authToken, target.vkPostId);
    if (!res.success) {
      throw new Error("VK вернул неуспешный результат удаления.");
    }
    if (ctx.authToken) {
      try { await apiUpdatePostVk(ctx.authToken, id, null); } catch {}
    }
    ctx.setContentEvents((prev: any[]) =>
      prev.map((item) =>
        item.id === id ? { ...item, vkWallUrl: undefined, vkPostId: undefined, vkPublishError: undefined } : item,
      ),
    );
    ctx.setContentMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setContentMessage("Пост удалён из VK.");
  } catch (err) {
    ctx.setContentMessageType(MESSAGE_STATUS.ERROR);
    ctx.setContentMessage(err instanceof Error ? err.message : "Не удалось удалить пост в VK.");
  } finally {
    ctx.setDeletingVkItemId(null);
  }
}

