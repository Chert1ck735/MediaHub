import type { ReportPreviewResponse } from "../api";

export type ChartBucket = {
  date: string;
  endDate: string;
  days: number;
  views: number;
  likes: number;
  comments: number;
};

export function bucketTimeSeries(
  points: ReportPreviewResponse["points"],
  target = 16,
): ChartBucket[] {
  const pts = (points ?? []).filter(Boolean).slice().sort((a, b) =>
    a.date < b.date ? -1 : a.date > b.date ? 1 : 0);

  if (!pts.length) return [];

  const size = Math.max(1, Math.ceil(pts.length / target));
  const out: ChartBucket[] = [];

  for (let i = 0; i < pts.length; i += size) {
    const slice = pts.slice(i, i + size);
    out.push({
      date: slice[0].date,
      endDate: slice[slice.length - 1].date,
      days: slice.length,
      views: slice.reduce((sum, point) => sum + (point.views || 0), 0),
      likes: slice.reduce((sum, point) => sum + (point.likes || 0), 0),
      comments: slice.reduce((sum, point) => sum + (point.comments || 0), 0),
    });
  }

  return out;
}
