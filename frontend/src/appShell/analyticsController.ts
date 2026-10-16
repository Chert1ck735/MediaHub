import { apiNeedsRebuild, apiRebuildVkAnalytics, apiReportPdf, waitForJob } from "../api";
import { MESSAGE_STATUS } from "../constants";
import { queryKeys } from "../hooks/queryKeys";
import { downloadBlob } from "../lib/downloadBlob";

export async function loadAnalyticsData(
  ctx: any,
  token: string,
  period: string = ctx.reportPeriod,
  sourceId: string | null = ctx.reportSourceId,
  municipalityName: string | null = ctx.reportMunicipalityName ?? null,
  options: { silent?: boolean } = {},
) {
  void options;
  await Promise.all([
    ctx.queryClient.invalidateQueries({ queryKey: queryKeys.analyticsSummary(token, period, sourceId, municipalityName) }),
    ctx.queryClient.invalidateQueries({ queryKey: queryKeys.painList(token, period, sourceId, municipalityName) }),
    ctx.queryClient.invalidateQueries({ queryKey: queryKeys.painTrends(token, period, sourceId, municipalityName) }),
    // постовая аналитика подтягивается сама — обновим её после импорта/пересборки
    ctx.queryClient.invalidateQueries({ queryKey: ["report-preview", token] }),
  ]);
}

/** Тихо освежает боли при входе на страницу: агрегация из БД, без LLM.
 *
 *  Снапшот строим полный, без period/public_social_link_id — `PainListService`
 *  всё равно пере-считывает срезы по периоду и площадке на чтении, так что
 *  одного полного снапшота хватает на все фильтры.
 *
 *  Ничего не пишет в reportMessage и не поднимает reportLoading: это фон, он не
 *  должен выглядеть как действие пользователя и не должен ломать страницу.
 */
export async function autoRefreshAnalytics(ctx: any) {
  if (!ctx.authToken) return;
  try {
    const check = await apiNeedsRebuild(ctx.authToken);
    if (!check.needs_rebuild) return;

    const { job_id } = await apiRebuildVkAnalytics(
      ctx.authToken,
      false,
      null,
      false,
      false,
      null,
    );
    const finalJob = await waitForJob(ctx.authToken, job_id, (job: unknown) =>
      ctx.setAnalyticsJob(job),
    );
    ctx.setAnalyticsJob(null);
    if (finalJob.status === "failed" || finalJob.status === "cancelled") return;

    await loadAnalyticsData(
      ctx,
      ctx.authToken,
      ctx.reportPeriod,
      ctx.reportSourceId,
      ctx.reportMunicipalityName ?? null,
      { silent: true },
    );
  } catch (err) {
    console.warn("auto rebuild failed", err);
    ctx.setAnalyticsJob(null);
  }
}

