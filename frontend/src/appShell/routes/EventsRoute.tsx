import { defaultInfoEventForm } from "../../app/constants";
import { EventsPage } from "../../pages/EventsPage";
import {
  deleteInfoEventAction,
  importInfoEventsAction,
  linkPainToEventAction,
  openCreateInfoEventModalAction,
  openEditInfoEventModalAction,
  unlinkPainFromEventAction,
} from "../eventsController";
import { openSmartEventAction } from "../smartEventController";
import { queryKeys } from "../../hooks/queryKeys";
import { useAppShellContext } from "../AppShellContext";

export function EventsRoute() {
  const { shellState, shellData, openAuth } = useAppShellContext();

  const handleInfoEventDelete = async (eventId: string) =>
    deleteInfoEventAction(eventId, {
      authToken: shellState.authToken,
      infoEvents: shellState.infoEvents,
      queryClient: shellData.queryClient,
      queryKeys,
      openAuth,
      setInfoEvents: shellState.setInfoEvents,
      setSelectedInfoEventId: shellState.setSelectedInfoEventId,
      setInfoEventMessageType: shellState.setInfoEventMessageType,
      setInfoEventMessage: shellState.setInfoEventMessage,
    });

  const handleInfoEventImport = async (event: React.ChangeEvent<HTMLInputElement>) =>
    importInfoEventsAction(event, {
      authToken: shellState.authToken,
      queryClient: shellData.queryClient,
      queryKeys,
      setInfoEventsImporting: shellState.setInfoEventsImporting,
      setInfoEventMessage: shellState.setInfoEventMessage,
      setInfoEventMessageType: shellState.setInfoEventMessageType,
      setInfoEvents: shellState.setInfoEvents,
      setSelectedInfoEventId: shellState.setSelectedInfoEventId,
    });

  const handleLinkPainToEvent = async (painId: string) =>
    linkPainToEventAction(painId, {
      authToken: shellState.authToken,
      selectedInfoEventId: shellState.selectedInfoEventId,
      queryClient: shellData.queryClient,
      queryKeys,
      setEventPainPickerOpen: shellState.setEventPainPickerOpen,
    });

  const handleUnlinkPainFromEvent = async (painId: string) =>
    unlinkPainFromEventAction(painId, {
      authToken: shellState.authToken,
      selectedInfoEventId: shellState.selectedInfoEventId,
      queryClient: shellData.queryClient,
      queryKeys,
    });

  const openCreateInfoEventModal = () =>
    openCreateInfoEventModalAction({
      authToken: shellState.authToken,
      defaultInfoEventForm,
      openAuth,
      setInfoEventMessage: shellState.setInfoEventMessage,
      setInfoEventMessageType: shellState.setInfoEventMessageType,
      setInfoEventForm: shellState.setInfoEventForm,
      setEditingInfoEventId: shellState.setEditingInfoEventId,
      setInfoEventModalOpen: shellState.setInfoEventModalOpen,
    });

  const openEditInfoEventModal = (eventItem: any) =>
    openEditInfoEventModalAction(eventItem, {
      authToken: shellState.authToken,
      openAuth,
      setInfoEventMessage: shellState.setInfoEventMessage,
      setInfoEventMessageType: shellState.setInfoEventMessageType,
      setInfoEventForm: shellState.setInfoEventForm,
      setEditingInfoEventId: shellState.setEditingInfoEventId,
      setInfoEventModalOpen: shellState.setInfoEventModalOpen,
    });

  const openSmartEvent = (eventItem: any, options?: { entryMode?: "content" | "calendar" }) =>
    openSmartEventAction(eventItem, options, {
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
    <EventsPage
      authToken={shellState.authToken}
      eventPainPickerOpen={shellState.eventPainPickerOpen}
      eventPains={shellData.eventPains}
      filteredInfoEvents={shellData.filteredInfoEvents}
      handleInfoEventDelete={handleInfoEventDelete}
      handleInfoEventImport={handleInfoEventImport}
      handleLinkPainToEvent={handleLinkPainToEvent}
      handleUnlinkPainFromEvent={handleUnlinkPainFromEvent}
      infoEventMessage={shellState.infoEventMessage}
      infoEventMessageType={shellState.infoEventMessageType}
      infoEventQuery={shellState.infoEventQuery}
      infoEventSort={shellState.infoEventSort}
      infoEvents={shellState.infoEvents}
      infoEventsImporting={shellState.infoEventsImporting}
      infoEventsLoading={shellData.infoEventsLoading}
      infoEventStats={shellData.infoEventStats}
      infoImportInputRef={shellState.infoImportInputRef}
      openAuth={openAuth}
      openCreateInfoEventModal={openCreateInfoEventModal}
      openEditInfoEventModal={openEditInfoEventModal}
      openSmartEvent={openSmartEvent}
      painItems={shellData.painItems}
      selectedInfoEvent={shellData.selectedInfoEvent}
      setEventPainPickerOpen={shellState.setEventPainPickerOpen}
      setInfoEventQuery={shellState.setInfoEventQuery}
      setInfoEventSort={shellState.setInfoEventSort}
      setSelectedInfoEventId={shellState.setSelectedInfoEventId}
    />
  );
}
