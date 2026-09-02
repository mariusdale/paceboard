/**
 * The five states every data surface must be able to show.
 *
 * The rule this file exists to enforce: an absent measurement is never drawn as
 * zero. It shows why it is absent, so "my HRV is 0" can never be confused with
 * "this watch does not record HRV".
 */
import type { ReactNode } from "react";
import type { Metric } from "../lib/api";
import { relativeAge } from "../lib/format";

export function Loading({ label = "Loading", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="panel-body" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="stack" aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="skeleton" style={{ height: i === 0 ? 22 : 13, width: `${94 - i * 13}%` }} />
        ))}
      </div>
    </div>
  );
}

export function Empty({ title, detail, action }: { title: string; detail?: string; action?: ReactNode }) {
  return (
    <div className="state">
      <div className="title">{title}</div>
      {detail && <div className="detail">{detail}</div>}
      {action}
    </div>
  );
}

export function Failed({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : "The request did not complete.";
  return (
    <div className="state err" role="alert">
      <div className="title">Could not load this data</div>
      <div className="detail">{message}</div>
      {retry && (
        <button onClick={retry} className="sm">
          Try again
        </button>
      )}
    </div>
  );
}

/** Renders a computed metric, or the stated reason it could not be computed. */
export function MetricValue({ metric, digits = 1 }: { metric?: Metric | null; digits?: number }) {
  if (!metric || !metric.available || metric.value === null) {
    return (
      <span className="na-inline" title={metric?.unavailable_reason ?? undefined}>
        Unavailable
      </span>
    );
  }
  return (
    <span className="mono">
      {metric.value.toFixed(digits)}
      {metric.units ? <span className="faint small"> {metric.units}</span> : null}
    </span>
  );
}

export function Unavailable({ reason }: { reason?: string | null }) {
  return (
    <div className="state">
      <div className="title">Unavailable</div>
      <div className="detail">{reason ?? "No data has been recorded for this window."}</div>
    </div>
  );
}

/** Flags data that is older than the sync cadence promises. */
export function StaleMark({ ageSeconds, thresholdSeconds }: { ageSeconds: number | null; thresholdSeconds: number }) {
  if (ageSeconds === null || ageSeconds < thresholdSeconds) return null;
  return (
    <span className="stale" title={`Last successful sync ${relativeAge(ageSeconds)}`}>
      <span className="dot warn" /> Stale · {relativeAge(ageSeconds)}
    </span>
  );
}

/** Some but not all of the requested data arrived; say which part is thin. */
export function PartialNote({ note }: { note: string }) {
  return (
    <div className="banner warn" role="status">
      <span aria-hidden="true">◐</span>
      <span>{note}</span>
    </div>
  );
}
