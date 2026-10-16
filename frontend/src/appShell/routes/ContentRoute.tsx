import { ContentPage } from "../../pages/ContentPage";
import {
  deleteVkPostForContentAction,
  republishContentEventAction,
  removeContentEventAction,
} from "../contentController";
import { openSmartEventAction } from "../smartEventController";
import { queryKeys } from "../../hooks/queryKeys";
import { useAppShellContext } from "../AppShellContext";

export function ContentRoute() {
  const { shellState, shellData, openAuth } = useAppShellContext();

  const reloadCalendarFromBackend = async () => {
    if (!shellState.authToken) return;
    shellState.calendarReloadSeqRef.current += 1;
    await shellData.queryClient.invalidateQueries({ queryKey: queryKeys.calendarEventsAll(shellState.authToken) });
  };

  const removeContentEvent = async (id: string) =>
    removeContentEventAction(id, {
      authToken: shellState.authToken,
      contentEvents: shellState.contentEvents,
      events: shellState.events,
      deletedPostIdsRef: shellState.deletedPostIdsRef,
      calendarReloadSeqRef: shellState.calendarReloadSeqRef,
      contentReloadSeqRef: shellState.contentReloadSeqRef,
      setContentEvents: shellState.setContentEvents,
      setEvents: shellState.setEvents,
      setContentMessageType: shellState.setContentMessageType,
      setContentMessage: shellState.setContentMessage,
    });

  const republishContentEvent = async (id: string) =>
    republishContentEventAction(id, {
      authToken: shellState.authToken,
      contentEvents: shellState.contentEvents,
      contentPublishTargets: shellState.contentPublishTargets,
      reloadCalendarFromBackend,
      setPublishingItemId: shellState.setPublishingItemId,
      setContentEvents: shellState.setContentEvents,
      setContentMessageType: shellState.setContentMessageType,
      setContentMessage: shellState.setContentMessage,
    });

  const deleteVkPostForContent = async (id: string) =>
    deleteVkPostForContentAction(id, {
      authToken: shellState.authToken,
      contentEvents: shellState.contentEvents,
      setDeletingVkItemId: shellState.setDeletingVkItemId,
      setContentEvents: shellState.setContentEvents,
      setContentMessageType: shellState.setContentMessageType,
      setContentMessage: shellState.setContentMessage,
    });

  // Единственный вход в создание поста: «Календарь» и «Инфоповоды» из меню убраны.
  const openCreatePost = () =>
    openSmartEventAction(null, { entryMode: "content" }, {
      selectedDay: shellState.selectedDay,
      defaultVkPublicLinkId: shellData.defaultVkPublicLinkId,
      smartFileInputRef: shellState.smartFileInputRef,
      setSmartEntryMode: shellState.setSmartEntryMode,
      setSmartSourceEventId: shellState.setSmartSourceEventId,
      setSmartTitle: shellState.setSmartTitle,
      setSmartPrompt: shellState.setSmartPrompt,
      setSmartEventDate: shellState.setSmartEventDate,
      setSmartTone: shellState.setSmartTone,
      setSmartPostType: shellState.setSmartPostType,
      setSmartPlatforms: shellState.setSmartPlatforms,
      setSmartScheduleEnabled: shellState.setSmartScheduleEnabled,
      setSmartScheduleDate: shellState.setSmartScheduleDate,
      setSmartScheduleTime: shellState.setSmartScheduleTime,
      setSmartGenerated: shellState.setSmartGenerated,
      setSmartPainId: shellState.setSmartPainId,
      setSmartStrategyId: shellState.setSmartStrategyId,
      setSmartPainDetail: shellState.setSmartPainDetail,
      setSmartMessage: shellState.setSmartMessage,
      setSmartMessageType: shellState.setSmartMessageType,
      setSmartImageFile: shellState.setSmartImageFile,
      setSmartImagePreview: shellState.setSmartImagePreview,
      setPublishToVk: shellState.setPublishToVk,
      setVkPublishing: shellState.setVkPublishing,
      setSmartEventOpen: shellState.setSmartEventOpen,
    });

  return (
    <ContentPage
      authToken={shellState.authToken}
      onCreatePost={openCreatePost}
      contentEvents={shellState.contentEvents}
      contentMessage={shellState.contentMessage}
      contentMessageType={shellState.contentMessageType}
      contentPublishTargets={shellState.contentPublishTargets}
      painItems={shellData.painItems}
      publicationTargetOptions={shellData.publicationTargetOptions}
      publishingItemId={shellState.publishingItemId}
      deletingVkItemId={shellState.deletingVkItemId}
      dataLoading={shellData.contentLoading}
      openAuth={openAuth}
      removeContentEvent={removeContentEvent}
      republishContentEvent={republishContentEvent}
      deleteVkPostForContent={deleteVkPostForContent}
      setContentPublishTargets={shellState.setContentPublishTargets}
    />
  );
}
