import type { ReactNode } from "react";
import type { ReportPreviewResponse } from "../api";
import type { ChartBucket } from "./chartUtils";
import { bucketTimeSeries } from "./chartUtils";
import { formatChartDate, formatMetricValue } from "../app/utils";

export function renderDetailedMetricChart(
  points: ReportPreviewResponse["points"],
  metricKey: "views" | "likes" | "comments",
  stroke: string,
  metricLabel: string,
  selectedChartRange: { from: string; to: string } | null,
  onBucketClick?: (bucket: ChartBucket) => void,
): ReactNode {
  const width = 420;
  const height = 220;
  const padTop = 20;
  const padRight = 14;
  const padBottom = 34;
  const padLeft = 42;
  const buckets = bucketTimeSeries(points);
  const values = buckets.map((bucket) => bucket[metricKey]);

  if (!values.length) {
    return (
      <div className="analytics-chart-empty">
        <strong>{metricLabel}</strong>
        <span>Нет данных для построения графика.</span>
      </div>
    );
  }

  const min = Math.min(0, ...values);
  const max = Math.max(1, ...values);
  const span = max - min || 1;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const xs = values.length === 1
    ? [padLeft + plotWidth / 2]
    : values.map((_, index) => padLeft + (index * plotWidth) / (values.length - 1));
  const ys = values.map((value) => padTop + ((max - value) * plotHeight) / span);
  const d = xs.map((x, index) => `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${ys[index].toFixed(2)}`).join(" ");
  const yTicks = [max, min + span / 2, min];
  const labelCount = Math.min(5, buckets.length);
  const xIndexes = Array.from({ length: labelCount }, (_, index) =>
    labelCount <= 1 ? 0 : Math.round((index * (buckets.length - 1)) / (labelCount - 1)));

  return (
    <div className="analytics-metric-chart-wrap">
      <div className="analytics-metric-chart-head">
        <span>{metricLabel}</span>
      </div>
      <svg className="analytics-metric-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {yTicks.map((tick, index) => {
          const y = padTop + (index * plotHeight) / (yTicks.length - 1);
          return (
            <g key={`${metricKey}-tick-${index}`}>
              <line x1={padLeft} x2={width - padRight} y1={y} y2={y} stroke="#253142" strokeWidth="1" strokeDasharray="3 4" />
              <text x={padLeft - 8} y={y + 4} textAnchor="end" className="analytics-axis-label">
                {formatMetricValue(Math.round(tick))}
              </text>
            </g>
          );
        })}
        <path d={d} fill="none" stroke={stroke} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {xs.map((x, index) => {
          const bucket = buckets[index];
          const selected = !!selectedChartRange && selectedChartRange.from === bucket.date;
          return (
            <g key={`${metricKey}-point-${index}`} style={onBucketClick ? { cursor: "pointer" } : undefined} onClick={onBucketClick ? () => onBucketClick(bucket) : undefined}>
              <circle cx={x} cy={ys[index]} r={onBucketClick ? 10 : 3.5} fill="transparent" />
              <circle cx={x} cy={ys[index]} r="3.5" fill={onBucketClick && selected ? "#fff" : stroke} stroke={onBucketClick && selected ? stroke : "#0b1118"} strokeWidth="2" />
            </g>
          );
        })}
        {xIndexes.map((bucketIndex, tickIndex) => (
          <text
            key={`${metricKey}-date-${bucketIndex}-${tickIndex}`}
            x={xs[bucketIndex]}
            y={height - 10}
            textAnchor={tickIndex === 0 ? "start" : tickIndex === xIndexes.length - 1 ? "end" : "middle"}
            className="analytics-axis-label"
          >
            {formatChartDate(buckets[bucketIndex].date)}
          </text>
        ))}
      </svg>
    </div>
  );
}
