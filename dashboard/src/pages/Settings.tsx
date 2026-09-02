/**
 * Connections and settings — provider state, sync control, preferences, storage
 * and the destructive controls, all in one place with confirmation.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api, type AppSettings, type Connection, type StravaStatus, type SyncRun,
} from "../lib/api";
import { useLatestSync, useStartSync } from "../lib/hooks";
import { bytes, localTime, relativeAge } from "../lib/format";
import { Failed, Loading } from "../components/States";
import { SourceBadge, StatusBadge } from "../components/SourceBadge";

export function Settings() {
  const client = useQueryClient();
  const connections = useQuery({ queryKey: ["connections"], queryFn: () => api.get<Connection[]>("/connections") });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<AppSettings>("/settings") });
  const strava = useQuery({ queryKey: ["strava-status"], queryFn: () => api.get<StravaStatus>("/auth/strava/status") });
  const sync = useLatestSync();
  const start = useStartSync();

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<AppSettings>("/settings", body),
    onSuccess: (data) => {
      client.setQueryData(["settings"], data);
      client.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  if (connections.isLoading || settings.isLoading) {
    return <section className="panel"><Loading label="Loading connections" rows={6} /></section>;
  }
  if (connections.isError) {
    return <section className="panel"><Failed error={connections.error} retry={connections.refetch} /></section>;
  }

  const garmin = connections.data!.find((c) => c.provider === "garmin");
  const stravaConn = connections.data!.find((c) => c.provider === "strava");
  const config = settings.data!;

  return (
    <>
      <section className="panel">
        <div className="panel-head"><h1>Connections</h1></div>
        <div className="grid g2" style={{ padding: 13 }}>
          <GarminCard connection={garmin} />
          <StravaCard connection={stravaConn} status={strava.data} onChange={() => {
            strava.refetch();
            connections.refetch();
          }} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Sync</h2>
          <span className="spacer" />
          {sync.data && <StatusBadge status={sync.data.status} />}
        </div>
        <div className="panel-body stack">
          <div className="toolbar">
            <button
              className="primary"
              disabled={sync.data?.status === "running" || start.isPending}
              onClick={() => start.mutate({ providers: ["garmin", "strava"], mode: "incremental" })}
            >
              Sync recent days
            </button>
            <button
              disabled={sync.data?.status === "running" || start.isPending}
              onClick={() => start.mutate({ providers: ["garmin", "strava"], mode: "backfill" })}
            >
              Backfill {config.backfill_days} days
            </button>
            <button
              disabled={sync.data?.status === "running" || start.isPending}
              onClick={() => start.mutate({ providers: ["garmin"], mode: "today", categories: ["activities", "daily_health"] })}
            >
              Refresh today only
            </button>
            {sync.data?.status === "running" && (
              <button
                className="danger"
                onClick={() => api.post(`/sync/${sync.data!.id}/cancel`).then(() => sync.refetch())}
              >
                Cancel run
              </button>
            )}
          </div>
          <SyncDetail run={sync.data ?? null} />
        </div>
      </section>

      <div className="grid g2">
        <section className="panel">
          <div className="panel-head"><h2>Preferences</h2></div>
          <div className="panel-body stack">
            {/* A <label> wrapper would hand its whole text to the first button
                as that button's accessible name; a labelled group keeps each
                button named by its own text. */}
            <div className="field">
              <span className="label" id="units-label">Units</span>
              <div className="segmented" role="group" aria-labelledby="units-label">
                <button aria-pressed={config.unit_system === "metric"} onClick={() => save.mutate({ unit_system: "metric" })}>
                  Metric
                </button>
                <button aria-pressed={config.unit_system === "imperial"} onClick={() => save.mutate({ unit_system: "imperial" })}>
                  Imperial
                </button>
              </div>
            </div>

            <NumberSetting
              label="Backfill window"
              suffix="days"
              value={config.backfill_days}
              min={1}
              max={3650}
              onSave={(value) => save.mutate({ backfill_days: value })}
            />
            <NumberSetting
              label="Fast sync interval"
              suffix="minutes"
              value={config.fast_interval_minutes}
              min={5}
              max={1440}
              onSave={(value) => save.mutate({ fast_interval_minutes: value })}
              note="Applies to today's health and recent activities. Takes effect at the next API restart."
            />

            <label className="field">
              <span className="label">Display timezone</span>
              <input
                defaultValue={config.timezone}
                onBlur={(e) => e.target.value !== config.timezone && save.mutate({ timezone: e.target.value })}
                style={{ width: 200 }}
              />
              <span className="small faint">Stored data is always UTC. Restart the API after changing this.</span>
            </label>

            <div style={{ borderTop: "1px solid var(--line)", paddingTop: 11 }}>
              <span className="label">Maps</span>
              <label className="inline" style={{ marginTop: 7 }}>
                <input
                  type="checkbox"
                  checked={config.show_maps}
                  onChange={(e) => save.mutate({ show_maps: e.target.checked })}
                />
                Show route maps
              </label>
              <label className="inline" style={{ marginTop: 5 }}>
                <input
                  type="checkbox"
                  checked={config.map_tiles_enabled}
                  disabled={!config.show_maps}
                  onChange={(e) => save.mutate({ map_tiles_enabled: e.target.checked })}
                />
                Allow links to an external map service
              </label>
              <p className="small faint" style={{ marginTop: 7, marginBottom: 0 }}>
                {config.notes?.map_tiles}
              </p>
            </div>

            <div className="small faint" style={{ borderTop: "1px solid var(--line)", paddingTop: 11 }}>
              Background scheduler: <strong>{config.scheduler_enabled ? "on" : "off"}</strong> ·
              daily reconciliation covers the last {config.reconcile_days} days
              {config.fixture_mode && <> · <span className="badge warn">fixture mode</span></>}
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><h2>Storage</h2></div>
          <div className="panel-body stack">
            <dl className="kv">
              <dt>Database</dt><dd className="small">{config.storage.database_path}</dd>
              <dt>Size on disk</dt><dd>{bytes(config.storage.database_bytes)}</dd>
              <dt>Total rows</dt><dd>{config.storage.total_rows.toLocaleString("en-US")}</dd>
            </dl>
            <div className="table-wrap" style={{ maxHeight: 210 }}>
              <table>
                <thead><tr><th>Table</th><th className="n">Rows</th></tr></thead>
                <tbody>
                  {Object.entries(config.storage.rows)
                    .filter(([, count]) => count > 0)
                    .map(([table, count]) => (
                      <tr key={table}>
                        <td className="mono small">{table}</td>
                        <td className="n">{count.toLocaleString("en-US")}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <DangerZone onDone={() => client.invalidateQueries()} />
          </div>
        </section>
      </div>
    </>
  );
}

function GarminCard({ connection }: { connection?: Connection }) {
  const [identity, setIdentity] = useState<string | null>(null);
  const verify = useMutation({
    mutationFn: () => api.post<Record<string, any>>("/tools/call", { tool: "get_unit_system", arguments: {} }),
    onSuccess: (data) => {
      setIdentity(
        data.status === "ok"
          ? "Verified — the MCP server answered a read call for your account."
          : `The read call returned "${data.status}". ${data.message ?? ""}`,
      );
    },
    onError: (error) => setIdentity(error instanceof Error ? error.message : "Verification failed"),
  });

  const ok = connection?.status === "connected";
  return (
    <div className="panel" style={{ background: "var(--surface-2)" }}>
      <div className="panel-head">
        <SourceBadge source="garmin" />
        <h2>Garmin MCP</h2>
        <span className="spacer" />
        <StatusBadge status={connection?.status ?? "unknown"} />
      </div>
      <div className="panel-body stack">
        <dl className="kv">
          <dt>Endpoint</dt><dd className="small">{connection?.endpoint}</dd>
          <dt>Transport</dt><dd className="small">streamable HTTP · read-only</dd>
          <dt>Allowlisted tools</dt><dd>{connection?.details?.allowlisted_tools ?? "—"}</dd>
          <dt>Last success</dt>
          <dd className="small">{connection?.last_success_at ? localTime(connection.last_success_at, "Europe/Oslo") : "never"}</dd>
        </dl>
        {connection?.last_error && <div className="banner err small">{connection.last_error}</div>}
        {!ok && (
          <div className="banner warn small">
            Paceboard cannot reach the Garmin MCP server, so Garmin syncs will
            fail. Start it with <code>./scripts/garmin-mcp-readonly.sh</code> and
            check that it answers on{" "}
            <code>{(connection?.endpoint ?? "http://127.0.0.1:8000/mcp").replace("/mcp", "/healthz")}</code>.
          </div>
        )}
        <div className="row">
          <button onClick={() => verify.mutate()} disabled={verify.isPending}>
            {verify.isPending ? "Checking…" : "Verify account access"}
          </button>
          {identity && <span className="small muted">{identity}</span>}
        </div>
        <p className="small faint" style={{ margin: 0 }}>
          Verification makes one harmless read call. Paceboard never sees your Garmin
          password or tokens — those stay with the MCP server.
        </p>
      </div>
    </div>
  );
}

function StravaCard({
  connection, status, onChange,
}: { connection?: Connection; status?: StravaStatus; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const connect = async () => {
    setBusy(true);
    try {
      const data = await api.get<{ authorize_url: string }>("/auth/strava/authorize");
      window.location.href = data.authorize_url;
    } finally {
      setBusy(false);
    }
  };
  const disconnect = useMutation({
    mutationFn: () => api.post("/auth/strava/disconnect"),
    onSuccess: onChange,
  });

  const configured = status?.configured ?? connection?.configured ?? false;
  const connected = status?.connected ?? false;

  return (
    <div className="panel" style={{ background: "var(--surface-2)" }}>
      <div className="panel-head">
        <SourceBadge source="strava" />
        <h2>Strava</h2>
        <span className="spacer" />
        <StatusBadge status={connected ? "connected" : configured ? "not_connected" : "not_configured"} />
      </div>
      <div className="panel-body stack">
        {!configured ? (
          <>
            <div className="banner warn small">
              <div>
                <strong>Strava not connected.</strong> Paceboard works fully on Garmin
                data without it — Strava adds segment efforts and anything you record
                on devices Garmin never sees.
              </div>
            </div>
            <ol className="small muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
              <li>Create an API application at <a href="https://www.strava.com/settings/api" target="_blank" rel="noreferrer noopener">strava.com/settings/api</a>.</li>
              <li>Set the callback domain to <code>127.0.0.1</code>.</li>
              <li>
                Put the client ID and secret in <code>.env</code> as{" "}
                <code>STRAVA_CLIENT_ID</code> and <code>STRAVA_CLIENT_SECRET</code>.
              </li>
              <li>Restart the Paceboard API, then press Connect here.</li>
            </ol>
          </>
        ) : (
          <>
            <dl className="kv">
              <dt>Athlete</dt><dd className="small">{status?.athlete?.athlete_name || status?.athlete?.athlete_id || "—"}</dd>
              <dt>Scopes</dt><dd className="small">{status?.athlete?.scope || status?.scopes_requested}</dd>
              <dt>Token expires</dt>
              <dd className="small">{status?.athlete?.expires_at ? localTime(status.athlete.expires_at, "Europe/Oslo") : "—"}</dd>
              <dt>At rest</dt><dd className="small">{status?.tokens_encrypted ? "encrypted" : "plaintext (owner-only file)"}</dd>
              <dt>Rate limit left</dt>
              <dd className="small">
                {status?.rate_limit?.short_remaining ?? "—"} / 15 min ·{" "}
                {status?.rate_limit?.daily_remaining ?? "—"} today
              </dd>
            </dl>
            <div className="row">
              {connected ? (
                <button className="danger" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
                  Disconnect and revoke
                </button>
              ) : (
                <button className="primary" onClick={connect} disabled={busy}>
                  {busy ? "Opening Strava…" : "Connect Strava"}
                </button>
              )}
            </div>
          </>
        )}
        <p className="small faint" style={{ margin: 0 }}>
          {connection?.details?.mcp_alternative?.reason}
        </p>
      </div>
    </div>
  );
}

function SyncDetail({ run }: { run: SyncRun | null }) {
  if (!run) return <p className="small muted" style={{ margin: 0 }}>No sync has run yet.</p>;
  return (
    <div className="stack">
      <dl className="kv">
        <dt>Run</dt><dd>#{run.id} · {run.mode} · {run.trigger}</dd>
        <dt>Window</dt><dd>{run.range_start} → {run.range_end}</dd>
        <dt>Started</dt><dd className="small">{localTime(run.started_at, "Europe/Oslo")}</dd>
        <dt>Records written</dt><dd>{run.records_written.toLocaleString("en-US")}</dd>
        {run.current_step && (<><dt>Step</dt><dd className="small">{run.current_step}</dd></>)}
      </dl>
      {run.summary?.tasks?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Task</th><th>Provider</th><th>Status</th><th className="n">Records</th><th className="n">Calls</th><th>Notes</th></tr>
            </thead>
            <tbody>
              {run.summary.tasks.map((task, i) => (
                <tr key={`${task.name}-${i}`}>
                  <td className="mono small">{task.name}</td>
                  <td><SourceBadge source={task.provider} /></td>
                  <td><StatusBadge status={task.status} /></td>
                  <td className="n">{task.records}</td>
                  <td className="n">{task.calls}</td>
                  <td className="small faint">{task.notes.join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {run.errors.length > 0 && (
        <div className="stack">
          <span className="label">Issues in this run</span>
          {run.errors.slice(0, 8).map((error, i) => (
            <div key={i} className="banner warn small">
              <span className="mono">{error.capability ?? error.provider}</span>
              <span className="spacer" />
              <span>{error.message}</span>
              <span className="faint nowrap">
                {relativeAge((Date.now() - new Date(`${error.occurred_at}Z`).getTime()) / 1000)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NumberSetting({
  label, value, suffix, min, max, onSave, note,
}: { label: string; value: number; suffix: string; min: number; max: number; onSave: (value: number) => void; note?: string }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const dirty = draft !== String(value);
  return (
    <label className="field">
      <span className="label">{label}</span>
      <span className="row">
        <input
          type="number"
          value={draft}
          min={min}
          max={max}
          onChange={(e) => setDraft(e.target.value)}
          style={{ width: 92 }}
        />
        <span className="small muted">{suffix}</span>
        {dirty && (
          <button className="sm primary" onClick={() => onSave(Number(draft))}>
            Save
          </button>
        )}
      </span>
      {note && <span className="small faint">{note}</span>}
    </label>
  );
}

/** Deletion is gated on typing the scope back, because it cannot be undone. */
function DangerZone({ onDone }: { onDone: () => void }) {
  const [scope, setScope] = useState<"raw" | "derived" | "all">("raw");
  const [confirm, setConfirm] = useState("");
  const [result, setResult] = useState<string | null>(null);

  const clear = useMutation({
    mutationFn: () => api.del<{ scope: string; deleted: Record<string, number> }>("/data", { scope, confirm }),
    onSuccess: (data) => {
      const total = Object.values(data.deleted).reduce((s, v) => s + v, 0);
      setResult(`Deleted ${total.toLocaleString("en-US")} rows.`);
      setConfirm("");
      onDone();
    },
    onError: (error) => setResult(error instanceof Error ? error.message : "Delete failed"),
  });

  const DESCRIPTIONS: Record<string, string> = {
    raw: "Removes stored provider payloads. Normalized data and analytics stay; the Data Explorer will be empty until the next sync.",
    derived: "Removes computed metrics. They are recalculated on the next sync or scheduler pass.",
    all: "Empties every data table. Your settings and the schema remain, so the app still starts — but all health data is gone.",
  };

  return (
    <div style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }}>
      <span className="label">Delete stored data</span>
      <div className="toolbar" style={{ marginTop: 7 }}>
        <select value={scope} onChange={(e) => { setScope(e.target.value as any); setConfirm(""); setResult(null); }}>
          <option value="raw">Raw provider payloads</option>
          <option value="derived">Derived metrics</option>
          <option value="all">Everything</option>
        </select>
        <label className="field">
          <span className="label">Type “{scope}” to confirm</span>
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} style={{ width: 110 }} />
        </label>
        <button className="danger" disabled={confirm !== scope || clear.isPending} onClick={() => clear.mutate()}>
          {clear.isPending ? "Deleting…" : "Delete"}
        </button>
      </div>
      <p className="small faint" style={{ marginTop: 7, marginBottom: 0 }}>{DESCRIPTIONS[scope]}</p>
      {result && <p className="small" style={{ marginBottom: 0 }}>{result}</p>}
    </div>
  );
}
