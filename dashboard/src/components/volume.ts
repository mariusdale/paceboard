/** Weekly volume bars, with zero-weeks filled so the axis stays continuous. */
import type { VolumeBucket } from "../lib/api";
import { dayLabel, sportLabel } from "../lib/format";
import { CHART, type SeriesSpec } from "./Charts";

const PALETTE = [CHART.teal, CHART.amber, CHART.violet, CHART.green, CHART.rose, CHART.grey];

export function buildWeeklyVolume(buckets: VolumeBucket[]): { data: Record<string, any>[]; series: SeriesSpec[] } {
  if (!buckets.length) return { data: [], series: [] };
  const sports = Array.from(new Set(buckets.map((b) => b.sport))).sort();
  const weeks = Array.from(new Set(buckets.map((b) => b.week_start))).sort();

  // Fill the gaps: a week with no activity is a real zero, not a missing point.
  const filled: string[] = [];
  const cursor = new Date(`${weeks[0]}T00:00:00Z`);
  const last = new Date(`${weeks[weeks.length - 1]}T00:00:00Z`);
  while (cursor <= last && filled.length < 120) {
    filled.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 7);
  }

  const data = filled.map((week) => {
    const row: Record<string, any> = { x: dayLabel(week) ?? week };
    for (const sport of sports) {
      const found = buckets.find((b) => b.week_start === week && b.sport === sport);
      row[sport] = found ? Math.round(found.duration_s / 60) : 0;
    }
    return row;
  });

  const series: SeriesSpec[] = sports.map((sport, i) => ({
    key: sport,
    name: sportLabel(sport),
    color: PALETTE[i % PALETTE.length],
    unit: "min",
    digits: 0,
  }));
  return { data, series };
}
