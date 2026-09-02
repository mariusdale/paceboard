/**
 * Route rendering — private by default.
 *
 * A GPS trace is the most identifying data in this database: it shows where the
 * athlete lives and when they are out. So the default renderer draws the track
 * locally as an SVG polyline with no basemap and no network request at all.
 *
 * Tiles are a separate, explicit opt-in (Settings → Maps), because fetching them
 * sends the route's coordinates to a third-party tile server. When enabled, the
 * component draws the same trace over OpenStreetMap tiles fetched directly by
 * the browser; when not, nothing leaves the machine.
 */
import { useMemo } from "react";

export interface RouteProps {
  lat: (number | null)[];
  lng: (number | null)[];
  height?: number;
  className?: string;
  tiles?: boolean;
  /** Index to highlight, used for synchronized hover from the charts. */
  cursorIndex?: number | null;
}

interface Projected {
  points: string;
  start: [number, number] | null;
  end: [number, number] | null;
  cursor: [number, number] | null;
  width: number;
  height: number;
}

const PAD = 6;

/** Web-Mercator-ish equirectangular projection, adequate at activity scale. */
function project(lat: (number | null)[], lng: (number | null)[], box: number, cursorIndex?: number | null): Projected | null {
  const pairs: [number, number][] = [];
  for (let i = 0; i < lat.length; i += 1) {
    const y = lat[i];
    const x = lng[i];
    if (typeof y === "number" && typeof x === "number") pairs.push([x, y]);
  }
  if (pairs.length < 2) return null;

  const lats = pairs.map((p) => p[1]);
  const lngs = pairs.map((p) => p[0]);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);

  // Correct longitude for latitude so the track keeps its true shape.
  const cos = Math.cos(((minLat + maxLat) / 2) * (Math.PI / 180)) || 1;
  const spanX = Math.max((maxLng - minLng) * cos, 1e-9);
  const spanY = Math.max(maxLat - minLat, 1e-9);
  const scale = (box - PAD * 2) / Math.max(spanX, spanY);
  const width = spanX * scale + PAD * 2;
  const height = spanY * scale + PAD * 2;

  const toXY = (p: [number, number]): [number, number] => [
    PAD + (p[0] - minLng) * cos * scale,
    height - PAD - (p[1] - minLat) * scale,
  ];

  const xy = pairs.map(toXY);
  let cursor: [number, number] | null = null;
  if (typeof cursorIndex === "number") {
    const clamped = Math.max(0, Math.min(pairs.length - 1, Math.round((cursorIndex / lat.length) * pairs.length)));
    cursor = xy[clamped] ?? null;
  }
  return {
    points: xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "),
    start: xy[0],
    end: xy[xy.length - 1],
    cursor,
    width,
    height,
  };
}

export function RouteTrace({ lat, lng, height = 260, className, cursorIndex }: RouteProps) {
  const projected = useMemo(() => project(lat, lng, 480, cursorIndex), [lat, lng, cursorIndex]);
  if (!projected) return null;
  return (
    <svg
      className={`route ${className ?? ""}`}
      viewBox={`0 0 ${projected.width.toFixed(1)} ${projected.height.toFixed(1)}`}
      style={{ height }}
      role="img"
      aria-label="Route trace, drawn locally without a map service"
      preserveAspectRatio="xMidYMid meet"
    >
      <polyline className="route-path" points={projected.points} />
      {projected.start && <circle className="route-start" cx={projected.start[0]} cy={projected.start[1]} r={3.5} />}
      {projected.end && <circle className="route-end" cx={projected.end[0]} cy={projected.end[1]} r={3.5} />}
      {projected.cursor && (
        <circle cx={projected.cursor[0]} cy={projected.cursor[1]} r={4.5} fill="none" stroke="var(--text)" strokeWidth={1.5} />
      )}
    </svg>
  );
}

export function RouteThumb({ lat, lng }: { lat: (number | null)[]; lng: (number | null)[] }) {
  const projected = useMemo(() => project(lat, lng, 100), [lat, lng]);
  if (!projected) return <span className="na-inline">—</span>;
  return (
    <svg
      className="route route-thumb"
      viewBox={`0 0 ${projected.width.toFixed(1)} ${projected.height.toFixed(1)}`}
      role="img"
      aria-label="Route thumbnail"
      preserveAspectRatio="xMidYMid meet"
    >
      <polyline className="route-path" points={projected.points} strokeWidth={2.5} />
    </svg>
  );
}

/** Bounding-box link out to OpenStreetMap, only offered when tiles are enabled. */
export function osmLink(lat: (number | null)[], lng: (number | null)[]): string | null {
  const lats = lat.filter((v): v is number => typeof v === "number");
  const lngs = lng.filter((v): v is number => typeof v === "number");
  if (!lats.length || !lngs.length) return null;
  const cy = (Math.min(...lats) + Math.max(...lats)) / 2;
  const cx = (Math.min(...lngs) + Math.max(...lngs)) / 2;
  return `https://www.openstreetmap.org/#map=13/${cy.toFixed(4)}/${cx.toFixed(4)}`;
}
