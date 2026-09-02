/**
 * Unit-aware formatting.
 *
 * Two rules the whole UI depends on:
 * 1. A missing value is never rendered as 0 or "-". It returns null, and the
 *    caller shows an explicit "Unavailable" state instead.
 * 2. Everything is stored metric; imperial is a presentation choice made here.
 */

export type UnitSystem = "metric" | "imperial";

const KM = 1000;
const MILE = 1609.344;
const FOOT = 0.3048;

export function num(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function distance(meters: number | null | undefined, units: UnitSystem): string | null {
  if (!num(meters)) return null;
  if (units === "imperial") {
    const miles = meters / MILE;
    return miles < 0.1 ? `${Math.round(meters / FOOT)} ft` : `${miles.toFixed(miles < 10 ? 2 : 1)} mi`;
  }
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / KM).toFixed(meters / KM < 10 ? 2 : 1)} km`;
}

export function elevation(meters: number | null | undefined, units: UnitSystem): string | null {
  if (!num(meters)) return null;
  return units === "imperial" ? `${Math.round(meters / FOOT)} ft` : `${Math.round(meters)} m`;
}

export function duration(seconds: number | null | undefined): string | null {
  if (!num(seconds) || seconds < 0) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function hours(seconds: number | null | undefined): string | null {
  if (!num(seconds)) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

/** Pace as min per km / per mile. Speed at or below zero has no pace. */
export function pace(speedMps: number | null | undefined, units: UnitSystem): string | null {
  if (!num(speedMps) || speedMps <= 0.05) return null;
  const perUnit = units === "imperial" ? MILE : KM;
  const secondsPerUnit = perUnit / speedMps;
  if (secondsPerUnit > 3600) return null;
  const m = Math.floor(secondsPerUnit / 60);
  const s = Math.round(secondsPerUnit % 60);
  const carry = s === 60;
  return `${carry ? m + 1 : m}:${String(carry ? 0 : s).padStart(2, "0")}`;
}

export function paceLabel(units: UnitSystem): string {
  return units === "imperial" ? "/mi" : "/km";
}

export function speed(speedMps: number | null | undefined, units: UnitSystem): string | null {
  if (!num(speedMps)) return null;
  const value = units === "imperial" ? speedMps * 2.236936 : speedMps * 3.6;
  return value.toFixed(1);
}

export function speedLabel(units: UnitSystem): string {
  return units === "imperial" ? "mph" : "km/h";
}

export function temperature(celsius: number | null | undefined, units: UnitSystem): string | null {
  if (!num(celsius)) return null;
  return units === "imperial"
    ? `${Math.round(celsius * 1.8 + 32)}°F`
    : `${Math.round(celsius)}°C`;
}

export function weight(kg: number | null | undefined, units: UnitSystem): string | null {
  if (!num(kg)) return null;
  return units === "imperial" ? `${(kg * 2.20462).toFixed(1)} lb` : `${kg.toFixed(1)} kg`;
}

export function round(value: number | null | undefined, digits = 0): string | null {
  if (!num(value)) return null;
  return value.toFixed(digits);
}

export function integer(value: number | null | undefined): string | null {
  if (!num(value)) return null;
  return Math.round(value).toLocaleString("en-US");
}

export function percent(value: number | null | undefined, digits = 0): string | null {
  if (!num(value)) return null;
  return `${value.toFixed(digits)}%`;
}

export function bytes(value: number | null | undefined): string | null {
  if (!num(value)) return null;
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

/** Render a UTC instant in the configured display timezone (Europe/Oslo by default). */
export function localTime(iso: string | null | undefined, timezone: string, withDate = true): string | null {
  if (!iso) return null;
  const stamp = iso.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return null;
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: timezone,
      ...(withDate ? { day: "2-digit", month: "short", year: "numeric" } : {}),
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  } catch {
    return date.toISOString().slice(0, 16).replace("T", " ");
  }
}

export function dayLabel(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(date);
}

export function relativeAge(seconds: number | null | undefined): string | null {
  if (!num(seconds)) return null;
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export const SPORT_LABELS: Record<string, string> = {
  run: "Run", ride: "Ride", swim: "Swim", walk: "Walk", hike: "Hike",
  strength: "Strength", cardio: "Cardio", row: "Row", paddle: "Paddle",
  yoga: "Yoga", ski: "Ski", multisport: "Multisport", transition: "Transition",
  other: "Other",
};

export function sportLabel(sport: string): string {
  return SPORT_LABELS[sport] ?? sport.replace(/_/g, " ");
}

/** Distance-based sports get pace; everything else gets speed or nothing. */
export function isPaceSport(sport: string): boolean {
  return ["run", "walk", "hike", "swim"].includes(sport);
}

export function daysAgo(count: number): string {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() - count);
  return date.toISOString().slice(0, 10);
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}
