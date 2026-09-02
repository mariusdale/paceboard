/**
 * Source attribution. Every number in Paceboard can be traced to who measured
 * it, so this badge appears wherever a value could plausibly have come from
 * more than one provider.
 */
export function SourceBadge({ source, title }: { source: string; title?: string }) {
  const cls = source === "garmin" ? "garmin" : source === "strava" ? "strava" : source === "paceboard" ? "paceboard" : "neutral";
  return (
    <span className={`badge ${cls}`} title={title ?? `Source: ${source}`}>
      {source}
    </span>
  );
}

export function SourceList({ sources }: { sources: { source: string }[] }) {
  return (
    <span className="row" style={{ gap: 4 }}>
      {sources.map((s) => (
        <SourceBadge key={s.source} source={s.source} />
      ))}
    </span>
  );
}

const STATUS_CLASS: Record<string, string> = {
  ok: "ok", success: "ok", connected: "ok", available: "ok", complete: "ok",
  partial: "warn", pending: "warn", running: "warn", retry: "warn", stale: "warn",
  error: "err", failed: "err", disconnected: "err",
  no_data: "neutral", unsupported: "neutral", unavailable: "neutral",
  not_configured: "neutral", not_connected: "neutral", unmapped: "neutral",
  cancelled: "neutral", single: "neutral", merged: "paceboard",
  skipped: "neutral",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={`badge ${STATUS_CLASS[status] ?? "neutral"}`}>{label ?? status.replace(/_/g, " ")}</span>;
}
