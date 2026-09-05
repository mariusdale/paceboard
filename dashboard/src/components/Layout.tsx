/** App shell: navigation rail, top bar with live sync state, content area. */
import { NavLink, Outlet } from "react-router-dom";
import { useConnections, useLatestSync, useStartSync, useStatus } from "../lib/hooks";
import { localTime, relativeAge } from "../lib/format";

const NAV = [
  { to: "/", label: "Overview", glyph: "◎", end: true },
  { to: "/activities", label: "Activities", glyph: "▤" },
  { to: "/recovery", label: "Recovery", glyph: "◍" },
  { to: "/training", label: "Training", glyph: "◈" },
  { to: "/explorer", label: "Data Explorer", glyph: "⌗" },
  { to: "/settings", label: "Connections", glyph: "⚙" },
];

export function Layout() {
  const status = useStatus();
  const connections = useConnections();
  const sync = useLatestSync();
  const start = useStartSync();

  const running = sync.data?.status === "running";
  const lastFinished = sync.data?.finished_at;

  return (
    <div className="app">
      <nav className="rail" aria-label="Sections">
        <div className="rail-brand">
          <strong>Paceboard</strong>
          <span>Health & performance</span>
        </div>
        <div className="rail-nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              <span className="glyph" aria-hidden="true">{item.glyph}</span>
              {item.label}
            </NavLink>
          ))}
        </div>
        <div className="rail-foot small faint">
          <div>Your data. Your space.</div>
          <div>Private · on this device</div>
        </div>
      </nav>

      <div className="main">
        <header className="topbar">
          <div className="provider-pills">{["garmin", "strava"].map(provider => {
            const connection = connections.data?.find(c => c.provider === provider);
            return <NavLink key={provider} to="/settings" className="provider-pill"><span className={`dot ${connection?.status === "connected" ? "ok" : "idle"}`} />{provider === "garmin" ? "Garmin" : "Strava"}<span className="sr-only">: {connection?.status ?? "checking"}</span></NavLink>;
          })}</div>
          <SyncPill />
          <span className="spacer" />
          {lastFinished && !running && (
            <span className="small faint nowrap">
              Last sync {localTime(lastFinished, status.data?.timezone ?? "Europe/Oslo")}
            </span>
          )}
          {start.isError && <span className="small" role="alert">{start.error.message}</span>}
          <button
            className="primary"
            disabled={running || start.isPending}
            onClick={() =>
              start.mutate({ providers: ["garmin", "strava"], mode: "incremental" })
            }
          >
            {running ? "Syncing…" : start.isPending ? "Starting…" : "Sync now"}
          </button>
        </header>
        <main className="content fade-in">
          {status.data?.fixture_mode && (
            <div className="banner warn" role="status" data-testid="fixture-banner">
              <span aria-hidden="true">⚠</span>
              <span>
                <strong>Fixture mode.</strong> Every number on screen is synthetic
                development data labelled <code>source=fixture</code>. Nothing here
                was measured by a device.
              </span>
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function SyncPill() {
  const { data, isLoading } = useLatestSync();
  if (isLoading) return <span className="small faint">Checking sync status…</span>;
  if (!data) {
    return (
      <span className="row small">
        <span className="dot idle" /> No sync has run yet
      </span>
    );
  }
  const tone =
    data.status === "running" ? "warn"
      : data.status === "success" ? "ok"
      : data.status === "partial" ? "warn"
      : data.status === "cancelled" ? "idle"
      : "err";
  const age = data.finished_at
    ? relativeAge((Date.now() - new Date(`${data.finished_at}Z`).getTime()) / 1000)
    : null;
  return (
    <span className="row small" role="status" aria-live="polite">
      <span className={`dot ${tone}`} />
      <span>
        {data.status === "running" ? (
          <>Sync running · <span className="muted">{data.current_step ?? "working"}</span></>
        ) : (
          <>
            Sync {data.status} · <span className="mono">{data.records_written}</span> records
            {data.errors_count > 0 && (
              <> · <span style={{ color: "var(--amber)" }}>{data.errors_count} issue{data.errors_count === 1 ? "" : "s"}</span></>
            )}
            {age && <span className="faint"> · {age}</span>}
          </>
        )}
      </span>
    </span>
  );
}
