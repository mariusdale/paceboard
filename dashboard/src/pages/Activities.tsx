/**
 * Activities — the combined, filterable table across both providers.
 *
 * One row per canonical activity, with badges showing which providers recorded
 * it. Uncertain cross-provider matches surface in a review strip above the
 * table rather than being silently merged or silently ignored.
 */
import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Activity, type Paged, type StreamSet } from "../lib/api";
import { useTimezone, useUnits, useSettings } from "../lib/hooks";
import {
  distance, duration, elevation, isPaceSport, localTime, pace, paceLabel,
  round, speed, speedLabel, sportLabel, SPORT_LABELS,
} from "../lib/format";
import { Empty, Failed, Loading } from "../components/States";
import { SourceBadge, StatusBadge } from "../components/SourceBadge";
import { RouteThumb } from "../components/RouteMap";

const PAGE_SIZE = 40;

export function Activities() {
  const units = useUnits();
  const timezone = useTimezone();
  const settings = useSettings();
  const showMaps = settings.data?.show_maps ?? false;

  const [search, setSearch] = useState("");
  const [sport, setSport] = useState("");
  const [source, setSource] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [offset, setOffset] = useState(0);

  const query = useQuery({
    queryKey: ["activities", { search, sport, source, start, end, offset }],
    queryFn: () =>
      api.get<Paged<Activity>>("/activities", {
        search: search || undefined,
        sport: sport || undefined,
        source: source || undefined,
        start: start || undefined,
        end: end || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  const reset = (fn: () => void) => { fn(); setOffset(0); };

  return (
    <>
      <DuplicateReview />

      <section className="panel">
        <div className="panel-head">
          <h1>Activities</h1>
          <span className="spacer" />
          {query.data && (
            <span className="small faint mono">
              {query.data.page.total} total · showing {query.data.items.length}
            </span>
          )}
        </div>

        <div className="panel-body">
          <div className="toolbar">
            <label className="field">
              <span className="label">Search name</span>
              <input
                value={search}
                onChange={(e) => reset(() => setSearch(e.target.value))}
                placeholder="Morning run"
                style={{ width: 180 }}
              />
            </label>
            <label className="field">
              <span className="label">Sport</span>
              <select value={sport} onChange={(e) => reset(() => setSport(e.target.value))}>
                <option value="">All sports</option>
                {Object.entries(SPORT_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="label">Source</span>
              <select value={source} onChange={(e) => reset(() => setSource(e.target.value))}>
                <option value="">Both providers</option>
                <option value="garmin">Garmin</option>
                <option value="strava">Strava</option>
              </select>
            </label>
            <label className="field">
              <span className="label">From</span>
              <input type="date" value={start} onChange={(e) => reset(() => setStart(e.target.value))} />
            </label>
            <label className="field">
              <span className="label">To</span>
              <input type="date" value={end} onChange={(e) => reset(() => setEnd(e.target.value))} />
            </label>
            {(search || sport || source || start || end) && (
              <button className="ghost" onClick={() => reset(() => { setSearch(""); setSport(""); setSource(""); setStart(""); setEnd(""); })}>
                Clear filters
              </button>
            )}
          </div>
        </div>

        {query.isLoading ? (
          <Loading label="Loading activities" rows={6} />
        ) : query.isError ? (
          <Failed error={query.error} retry={query.refetch} />
        ) : query.data!.items.length === 0 ? (
          <Empty
            title="No activities match these filters"
            detail={search || sport || source || start || end
              ? "Try widening the date range or clearing a filter."
              : "Nothing has been ingested yet. Run a sync from Connections."}
          />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {showMaps && <th>Route</th>}
                    <th>Activity</th>
                    <th>Sport</th>
                    <th className="n">Distance</th>
                    <th className="n">Moving</th>
                    <th className="n">{isPaceSport(sport) ? `Pace ${paceLabel(units)}` : "Pace / speed"}</th>
                    <th className="n">Ascent</th>
                    <th className="n">Avg HR</th>
                    <th>Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data!.items.map((activity) => (
                    <ActivityRow
                      key={activity.id}
                      activity={activity}
                      units={units}
                      timezone={timezone}
                      showMap={showMaps}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel-body row">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                ← Previous
              </button>
              <span className="small muted mono">
                {offset + 1}–{offset + query.data!.items.length} of {query.data!.page.total}
              </span>
              <button disabled={!query.data!.page.has_more} onClick={() => setOffset(offset + PAGE_SIZE)}>
                Next →
              </button>
            </div>
          </>
        )}
      </section>
    </>
  );
}

function ActivityRow({
  activity, units, timezone, showMap,
}: { activity: Activity; units: "metric" | "imperial"; timezone: string; showMap: boolean }) {
  const paceValue = isPaceSport(activity.sport)
    ? pace(activity.avg_speed_mps, units)
    : speed(activity.avg_speed_mps, units);
  const paceUnit = isPaceSport(activity.sport) ? paceLabel(units) : ` ${speedLabel(units)}`;

  return (
    <tr>
      {showMap && (
        <td style={{ width: 64 }}>
          {activity.has_gps ? <ThumbCell id={activity.id} /> : <span className="na-inline">—</span>}
        </td>
      )}
      <td>
        <Link to={`/activities/${activity.id}`}>{activity.name ?? "Untitled activity"}</Link>
        <div className="small faint mono">{localTime(activity.start_time_utc, timezone)}</div>
      </td>
      <td>{sportLabel(activity.sport)}</td>
      <td className="n">{distance(activity.distance_m, units) ?? "—"}</td>
      <td className="n">{duration(activity.moving_duration_s ?? activity.duration_s) ?? "—"}</td>
      <td className="n">{paceValue ? `${paceValue}${paceUnit}` : "—"}</td>
      <td className="n">{elevation(activity.elevation_gain_m, units) ?? "—"}</td>
      <td className="n">{round(activity.avg_hr, 0) ?? "—"}</td>
      <td>
        <span className="row" style={{ gap: 4 }}>
          {activity.sources.map((s) => (
            <SourceBadge key={s.source} source={s.source} title={`${s.source} id ${s.provider_id}`} />
          ))}
          {activity.duplicate_state === "merged" && <StatusBadge status="merged" label="merged" />}
          {activity.stream_status === "pending" && <StatusBadge status="pending" label="streams pending" />}
        </span>
      </td>
    </tr>
  );
}

/** Thumbnails are fetched lazily and only when the user has enabled maps. */
function ThumbCell({ id }: { id: number }) {
  const { data } = useQuery({
    queryKey: ["thumb", id],
    queryFn: () => api.get<StreamSet>(`/activities/${id}/streams`, { channels: "lat,lng", max_points: 120 }),
    staleTime: Infinity,
  });
  if (!data?.available || !data.channels.lat) return <span className="na-inline">—</span>;
  return <RouteThumb lat={data.channels.lat.data} lng={data.channels.lng?.data ?? []} />;
}

interface DuplicateRow {
  id: number;
  score: number;
  reasons: Record<string, unknown>;
  left: Record<string, any>;
  right: Record<string, any>;
}

/** Matches Paceboard is not confident enough to merge on its own. */
function DuplicateReview() {
  const client = useQueryClient();
  const timezone = useTimezone();
  const query = useQuery({
    queryKey: ["duplicates"],
    queryFn: () => api.get<DuplicateRow[]>("/activities/duplicates", { state: "pending" }),
  });
  const decide = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) =>
      api.post(`/activities/duplicates/${id}`, undefined, { accept }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["duplicates"] });
      client.invalidateQueries({ queryKey: ["activities"] });
    },
  });

  if (!query.data?.length) return null;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Possible duplicates to review</h2>
        <span className="spacer" />
        <span className="small faint">
          These pairs look like the same session recorded by both providers, but not
          closely enough for Paceboard to merge them on its own.
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="n">Match</th>
              <th>Garmin / Strava record</th>
              <th>Why</th>
              <th className="right">Decision</th>
            </tr>
          </thead>
          <tbody>
            {query.data.map((row) => (
              <tr key={row.id}>
                <td className="n">{Math.round(row.score * 100)}%</td>
                <td>
                  {[row.left, row.right].map((side) => (
                    <div key={side.provider_id} className="row small" style={{ gap: 6 }}>
                      <SourceBadge source={side.source} />
                      <span>{side.name ?? "Untitled"}</span>
                      <span className="faint mono">{localTime(side.start_time_utc, timezone)}</span>
                    </div>
                  ))}
                </td>
                <td className="small muted">
                  {Object.entries(row.reasons ?? {}).map(([k, v]) => (
                    <div key={k}>{k.replace(/_/g, " ")}: {String(v)}</div>
                  ))}
                </td>
                <td className="right nowrap">
                  <button className="sm" disabled={decide.isPending} onClick={() => decide.mutate({ id: row.id, accept: true })}>
                    Same activity
                  </button>{" "}
                  <button className="sm ghost" disabled={decide.isPending} onClick={() => decide.mutate({ id: row.id, accept: false })}>
                    Keep separate
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
