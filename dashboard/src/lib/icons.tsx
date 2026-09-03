/**
 * Shared icon set — Lucide-derived stroke paths, lifted verbatim from the
 * Claude Design handoff so the nav rail, sport dots and section headers match
 * the mockup exactly. Inlined rather than pulled from a package: this is a
 * dozen icons, not a dependency.
 */
const PATHS: Record<string, string[]> = {
  overview: ["M22 12h-4l-3 9L9 3l-3 9H2"],
  list: ["M3 5h.01", "M3 12h.01", "M3 19h.01", "M8 5h13", "M8 12h13", "M8 19h13"],
  moon: ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9"],
  trendingUp: ["M16 7h6v6", "m22 7-8.5 8.5-5-5L2 19"],
  database: [
    "M3 5a9 3 0 1 0 18 0a9 3 0 1 0 -18 0",
    "M3 5V19A9 3 0 0 0 21 19V5",
    "M3 12A9 3 0 0 0 21 12",
  ],
  gear: [
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
    "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.8 1.17V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 7.3 19.4l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 3 14.6a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 7.3l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 2.83 1.51l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 21 10h.09a2 2 0 1 1 0 4H21Z",
  ],
  footprints: [
    "M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z",
    "M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z",
    "M16 17h4",
    "M4 13h4",
  ],
  walk: [
    "M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z",
    "M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z",
  ],
  bike: [
    "M15 17.5a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0 -7 0",
    "M2 17.5a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0 -7 0",
    "M14 5a1 1 0 1 0 2 0a1 1 0 1 0 -2 0",
    "M12 17.5V14l-3-3 4-3 2 3h2",
  ],
  dumbbell: [
    "M17.596 12.768a2 2 0 1 0 2.829-2.829l-1.768-1.767a2 2 0 0 0 2.828-2.829l-2.828-2.828a2 2 0 0 0-2.829 2.828l-1.767-1.768a2 2 0 1 0-2.829 2.829z",
    "m2.5 21.5 1.4-1.4",
    "m20.1 3.9 1.4-1.4",
    "M5.343 21.485a2 2 0 1 0 2.829-2.828l1.767 1.768a2 2 0 1 0 2.829-2.829l-6.364-6.364a2 2 0 1 0-2.829 2.829l1.768 1.767a2 2 0 0 0-2.828 2.829z",
    "m9.6 14.4 4.8-4.8",
  ],
  chevronDown: ["m6 9 6 6 6-6"],
  chevronLeft: ["m15 18-6-6 6-6"],
  sun: [
    "M12 2v2", "M12 20v2", "m4.93 4.93 1.41 1.41", "m17.66 17.66 1.41 1.41",
    "M2 12h2", "M20 12h2", "m6.34 17.66-1.41 1.41", "m19.07 4.93-1.41 1.41",
  ],
  sunCore: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z"],
};

const SPORT_ICON: Record<string, keyof typeof PATHS> = {
  run: "footprints",
  walk: "walk",
  hike: "walk",
  ride: "bike",
  swim: "walk",
  strength: "dumbbell",
  cardio: "trendingUp",
  row: "bike",
  paddle: "bike",
  yoga: "moon",
  ski: "bike",
  multisport: "trendingUp",
  transition: "trendingUp",
  other: "trendingUp",
};

const NAV_ICON: Record<string, keyof typeof PATHS> = {
  Overview: "overview",
  Activities: "list",
  Recovery: "moon",
  Training: "trendingUp",
  "Your data": "database",
  Connections: "gear",
};

export function Icon({
  name, size = 14, strokeWidth = 2.75, className,
}: { name: keyof typeof PATHS; size?: number; strokeWidth?: number; className?: string }) {
  const paths = PATHS[name] ?? [];
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      className={className} aria-hidden="true"
    >
      {paths.map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}

export function sportIcon(sport: string): keyof typeof PATHS {
  return SPORT_ICON[sport] ?? "trendingUp";
}

export function navIcon(label: string): keyof typeof PATHS {
  return NAV_ICON[label] ?? "overview";
}
