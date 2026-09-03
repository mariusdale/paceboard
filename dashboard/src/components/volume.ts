/** Weekly volume bars, with zero-weeks filled so the axis stays continuous. */
import type { VolumeBucket } from "../lib/api";
import { dayLabel, sportLabel } from "../lib/format";
import type { Palette, SeriesSpec } from "./Charts";

export function buildWeeklyVolume(
  buckets: VolumeBucket[],
  palette: Palette,
): { data: Record<string, any>[]; series: SeriesSpec[] } {
  const PALETTE = [palette.primary, palette.secondary, palette.quaternary, palette.tertiary, palette.quinary, palette.secondaryFill];
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
