import { useEffect, useRef } from "react";

import { apiLinkEventPains, apiUnlinkEventPain } from "../../api";
import { queryKeys } from "../../hooks/queryKeys";
import { AnalyticsPage } from "../../pages/AnalyticsPage";
import { renderDetailedMetricChart } from "../analyticsChartRenderer";
import {
  autoRefreshAnalytics,
  downloadReportPdfAction,
  refreshAnalyticsFromDb,
} from "../analyticsController";
import { useAppShellContext } from "../AppShellContext";

export function AnalyticsRoute() {
  const { shellState, shellData } = useAppShellContext();

  // Боли освежаются сами при входе на страницу — без кнопки и без LLM.
  // Ref-guard: строго один прогон на монтирование, иначе ре-рендеры
  // (job/период/выбор боли) плодили бы пересборки.
  const autoRefreshedRef = useRef(false);
  useEffect(() => {
    if (!shellState.authToken || autoRefreshedRef.current) return;
    if (shellState.reportLoading) return; // ручная пересборка уже идёт
    autoRefreshedRef.current = true;
    void autoRefreshAnalytics({
      authToken: shellState.authToken,
      reportPeriod: shellState.reportPeriod,
      reportSourceId: shellState.reportSourceId,
      reportMunicipalityName: shellState.reportMunicipalityName,
      queryClient: shellData.queryClient,
      setAnalyticsJob: shellState.setAnalyticsJob,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shellState.authToken]);

  const handleGenerate = async () =>
    refreshAnalyticsFromDb({
      authToken: shellState.authToken,
      reportPeriod: shellState.reportPeriod,
      reportSourceId: shellState.reportSourceId,
      reportMunicipalityName: shellState.reportMunicipalityName,
      reportPreviewQuery: shellData.reportPreviewQuery,
      queryClient: shellData.queryClient,
      setReportLoading: shellState.setReportLoading,
      setReportMessage: shellState.setReportMessage,
      setReportMessageType: shellState.setReportMessageType,
      setSelectedChartRange: shellState.setSelectedChartRange,
    });

  const downloadReportPdf = async () =>
    downloadReportPdfAction({
      authToken: shellState.authToken,
      reportPlatform: shellState.reportPlatform,
      reportSourceId: shellState.reportSourceId,
      reportMunicipalityName: shellState.reportMunicipalityName,
      reportPeriod: shellState.reportPeriod,
      setReportPdfLoading: shellState.setReportPdfLoading,
      setReportMessage: shellState.setReportMessage,
      setReportMessageType: shellState.setReportMessageType,
    });

  const loadMorePainComments = async () => {
    if (
      !shellData.painCommentsQuery.hasNextPage ||
      shellData.painCommentsQuery.isFetchingNextPage
    ) {
      return;
    }
    await shellData.painCommentsQuery.fetchNextPage();
  };

  const handleLinkEventToPain = async (eventId: string) => {
    if (!shellState.authToken || !shellState.selectedPainId) return;
    try {
      await apiLinkEventPains(shellState.authToken, eventId, [shellState.selectedPainId]);
      await shellData.queryClient.invalidateQueries({
        queryKey: queryKeys.painEvents(
          shellState.authToken,
          shellState.selectedPainId,
        ),
      });
      shellState.setPainEventPickerOpen(false);
      shellState.setPainEventPickerQuery("");
    } catch {}
  };

  const handleUnlinkEventFromPain = async (eventId: string) => {
    if (!shellState.authToken || !shellState.selectedPainId) return;
    try {
      await apiUnlinkEventPain(
        shellState.authToken,
        eventId,
        shellState.selectedPainId,
      );
      await shellData.queryClient.invalidateQueries({
        queryKey: queryKeys.painEvents(
          shellState.authToken,
          shellState.selectedPainId,
        ),
      });
    } catch {}
  };

  return (
    <AnalyticsPage
      authToken={shellState.authToken}
      dataLoading={shellData.analyticsPageLoading}
      analyticsLoading={shellData.analyticsLoading}
      analyticsView={shellState.analyticsView}
      setAnalyticsView={shellState.setAnalyticsView}
      reportPlatform={shellState.reportPlatform}
      setReportPlatform={shellState.setReportPlatform}
      reportSourceId={shellState.reportSourceId}
      setReportSourceId={shellState.setReportSourceId}
      reportMunicipalityName={shellState.reportMunicipalityName}
      setReportMunicipalityName={shellState.setReportMunicipalityName}
      reportSourcesLoading={shellData.reportSourcesLoading}
      reportSourceOptions={shellData.reportSourceOptions}
      reportPlatformOptions={shellData.reportPlatformOptions}
      reportPeriod={shellState.reportPeriod}
      setReportPeriod={shellState.setReportPeriod}
      deepLlmAnalysis={shellState.deepLlmAnalysis}
      setDeepLlmAnalysis={shellState.setDeepLlmAnalysis}
      prefilterEnabled={shellState.prefilterEnabled}
      setPrefilterEnabled={shellState.setPrefilterEnabled}
      reportLoading={shellState.reportLoading}
      handleGenerate={handleGenerate}
      downloadReportPdf={downloadReportPdf}
      reportPdfLoading={shellState.reportPdfLoading}
      analyticsJob={shellState.analyticsJob}
      analyticsSummary={shellData.analyticsSummary}
      painItems={shellData.painItems}
      analyticsSentimentBars={shellData.analyticsSentimentBars}
      analyticsRelevanceBars={shellData.analyticsRelevanceBars}
      analyticsMessageTypeBars={shellData.analyticsMessageTypeBars}
      analyticsCategoryBars={shellData.analyticsCategoryBars}
      painSeverityFilter={shellState.painSeverityFilter}
      setPainSeverityFilter={shellState.setPainSeverityFilter}
      selectedPainId={shellState.selectedPainId}
      setSelectedPainId={shellState.setSelectedPainId}
      painTrends={shellData.painTrends}
      selectedPainDetail={shellData.selectedPainDetail}
      painEvents={shellData.painEvents}
      painEventPickerOpen={shellState.painEventPickerOpen}
      setPainEventPickerOpen={shellState.setPainEventPickerOpen}
      painEventPickerQuery={shellState.painEventPickerQuery}
      setPainEventPickerQuery={shellState.setPainEventPickerQuery}
      infoEvents={shellState.infoEvents}
      handleLinkEventToPain={handleLinkEventToPain}
      handleUnlinkEventFromPain={handleUnlinkEventFromPain}
      selectedSubproblem={shellData.selectedSubproblem}
      setSelectedSubproblemTitle={shellState.setSelectedSubproblemTitle}
      paginatedComments={shellData.paginatedComments}
      paginatedLoading={shellData.paginatedLoading}
      paginatedTotal={shellData.paginatedTotal}
      loadMorePainComments={loadMorePainComments}
      expandedCases={shellState.expandedCases}
      setExpandedCases={shellState.setExpandedCases}
      strategyRegenLoading={shellState.strategyRegenLoading}
      strategyRegenError={shellState.strategyRegenError}
      setStrategyRegenError={shellState.setStrategyRegenError}
      setStrategyRegenLoading={shellState.setStrategyRegenLoading}
      reportPreview={shellData.reportPreview}
      reportOverviewCards={shellData.reportOverviewCards}
      renderDetailedMetricChart={(points: any, metricKey: any, stroke: any, metricLabel: any, onBucketClick: any) =>
        renderDetailedMetricChart(
          points,
          metricKey,
          stroke,
          metricLabel,
          shellState.selectedChartRange,
          onBucketClick,
        )
      }
      selectedChartRange={shellState.selectedChartRange}
      setSelectedChartRange={shellState.setSelectedChartRange}
      reportDateRange={shellData.reportDateRange}
      reportTrend={shellData.reportTrend}
      reportAverageEngagement={shellData.reportAverageEngagement}
      reportTopPosts={shellData.reportTopPosts}
      chartRangePosts={shellData.chartRangePosts}
      reportAllPostsSorted={shellData.reportAllPostsSorted}
      reportPreviewFetching={shellData.reportPreviewFetching}
      refetchReportPreview={shellData.refetchReportPreview}
      chartPostsLimit={shellState.chartPostsLimit}
      setChartPostsLimit={shellState.setChartPostsLimit}
      chartPostsSort={shellState.chartPostsSort}
      setChartPostsSort={shellState.setChartPostsSort}
      reportMessageType={shellState.reportMessageType}
      reportMessage={shellState.reportMessage}
    />
  );
}
