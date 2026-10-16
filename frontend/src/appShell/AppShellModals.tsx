import type { ChangeEvent, FormEvent } from "react";

import { apiUpdatePostVk } from "../api";
import { AuthModal, CalendarModal, InfoEventModal } from "../components/AppModals";
import { SmartEventModal } from "../components/SmartEventModal";
import { InvitationAccept } from "../components/InvitationAccept";
import { SESSION_KEY } from "../app/constants";
import { defaultInfoEventForm, VK_MESSAGE_MAX } from "../app/constants";
import { queryKeys } from "../hooks/queryKeys";
import { DEFAULT_EVENT_SLOT_MS } from "../constants";
import {
  openAuthModal,
  submitAuth,
} from "./authController";
import { submitCalendarEvent } from "./calendarController";
import {
  publishContentEventToVkAction,
  syncPublishedVkPostAction,
} from "./contentController";
import { submitInfoEvent } from "./eventsController";
import {
  clearSmartImageAction,
  closeSmartEventAction,
  handleSmartGenerateAction,
  handleSmartImagePickAction,
  handleSmartPainSelectAction,
  handleSmartSourceEventChangeAction,
  handleSmartSubmitAction,
} from "./smartEventController";
import { useAppShellContext } from "./AppShellContext";

export function AppShellModals() {
  const { location, navigate, shellState, shellData } = useAppShellContext();
  const {
    authModalOpen,
    setAuthModalOpen,
    calendarModalOpen,
    setCalendarModalOpen,
    infoEventModalOpen,
    setInfoEventModalOpen,
    infoEventCreating,
    setInfoEventCreating,
    editingInfoEventId,
    setEditingInfoEventId,
    infoEventMessage,
    setInfoEventMessage,
    infoEventMessageType,
    setInfoEventMessageType,
    infoEventForm,
    setInfoEventForm,
    setContentMessage,
    setContentMessageType,
    editingEventId,
    setAuthMode,
    email,
    setEmail,
    password,
    setPassword,
    showPassword,
    setShowPassword,
    rememberMe,
    setRememberMe,
    authMessage,
    setAuthMessage,
    authMessageType,
    setAuthMessageType,
    authLoading,
    setAuthLoading,
    authToken,
    setAuthToken,
    setCurrentUser,
    eventTitle,
    setEventTitle,
    eventDate,
    setEventDate,
    eventTime,
    setEventTime,
    eventDescription,
    setEventDescription,
    eventStatus,
    setEventStatus,
    eventPlatforms,
    setEventPlatforms,
    eventDraft,
    setEventDraft,
    eventTone,
    setEventTone,
    eventPostType,
    setEventPostType,
    eventInfoEventId,
    setEventInfoEventId,
    eventSeriesCount,
    setEventSeriesCount,
    eventSeriesStepMinutes,
    setEventSeriesStepMinutes,
    eventSeriesItems,
    setEventSeriesItems,
    calendarGenerating,
    setCalendarGenerating,
    calendarGenerationProgress,
    setCalendarGenerationProgress,
    calendarMessage,
    setCalendarMessage,
    calendarMessageType,
    setCalendarMessageType,
    smartEventOpen,
    smartEntryMode,
    setSmartEntryMode,
    smartTitle,
    setSmartTitle,
    smartPrompt,
    setSmartPrompt,
    smartTone,
    setSmartTone,
    smartPostType,
    setSmartPostType,
    smartSourceEventId,
    setSmartSourceEventId,
    smartEventDate,
    setSmartEventDate,
    smartPlatforms,
    setSmartPlatforms,
    smartScheduleEnabled,
    setSmartScheduleEnabled,
    smartScheduleDate,
    setSmartScheduleDate,
    smartScheduleTime,
    setSmartScheduleTime,
    smartGenerated,
    setSmartGenerated,
    smartLlmLoading,
    setSmartLlmLoading,
    smartMessage,
    setSmartMessage,
    smartMessageType,
    setSmartMessageType,
    smartPainId,
    setSmartPainId,
    smartStrategyId,
    setSmartStrategyId,
    smartPainDetail,
    setSmartPainDetail,
    smartImageFile,
    setSmartImageFile,
    smartImagePreview,
    setSmartImagePreview,
    smartFileInputRef,
    publishToVk,
    setPublishToVk,
    vkPublishing,
    setVkPublishing,
    setSelectedDay,
    setCalendarDate,
    setEvents,
    setInfoEvents,
    setContentEvents,
  } = shellState;
  const {
    queryClient,
    authTitle,
    publicationTargetOptions,
    painItems,
    selectedSmartSourceEvent,
  } = shellData;

  const openAuth = (mode: "login", options?: { reset?: boolean }) =>
    openAuthModal(mode, options, {
      setAuthMode,
      setEmail,
      setPassword,
      setAuthMessage,
      setAuthMessageType,
      setAuthModalOpen,
    });

  const invitationToken = new URLSearchParams(location.search).get("invite");

  const reloadCalendarFromBackend = async () => {
    if (!authToken) return;
    shellState.calendarReloadSeqRef.current += 1;
    await queryClient.invalidateQueries({ queryKey: queryKeys.calendarEventsAll(authToken) });
  };

  const reloadContentFromBackend = async () => {
    if (!authToken) return;
    shellState.contentReloadSeqRef.current += 1;
    await queryClient.invalidateQueries({ queryKey: queryKeys.posts(authToken) });
  };

  const handleAuthSubmit = async (event: FormEvent) =>
    submitAuth(event, {
      email,
      password,
      rememberMe,
      setAuthMode,
      setEmail,
      setPassword,
      setAuthMessage,
      setAuthMessageType,
      setAuthLoading,
      setAuthToken,
      setCurrentUser,
      setAuthModalOpen,
      location,
      navigate,
    });

  const handleInfoEventCreate = async (event: FormEvent) =>
    submitInfoEvent(event, {
      authToken,
      infoEventForm,
      editingInfoEventId,
      queryClient,
      queryKeys,
      defaultInfoEventForm,
      openAuth,
      setInfoEventCreating,
      setInfoEventMessage,
      setInfoEventMessageType,
      setInfoEvents,
      setSelectedInfoEventId: shellState.setSelectedInfoEventId,
      setInfoEventForm,
      setEditingInfoEventId,
      setInfoEventModalOpen,
    });

  const handleCalendarSubmit = async (event: FormEvent) =>
    submitCalendarEvent(event, {
      authToken,
      eventTitle,
      eventDate,
      eventTime,
      eventDescription,
      eventPlatforms,
      eventStatus,
      eventSeriesCount,
      eventSeriesStepMinutes,
      eventPostType,
      eventSeriesItems,
      editingEventId,
      eventDraft,
      eventTone,
      eventInfoEventId,
      openAuth,
      reloadCalendarFromBackend,
      reloadContentFromBackend,
      setCalendarMessageType,
      setCalendarMessage,
      setCalendarGenerating,
      setCalendarGenerationProgress,
      setSelectedDay,
      setCalendarDate,
      setCalendarModalOpen,
      setEditingEventId: shellState.setEditingEventId,
    });

  const closeSmartEvent = () =>
    closeSmartEventAction({
      setSmartEventOpen: shellState.setSmartEventOpen,
      setSmartEntryMode,
      setSmartLlmLoading,
      setVkPublishing,
    });

  const handleSmartSourceEventChange = (eventId: string) =>
    handleSmartSourceEventChangeAction(eventId, {
      infoEvents: shellState.infoEvents,
      setSmartSourceEventId,
      setSmartTitle,
      setSmartPrompt,
      setSmartEventDate,
      setSmartScheduleDate,
    });

  const handleSmartPainSelect = async (painId: string) =>
    handleSmartPainSelectAction(painId, {
      setSmartPainId,
      setSmartStrategyId,
      setSmartPainDetail,
    });

  const handleSmartGenerate = async () =>
    handleSmartGenerateAction({
      authToken,
      painItems,
      infoEvents: shellState.infoEvents,
      smartPrompt,
      smartEventDate,
      smartTitle,
      smartPainId,
      smartSourceEventId,
      smartPostType,
      smartTone,
      smartPainDetail,
      smartPlatforms,
      setSmartLlmLoading,
      setSmartMessage,
      setSmartMessageType,
      setSmartGenerated,
    });

  const handleSmartImagePick = async (event: ChangeEvent<HTMLInputElement>) =>
    handleSmartImagePickAction(event, {
      setSmartMessageType,
      setSmartMessage,
      setSmartImageFile,
      setSmartImagePreview,
    });

  const clearSmartImage = () =>
    clearSmartImageAction({
      smartFileInputRef,
      setSmartImageFile,
      setSmartImagePreview,
    });

  const publishContentEventToVk = async (item: any, imageFile?: File | null) =>
    publishContentEventToVkAction(item, imageFile, {
      authToken,
      VK_MESSAGE_MAX,
    });

  const syncPublishedVkPost = async (
    postId: string,
    publicationId: string | undefined,
    publicSocialLinkId: string | undefined,
    vk: { url: string; postId: number },
  ) =>
    syncPublishedVkPostAction(postId, publicationId, publicSocialLinkId, vk, {
      authToken,
    });

  const handleSmartSubmit = async (event: FormEvent) =>
    handleSmartSubmitAction(event, {
      authToken,
      smartEntryMode,
      smartScheduleEnabled,
      smartTitle,
      smartPrompt,
      smartScheduleDate,
      smartScheduleTime,
      smartPlatforms,
      publishToVk,
      smartGenerated,
      smartTone,
      smartStrategyId,
      smartImageFile,
      smartImagePreview,
      smartPostType,
      smartSourceEventId,
      smartEventDate,
      painItems,
      infoEvents: shellState.infoEvents,
      smartPainId,
      smartPainDetail,
      openAuth,
      closeSmartEvent,
      publishContentEventToVk,
      syncPublishedVkPost,
      reloadContentFromBackend,
      reloadCalendarFromBackend,
      apiUpdatePostVk,
      setSmartMessageType,
      setSmartMessage,
      setContentEvents,
      setContentMessageType,
      setContentMessage,
      setSelectedDay,
      setCalendarDate,
      setEvents,
      setVkPublishing,
      DEFAULT_EVENT_SLOT_MS,
    });

  return (
    <>
      {invitationToken ? (
        <InvitationAccept
          token={invitationToken}
          onAccepted={(result) => {
            localStorage.setItem(SESSION_KEY, result.email);
            sessionStorage.removeItem(SESSION_KEY);
            setAuthToken(result.access_token);
            setCurrentUser(result.email);
            navigate("/", { replace: true });
          }}
          onCancel={() => navigate("/?auth=login", { replace: true })}
        />
      ) : null}
      <AuthModal
        open={authModalOpen && !invitationToken}
        authTitle={authTitle}
        authLoading={authLoading}
        authMessage={authMessage}
        authMessageType={authMessageType}
        email={email}
        password={password}
        showPassword={showPassword}
        rememberMe={rememberMe}
        onSubmit={handleAuthSubmit}
        onSetEmail={setEmail}
        onSetPassword={setPassword}
        onSetShowPassword={setShowPassword}
        onSetRememberMe={setRememberMe}
      />
      <InfoEventModal
        open={infoEventModalOpen}
        authToken={authToken}
        infoEventCreating={infoEventCreating}
        editingInfoEventId={editingInfoEventId}
        infoEventForm={infoEventForm}
        infoEventMessage={infoEventMessage}
        infoEventMessageType={infoEventMessageType}
        onClose={() => setInfoEventModalOpen(false)}
        onSubmit={handleInfoEventCreate}
        onSetInfoEventForm={setInfoEventForm}
      />
      <CalendarModal
        open={calendarModalOpen}
        eventTitle={eventTitle}
        eventDescription={eventDescription}
        eventDraft={eventDraft}
        eventTone={eventTone}
        eventPostType={eventPostType}
        eventDate={eventDate}
        eventTime={eventTime}
        eventStatus={eventStatus}
        eventSeriesCount={eventSeriesCount}
        eventSeriesStepMinutes={eventSeriesStepMinutes}
        eventSeriesItems={eventSeriesItems}
        eventPlatforms={eventPlatforms}
        publicationTargetOptions={publicationTargetOptions}
        editingEventId={editingEventId}
        calendarGenerating={calendarGenerating}
        calendarGenerationProgress={calendarGenerationProgress}
        calendarMessage={calendarMessage}
        calendarMessageType={calendarMessageType}
        infoEvents={shellState.infoEvents}
        eventInfoEventId={eventInfoEventId}
        onSetEventInfoEventId={setEventInfoEventId}
        onClose={() => setCalendarModalOpen(false)}
        onSubmit={handleCalendarSubmit}
        onSetEventTitle={setEventTitle}
        onSetEventDescription={setEventDescription}
        onSetEventDraft={setEventDraft}
        onSetEventTone={setEventTone}
        onSetEventPostType={setEventPostType}
        onSetEventDate={setEventDate}
        onSetEventTime={setEventTime}
        onSetEventStatus={setEventStatus}
        onSetEventSeriesCount={setEventSeriesCount}
        onSetEventSeriesStepMinutes={setEventSeriesStepMinutes}
        onSetEventSeriesItems={setEventSeriesItems}
        onSetEventPlatforms={setEventPlatforms}
      />
      <SmartEventModal
        open={smartEventOpen}
        smartEntryMode={smartEntryMode}
        infoEvents={shellState.infoEvents}
        smartSourceEventId={smartSourceEventId}
        selectedSmartSourceEvent={selectedSmartSourceEvent}
        smartTitle={smartTitle}
        smartPrompt={smartPrompt}
        smartEventDate={smartEventDate}
        smartTone={smartTone}
        smartPostType={smartPostType}
        smartScheduleEnabled={smartScheduleEnabled}
        smartPlatforms={smartPlatforms}
        publicationTargetOptions={publicationTargetOptions}
        publishToVk={publishToVk}
        smartScheduleDate={smartScheduleDate}
        smartScheduleTime={smartScheduleTime}
        painItems={painItems}
        smartPainId={smartPainId}
        smartLlmLoading={smartLlmLoading}
        smartGenerated={smartGenerated}
        smartImagePreview={smartImagePreview}
        smartFileInputRef={smartFileInputRef}
        vkPublishing={vkPublishing}
        smartMessage={smartMessage}
        smartMessageType={smartMessageType}
        onClose={closeSmartEvent}
        onSubmit={handleSmartSubmit}
        onHandleSmartSourceEventChange={handleSmartSourceEventChange}
        onSetSmartTitle={setSmartTitle}
        onSetSmartPrompt={setSmartPrompt}
        onSetSmartEventDate={setSmartEventDate}
        onSetSmartTone={setSmartTone}
        onSetSmartPostType={setSmartPostType}
        onSetSmartScheduleEnabled={setSmartScheduleEnabled}
        onSetSmartPlatforms={setSmartPlatforms}
        onSetSmartScheduleDate={setSmartScheduleDate}
        onSetSmartScheduleTime={setSmartScheduleTime}
        onHandleSmartPainSelect={handleSmartPainSelect}
        onHandleSmartGenerate={handleSmartGenerate}
        onSetSmartGenerated={setSmartGenerated}
        onHandleSmartImagePick={handleSmartImagePick}
        onClearSmartImage={clearSmartImage}
        onSetPublishToVk={setPublishToVk}
      />
    </>
  );
}