export async function generateAnalyticsReport(ctx: any) {
  if (!ctx.authToken) return;
  ctx.setReportLoading(true);
  ctx.setReportMessage("");
  ctx.setReportMessageType(MESSAGE_STATUS.IDLE);
  ctx.setAnalyticsJob(null);
  try {
    let rebuiltMsg = "";
    try {
      const check = await apiNeedsRebuild(ctx.authToken);
      ctx.setReportMessage(
        ctx.deepLlmAnalysis
          ? "Глубокая LLM-аналитика комментариев... это может занять минуты"
          : check.needs_rebuild
            ? (check.reason === "pending_classification"
                ? "Классифицируем новые комментарии..."
                : "Пересобираем аналитику по новым данным...")
            : "Пересобираем аналитику..."
      );
      // incremental=false намеренно: LLM гоняется только по явному желанию —
      // через тумблер глубокого анализа (deepLlmAnalysis → force_reclassify).
      // Иначе пересборка просто агрегирует то, что уже размечено в БД, а
      // доразметку новых комментов делает фоновый classification-воркер.
      const { job_id } = await apiRebuildVkAnalytics(
        ctx.authToken,
        ctx.deepLlmAnalysis,
        ctx.reportPeriod,
        ctx.prefilterEnabled,
        false,
        ctx.reportSourceId,
      );
      try { localStorage.setItem(ctx.ANALYTICS_JOB_KEY, job_id); } catch {}
      const finalJob = await waitForJob(ctx.authToken, job_id, (job: unknown) => ctx.setAnalyticsJob(job));
      try { localStorage.removeItem(ctx.ANALYTICS_JOB_KEY); } catch {}
      ctx.setAnalyticsJob(null);
      if (finalJob.status === "failed") {
        throw new Error(finalJob.error || "Не удалось пересобрать");
      }
      if (finalJob.status === "cancelled") {
        ctx.setReportMessageType(MESSAGE_STATUS.ERROR);
        ctx.setReportMessage(finalJob.error || "Пересборка отменена");
      }
      const result = finalJob.result as any;
      if (result) {
        const speed =
          result.elapsed_seconds > 0
            ? `За ${Math.round(result.elapsed_seconds)}с · ~${result.comments_per_min} комм/мин · `
            : "";
        const pf = result.prefilter_used
          ? `префильтр: вкл, отсеял ${result.prefilter_dropped} · `
          : "префильтр: выкл · ";
        rebuiltMsg =
          `Аналитика пересобрана. ${speed}${pf}` +
          `Болей: ${result.pain_count}. ` +
          `LLM: ${result.llm_classified_comments}, fallback: ${result.fallback_classified_comments}. `;
      }
    } catch (err) {
      console.warn("rebuild check/run failed", err);
      ctx.setAnalyticsJob(null);
    }

    await Promise.all([
      loadAnalyticsData(
        ctx,
        ctx.authToken,
        ctx.reportPeriod,
        ctx.reportSourceId,
        ctx.reportMunicipalityName ?? null,
        { silent: true },
      ).catch(() => {}),
      ctx.reportPreviewQuery.refetch()
        .then(() => {
          ctx.setSelectedChartRange(null);
        })
        .catch(() => {}),
    ]);
    ctx.setReportMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setReportMessage(`${rebuiltMsg}Отчет обновлен.`);
  } catch (err) {
    ctx.setReportMessageType(MESSAGE_STATUS.ERROR);
    ctx.setReportMessage(err instanceof Error ? err.message : "Ошибка формирования");
  } finally {
    ctx.setReportLoading(false);
  }
}

export async function refreshAnalyticsFromDb(ctx: any) {
  if (!ctx.authToken) return;
  ctx.setReportLoading(true);
  ctx.setReportMessage("");
  ctx.setReportMessageType(MESSAGE_STATUS.IDLE);
  try {
    await Promise.all([
      loadAnalyticsData(
        ctx,
        ctx.authToken,
        ctx.reportPeriod,
        ctx.reportSourceId,
        ctx.reportMunicipalityName ?? null,
        { silent: true },
      ).catch(() => {}),
      ctx.reportPreviewQuery.refetch()
        .then(() => {
          ctx.setSelectedChartRange(null);
        })
        .catch(() => {}),
    ]);
    ctx.setReportMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setReportMessage("Данные обновлены из базы.");
  } catch (err) {
    ctx.setReportMessageType(MESSAGE_STATUS.ERROR);
    ctx.setReportMessage(err instanceof Error ? err.message : "Не удалось обновить данные из базы.");
  } finally {
    ctx.setReportLoading(false);
  }
}

export async function downloadReportPdfAction(ctx: any) {
  if (!ctx.authToken) return;
  ctx.setReportPdfLoading(true);
  ctx.setReportMessage("");
  ctx.setReportMessageType(MESSAGE_STATUS.IDLE);
  try {
    const blob = await apiReportPdf(ctx.authToken, {
      platform: ctx.reportPlatform,
      public_social_link_id: ctx.reportSourceId,
      municipality_name: ctx.reportMunicipalityName ?? null,
      period: ctx.reportPeriod,
    });
    const stamp = new Date().toISOString().slice(0, 10);
    downloadBlob(blob, `report-${ctx.reportPlatform}-${stamp}.pdf`);
    ctx.setReportMessageType(MESSAGE_STATUS.SUCCESS);
    ctx.setReportMessage("PDF скачан.");
  } catch (err) {
    ctx.setReportMessageType(MESSAGE_STATUS.ERROR);
    ctx.setReportMessage(err instanceof Error ? err.message : "Не удалось скачать PDF");
  } finally {
    ctx.setReportPdfLoading(false);
  }
}
