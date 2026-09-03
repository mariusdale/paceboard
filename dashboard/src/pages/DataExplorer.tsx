/**
 * Data Explorer — what Paceboard can read, what it actually got, and the raw
 * bytes behind every number in the rest of the app.
 *
 * The manual invocation form only offers tools from the backend's read-only
 * allowlist, and the backend validates the tool and its arguments again before
 * anything reaches the MCP server.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type Capability, type RawPayloadRow, type Status, type ToolSpec } from "../lib/api";
import { useStatus, useTimezone } from "../lib/hooks";
import { bytes, localTime, relativeAge } from "../lib/format";
import { Empty, Failed, Loading } from "../components/States";
import { SourceBadge, StatusBadge } from "../components/SourceBadge";
import { JsonViewer } from "../components/JsonViewer";

type Tab = "capabilities" | "payloads" | "invoke";

interface RawList {
  items: RawPayloadRow[];
  page: { total: number; limit: number; offset: number; has_more: boolean };
  endpoints: { provider: string; endpoint: string; status: string; count: number; last_retrieved_at: string | null }[];
}

export function DataExplorer() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("reference") ? "payloads" : "capabilities");
  const status = useStatus();

  return (
    <>
      <section className="hero">
        <div style={{ maxWidth: 700 }}>
          <div className="hero-eyebrow">Your data</div>
          <h1 style={{ fontSize: 27 }}>Everything Paceboard has pulled, and nothing it hasn't.</h1>
          <p>
            Every provider response is stored verbatim, including the ones that returned
            nothing — a metric with no data is visibly recorded as such, never silently missing.
          </p>
        </div>
      </section>

      <DataTiles status={status.data} />

      <section className="panel">
        <div className="panel-head">
          <h2>By source</h2>
          <span className="small faint">where each kind of number comes from, and how fresh it is</span>
          <span className="spacer" />
          <div className="segmented" role="tablist" aria-label="Explorer view">
            <button role="tab" aria-pressed={tab === "capabilities"} onClick={() => setTab("capabilities")}>Capabilities</button>
            <button role="tab" aria-pressed={tab === "payloads"} onClick={() => setTab("payloads")}>Raw payloads</button>
            <button role="tab" aria-pressed={tab === "invoke"} onClick={() => setTab("invoke")}>Run a read tool</button>
          </div>
        </div>
        {status.data?.freshness && status.data.freshness.length > 0 && (
          <div className="panel-body row" style={{ gap: 18 }}>
            {status.data.freshness.map((f) => (
              <span key={`${f.provider}:${f.category}`} className="row small">
                <SourceBadge source={f.provider} />
                <span className="muted">{f.category}</span>
                <span className="mono">{relativeAge(f.age_seconds) ?? "never"}</span>
                {f.cursor_date && <span className="faint">through {f.cursor_date}</span>}
              </span>
            ))}
          </div>
        )}
      </section>

      {tab === "capabilities" && <Capabilities />}
      {tab === "payloads" && <Payloads initialReference={params.get("reference") ?? ""} />}
      {tab === "invoke" && <Invoke />}
    </>
  );
}

function DataTiles({ status }: { status?: Status }) {
  if (!status) return null;
  const tiles = [
    { label: "Activities stored", value: status.counts.activities?.toLocaleString("en-US") ?? "0" },
    { label: "Days of daily metrics", value: status.counts.daily_health?.toLocaleString("en-US") ?? "0" },
    { label: "Providers connected", value: `${status.freshness.length ? new Set(status.freshness.map((f) => f.provider)).size : 0}`, sub: "of 3 supported" },
    { label: "Database", value: bytes(status.database_bytes) ?? "—", sub: "on this machine only" },
  ];
  return (
    <div className="grid g4">
      {tiles.map((t) => (
        <div key={t.label} className="stat-card" style={{ padding: "13px 15px" }}>
          <span className="label">{t.label}</span>
          <div className="stat-value" style={{ fontSize: 27, marginTop: 5 }}>{t.value}</div>
          {t.sub && <div className="stat-sub">{t.sub}</div>}
        </div>
      ))}
    </div>
  );
}

function Capabilities() {
  const [provider, setProvider] = useState("");
  const [status, setStatus] = useState("");
  const query = useQuery({
    queryKey: ["capabilities", provider, status],
    queryFn: () => api.get<Capability[]>("/capabilities", { provider: provider || undefined, status: status || undefined }),
  });
  const timezone = useTimezone();

  if (query.isLoading) return <section className="panel"><Loading rows={6} /></section>;
  if (query.isError) return <section className="panel"><Failed error={query.error} retry={query.refetch} /></section>;

  const rows = query.data!;
  const counts = rows.reduce<Record<string, number>>((acc, row) => {
    acc[row.status] = (acc[row.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Capability catalog</h2>
        <span className="spacer" />
        <span className="row small">
          {Object.entries(counts).map(([key, count]) => (
            <span key={key} className="row" style={{ gap: 4 }}>
              <StatusBadge status={key} /> <span className="mono">{count}</span>
            </span>
          ))}
        </span>
      </div>
      <div className="panel-body toolbar">
        <label className="field">
          <span className="label">Provider</span>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="">All providers</option>
            <option value="garmin">Garmin</option>
            <option value="strava">Strava</option>
          </select>
        </label>
        <label className="field">
          <span className="label">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            <option value="available">Available and mapped</option>
            <option value="unavailable">Mapped but missing on this server</option>
            <option value="unmapped">Exposed but not mapped by Paceboard</option>
          </select>
        </label>
      </div>
      {rows.length === 0 ? (
        <Empty
          title="No capabilities recorded yet"
          detail="Capabilities are discovered at the start of each sync. Run one from Connections."
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Tool / endpoint</th>
                <th>Provider</th>
                <th>Category</th>
                <th>Cadence</th>
                <th>Status</th>
                <th>Last call</th>
                <th className="n">Calls</th>
                <th className="n">Errors</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.provider}:${row.name}`}>
                  <td>
                    <span className="mono">{row.name}</span>
                    {row.description && <div className="small faint">{row.description.slice(0, 110)}</div>}
                  </td>
                  <td><SourceBadge source={row.provider} /></td>
                  <td className="small">{row.category}</td>
                  <td className="small">{row.enabled ? row.cadence : <span className="faint">on demand</span>}</td>
                  <td>
                    <StatusBadge status={row.status} />
                    {row.last_status && row.last_status !== "ok" && (
                      <div className="small faint" title={row.last_note ?? undefined}>{row.last_status.replace(/_/g, " ")}</div>
                    )}
                  </td>
                  <td className="small mono">{localTime(row.last_called_at, timezone) ?? "—"}</td>
                  <td className="n">{row.call_count}</td>
                  <td className="n">{row.error_count || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Payloads({ initialReference }: { initialReference: string }) {
  const timezone = useTimezone();
  const [provider, setProvider] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [status, setStatus] = useState("");
  const [reference, setReference] = useState(initialReference);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["raw", provider, endpoint, status, reference, offset],
    queryFn: () =>
      api.get<RawList>("/raw-data", {
        provider: provider || undefined,
        endpoint: endpoint || undefined,
        status: status || undefined,
        reference_id: reference || undefined,
        limit: 25,
        offset,
      }),
  });

  const detail = useQuery({
    queryKey: ["raw-detail", selected],
    queryFn: () => api.get<RawPayloadRow & { content: unknown }>(`/raw-data/${selected}`),
    enabled: selected !== null,
  });

  const endpoints = useMemo(
    () => Array.from(new Set((list.data?.endpoints ?? []).map((e) => e.endpoint))).sort(),
    [list.data],
  );

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>Raw payloads</h2>
          <span className="spacer" />
          {list.data && <span className="small faint mono">{list.data.page.total} stored</span>}
          <a className="btn" href={api.exportUrl("json", { dataset: "raw_payloads", days: 365 })} download>
            Export JSON
          </a>
          <a className="btn" href={api.exportUrl("csv", { dataset: "raw_payloads", days: 365 })} download>
            Export CSV
          </a>
        </div>
        <div className="panel-body toolbar">
          <label className="field">
            <span className="label">Provider</span>
            <select value={provider} onChange={(e) => { setProvider(e.target.value); setOffset(0); }}>
              <option value="">All</option>
              <option value="garmin">Garmin</option>
              <option value="strava">Strava</option>
            </select>
          </label>
          <label className="field">
            <span className="label">Endpoint</span>
            <select value={endpoint} onChange={(e) => { setEndpoint(e.target.value); setOffset(0); }}>
              <option value="">All endpoints</option>
              {endpoints.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="label">Result</span>
            <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
              <option value="">Any result</option>
              <option value="ok">ok</option>
              <option value="no_data">no data</option>
              <option value="unsupported">unsupported</option>
              <option value="invalid_request">invalid request</option>
              <option value="error">error</option>
            </select>
          </label>
          <label className="field">
            <span className="label">Reference id</span>
            <input value={reference} onChange={(e) => { setReference(e.target.value); setOffset(0); }} placeholder="activity id" style={{ width: 150 }} />
          </label>
        </div>

        {list.isLoading ? <Loading rows={5} /> : list.isError ? (
          <Failed error={list.error} retry={list.refetch} />
        ) : list.data!.items.length === 0 ? (
          <Empty title="No payloads match" detail="Adjust the filters, or run a sync to populate the store." />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Endpoint</th>
                    <th>Provider</th>
                    <th>Parameters</th>
                    <th>Result</th>
                    <th className="n">Size</th>
                    <th className="n">ms</th>
                    <th>Retrieved</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data!.items.map((row) => (
                    <tr
                      key={row.id}
                      className="clickable"
                      onClick={() => setSelected(row.id)}
                      tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") setSelected(row.id); }}
                      aria-label={`Open payload ${row.id}`}
                    >
                      <td className="mono">{row.endpoint}</td>
                      <td><SourceBadge source={row.provider} /></td>
                      <td className="small mono faint">
                        {Object.entries(row.params ?? {}).map(([k, v]) => `${k}=${v}`).join(" ") || "—"}
                      </td>
                      <td><StatusBadge status={row.status} /></td>
                      <td className="n">{bytes(row.byte_size)}</td>
                      <td className="n">{row.duration_ms ?? "—"}</td>
                      <td className="small mono">{localTime(row.retrieved_at, timezone)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel-body row">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>← Previous</button>
              <span className="small muted mono">{offset + 1}–{offset + list.data!.items.length} of {list.data!.page.total}</span>
              <button disabled={!list.data!.page.has_more} onClick={() => setOffset(offset + 25)}>Next →</button>
            </div>
          </>
        )}
      </section>

      {selected !== null && (
        <section className="panel">
          <div className="panel-head">
            <h2>Payload {selected}</h2>
            <span className="spacer" />
            <button className="ghost sm" onClick={() => setSelected(null)}>Close</button>
          </div>
          <div className="panel-body">
            {detail.isLoading ? <Loading rows={5} /> : detail.data ? (
              <>
                <dl className="kv" style={{ marginBottom: 12 }}>
                  <dt>Endpoint</dt><dd>{detail.data.endpoint}</dd>
                  <dt>Parameters</dt><dd>{JSON.stringify(detail.data.params ?? {})}</dd>
                  <dt>Result</dt><dd>{detail.data.status}</dd>
                  <dt>Schema version</dt><dd>{detail.data.schema_version}</dd>
                  <dt>Retrieved</dt><dd>{localTime(detail.data.retrieved_at, timezone)}</dd>
                </dl>
                <JsonViewer value={detail.data.content} />
              </>
            ) : null}
          </div>
        </section>
      )}
    </>
  );
}

function Invoke() {
  const [tool, setTool] = useState("");
  const [args, setArgs] = useState<Record<string, string>>({});

  const tools = useQuery({ queryKey: ["tools"], queryFn: () => api.get<ToolSpec[]>("/tools") });
  const run = useMutation({
    mutationFn: (body: { tool: string; arguments: Record<string, unknown> }) =>
      api.post<Record<string, any>>("/tools/call", body),
  });

  const spec = tools.data?.find((t) => t.name === tool);

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>Run a read-only tool</h2>
          <span className="spacer" />
          <SourceBadge source="garmin" />
        </div>
        <div className="panel-body stack">
          <div className="banner info">
            <span aria-hidden="true">🔒</span>
            <span>
              Only the read tools below can be invoked. Anything that writes to your
              Garmin account — creating, uploading, scheduling, logging or deleting —
              is refused by the backend, not just hidden here.
            </span>
          </div>

          <div className="toolbar">
            <label className="field" style={{ minWidth: 260 }}>
              <span className="label">Tool</span>
              <select value={tool} onChange={(e) => { setTool(e.target.value); setArgs({}); }}>
                <option value="">Choose a tool…</option>
                {(tools.data ?? []).map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name} — {t.category}
                  </option>
                ))}
              </select>
            </label>
            {spec?.arguments.map((name) => (
              <label className="field" key={name}>
                <span className="label">{name}</span>
                <input
                  value={args[name] ?? ""}
                  onChange={(e) => setArgs({ ...args, [name]: e.target.value })}
                  placeholder={name.includes("date") ? "YYYY-MM-DD" : ""}
                  style={{ width: 130 }}
                />
              </label>
            ))}
            <button
              className="primary"
              disabled={!tool || run.isPending}
              onClick={() =>
                run.mutate({
                  tool,
                  arguments: Object.fromEntries(
                    Object.entries(args)
                      .filter(([, v]) => v !== "")
                      .map(([k, v]) => [k, /^\d+$/.test(v) ? Number(v) : v]),
                  ),
                })
              }
            >
              {run.isPending ? "Calling…" : "Run"}
            </button>
          </div>

          {spec && (
            <div className="small muted">
              <strong>{spec.name}</strong> · scope {spec.scope} · {spec.scheduled ? `synced ${spec.cadence}` : "on demand only"}
              {spec.max_range_days ? ` · maximum ${spec.max_range_days}-day range` : ""}
              {spec.notes ? ` · ${spec.notes}` : ""}
            </div>
          )}
        </div>
      </section>

      {run.isError && (
        <section className="panel">
          <Failed error={run.error} />
        </section>
      )}

      {run.data && (
        <section className="panel">
          <div className="panel-head">
            <h2>Response</h2>
            <span className="spacer" />
            <StatusBadge status={run.data.status} />
            <span className="small faint mono">{run.data.duration_ms} ms · stored as payload {run.data.raw_payload_id}</span>
          </div>
          <div className="panel-body">
            {run.data.message && <div className="banner warn" style={{ marginBottom: 10 }}>{run.data.message}</div>}
            <JsonViewer value={run.data.content} />
          </div>
        </section>
      )}
    </>
  );
}
