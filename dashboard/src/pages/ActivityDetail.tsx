/**
 * Activity detail — everything recorded about one session.
 *
 * The charts share a Recharts `syncId`, so hovering any of them moves the
 * cursor on all of them and on the route trace. That single interaction is what
 * turns four separate series into one readable picture of the session.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, type Activity, type Metric, type StreamSet } from "../lib/api";
import { useTimezone, useSettings, useUnits } from "../lib/hooks";
import {
  distance,
  duration,
  elevation,
  isPaceSport,
  localTime,
  pace,
  paceLabel,
  percent,
  round,
  speed,
  speedLabel,
  sportLabel,
  temperature,
} from "../lib/format";
import { CHART, TimeChart, type SeriesSpec } from "../components/Charts";
import {
  Empty,
  Failed,
  Loading,
  MetricValue,
  Unavailable,
} from "../components/States";
import { SourceBadge, StatusBadge } from "../components/SourceBadge";
import { RouteTrace, osmLink } from "../components/RouteMap";

interface Analysis {
  activity_id: number;
  metrics: Record<string, Metric>;
  source_comparison: {
    available: boolean;
    unavailable_reason: string | null;
    fields: {
      field: string;
      values: Record<string, number | null>;
      difference: number;
      difference_pct: number | null;
      chosen_source: string | null;
    }[];
  };
}

interface Lap {
  source: string;
  lap_index: number;
  start_time_utc: string | null;
  duration_s: number | null;
  moving_duration_s: number | null;
  distance_m: number | null;
  avg_speed_mps: number | null;
  max_speed_mps: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_power_w: number | null;
  avg_cadence: number | null;
  elevation_gain_m: number | null;
  calories: number | null;
  intensity_type: string | null;
}

interface Split {
  source: string;
  split_type: string;
  split_index: number;
  distance_m: number | null;
  duration_s: number | null;
  elevation_gain_m: number | null;
  avg_speed_mps: number | null;
  avg_hr: number | null;
  details: Record<string, any> | null;
}

interface ZoneResponse {
  available: boolean;
  unavailable_reason: string | null;
  zones: {
    source: string;
    kind: string;
    zone: number;
    seconds: number | null;
    low: number | null;
    high: number | null;
  }[];
}

export function ActivityDetail() {
  const { id } = useParams();
  const units = useUnits();
  const timezone = useTimezone();
  const settings = useSettings();
  const [showRaw, setShowRaw] = useState(false);

  const activity = useQuery({
    queryKey: ["activity", id],
    queryFn: () => api.get<Activity>(`/activities/${id}`),
  });
  const streams = useQuery({
    queryKey: ["streams", id],
    queryFn: () =>
      api.get<StreamSet>(`/activities/${id}/streams`, { max_points: 1200 }),
  });
  const laps = useQuery({
    queryKey: ["laps", id],
    queryFn: () => api.get<Lap[]>(`/activities/${id}/laps`),
  });
  const zones = useQuery({
    queryKey: ["zones", id],
    queryFn: () => api.get<ZoneResponse>(`/activities/${id}/zones`),
  });
  const splits = useQuery({
    queryKey: ["splits", id],
    queryFn: () => api.get<Split[]>(`/activities/${id}/splits`),
  });
  const analysis = useQuery({
    queryKey: ["analysis", id],
    queryFn: () => api.get<Analysis>(`/activities/${id}/analysis`),
  });

  if (activity.isLoading)
    return (
      <section className="panel">
        <Loading label="Loading activity" rows={6} />
      </section>
    );
  if (activity.isError)
    return (
      <section className="panel">
        <Failed error={activity.error} retry={activity.refetch} />
      </section>
    );

  const a = activity.data!;
  const lapHas = (key: keyof Lap) => laps.data?.some(lap => lap[key] != null);
  const chartData = buildChartData(streams.data, units, a.sport);
  const showMaps = settings.data?.show_maps ?? false;
  const hasRoute = streams.data?.available && streams.data.channels.lat;
  const availableMetrics = Object.entries(analysis.data?.metrics ?? {}).filter(([key, metric]) => ["trimp", "aerobic_decoupling", "normalized_power", "intensity_factor", "training_stress_score", "watts_per_kg"].includes(key) && metric.available && metric.value != null);
  const metricNames: Record<string, string> = { trimp: "Training impulse", aerobic_decoupling: "Cardiac drift", normalized_power: "Normalized power", intensity_factor: "Intensity factor", training_stress_score: "Training stress score", watts_per_kg: "Watts / kg" };
  const missing = Object.entries(analysis.data?.metrics ?? {}).filter(([, metric]) => !metric.available);


  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h1>{a.name ?? "Untitled activity"}</h1>
            <div className="small faint mono">
              {localTime(a.start_time_utc, timezone)} · {sportLabel(a.sport)}
              {a.provider_type && a.provider_type !== a.sport
                ? ` (${a.provider_type})`
                : ""}
              {a.device_name ? ` · ${a.device_name}` : ""}
            </div>
          </div>
          <span className="spacer" />
          <span className="row" style={{ gap: 5 }}>
            {a.sources.map((s) => (
              <SourceBadge
                key={s.source}
                source={s.source}
                title={`${s.source} id ${s.provider_id}`}
              />
            ))}
            {a.duplicate_state === "merged" && (
              <StatusBadge status="merged" label="merged record" />
            )}
          </span>
          <Link
            className="btn"
            to={`/explorer?reference=${a.sources[0]?.provider_id ?? ""}`}
          >
            Raw data
          </Link>
        </div>

        <div className="readouts">
          <Metric2 label="Distance" value={distance(a.distance_m, units)} />
          <Metric2
            label="Moving time"
            value={duration(a.moving_duration_s ?? a.duration_s)}
          />
          <Metric2
            label={isPaceSport(a.sport) ? "Avg pace" : "Avg speed"}
            value={
              isPaceSport(a.sport)
                ? pace(a.avg_speed_mps, units)
                : speed(a.avg_speed_mps, units)
            }
            unit={isPaceSport(a.sport) ? paceLabel(units) : speedLabel(units)}
          />
          <Metric2
            label="Ascent"
            value={elevation(a.elevation_gain_m, units)}
          />
          <Metric2
            label="Avg HR"
            value={round(a.avg_hr, 0)}
            unit="bpm"
            note={a.max_hr ? `Max ${Math.round(a.max_hr)}` : undefined}
          />
          <Metric2 label="Avg power" value={round(a.avg_power_w, 0)} unit="W" />
          <Metric2 label="Calories" value={round(a.calories, 0)} unit="kcal" />
          <Metric2
            label="Training effect"
            value={round(a.aerobic_training_effect, 1)}
            note={
              a.training_effect_label ??
              (a.anaerobic_training_effect
                ? `Anaerobic ${a.anaerobic_training_effect.toFixed(1)}`
                : undefined)
            }
          />
          <Metric2
            label="Garmin load"
            value={round(a.training_load, 0)}
            unit="au"
          />
          <Metric2
            label="Temperature"
            value={temperature(a.avg_temperature_c, units)}
          />
        </div>
      </section>

      {[streams, laps, zones, splits, analysis].filter(q => q.isError).map((q, i) => <section className="panel" key={i}><Failed error={q.error} retry={q.refetch} /></section>)}
      <p className="small muted">Showing measurements recorded for this activity. Details depend on the device, sport and connected provider.</p>
      <div className="grid g-2-1">
        <div className="stack">
          {(streams.isLoading || chartData.charts.length > 0) && <section className="panel">
            <div className="panel-head">
              <h2>Session charts</h2>
              <span className="spacer" />
              <span className="small faint">
                {streams.data?.available
                  ? `${streams.data.point_count.toLocaleString("en-US")} points shown${
                      streams.data.original_point_count &&
                      streams.data.original_point_count >
                        streams.data.point_count
                        ? ` of ${streams.data.original_point_count.toLocaleString("en-US")}`
                        : ""
                    }`
                  : ""}
              </span>
              <span className="small faint">
                Hover moves all charts together
              </span>
            </div>
            {streams.isLoading ? (
              <Loading label="Loading streams" rows={4} />
            ) : !streams.data?.available ? (
              <Unavailable
                reason={
                  streams.data?.unavailable_reason ??
                  "No per-sample data for this activity."
                }
              />
            ) : (
              <div className="panel-body flush">
                {chartData.charts.map((chart) => (
                  <div
                    key={chart.title}
                    style={{ borderTop: "1px solid var(--line)" }}
                  >
                    <div className="row" style={{ padding: "8px 13px 0" }}>
                      <span className="label">{chart.title}</span>
                      <span className="spacer" />
                      <SourceBadge source={chart.source} />
                    </div>
                    <TimeChart
                      data={chartData.rows}
                      series={chart.series}
                      height={chart.height ?? 150}
                      syncId="activity"
                      xKey="x"
                    />
                  </div>
                ))}
              </div>
            )}
          </section>}

          {(laps.isLoading || !!laps.data?.length) && <section className="panel">
            <div className="panel-head">
              <h2>Laps</h2>
              <span className="spacer" />
              <button
                className="ghost sm"
                onClick={() => setShowRaw((v) => !v)}
              >
                {showRaw ? "Hide" : "Show"} provenance
              </button>
            </div>
            {laps.isLoading ? (
              <Loading rows={4} />
            ) : !laps.data?.length ? (
              <Empty
                title="No laps recorded"
                detail="The provider did not return lap splits for this activity."
              />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th className="n">#</th>
                      <th className="n">Distance</th>
                      <th className="n">Time</th>
                      <th className="n">
                        {isPaceSport(a.sport)
                          ? `Pace ${paceLabel(units)}`
                          : speedLabel(units)}
                      </th>
                      {lapHas("avg_hr") && <th className="n">Avg HR</th>}
                      {lapHas("max_hr") && <th className="n">Max HR</th>}
                      {lapHas("avg_power_w") && <th className="n">Power</th>}
                      {lapHas("elevation_gain_m") && <th className="n">Ascent</th>}
                      {lapHas("intensity_type") && <th>Type</th>}
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {laps.data.map((lap) => (
                      <tr key={`${lap.source}-${lap.lap_index}`}>
                        <td className="n">{lap.lap_index}</td>
                        <td className="n">
                          {distance(lap.distance_m, units) ?? "—"}
                        </td>
                        <td className="n">
                          {duration(lap.moving_duration_s ?? lap.duration_s) ??
                            "—"}
                        </td>
                        <td className="n">
                          {isPaceSport(a.sport)
                            ? (pace(lap.avg_speed_mps, units) ?? "—")
                            : (speed(lap.avg_speed_mps, units) ?? "—")}
                        </td>
                        {lapHas("avg_hr") && <td className="n">{round(lap.avg_hr, 0) ?? "—"}</td>}
                        {lapHas("max_hr") && <td className="n">{round(lap.max_hr, 0) ?? "—"}</td>}
                        {lapHas("avg_power_w") && <td className="n">
                          {round(lap.avg_power_w, 0) ?? "—"}
                        </td>}
                        {lapHas("elevation_gain_m") && <td className="n">
                          {elevation(lap.elevation_gain_m, units) ?? "—"}
                        </td>}
                        {lapHas("intensity_type") && <td className="small muted">
                          {lap.intensity_type ?? "—"}
                        </td>}
                        <td>
                          <SourceBadge source={lap.source} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {showRaw && (
              <div className="panel-body small">
                <span className="label">Field provenance</span>
                <div className="row" style={{ gap: 10, marginTop: 6 }}>
                  {Object.entries(a.field_provenance ?? {}).map(
                    ([field, source]) => (
                      <span
                        key={field}
                        className="row small"
                        style={{ gap: 4 }}
                      >
                        <span className="muted">
                          {field.replace(/_/g, " ")}
                        </span>
                        <SourceBadge source={source} />
                      </span>
                    ),
                  )}
                </div>
              </div>
            )}
          </section>}
        </div>
        <div className="stack">
          {showMaps && hasRoute ? (
            <section className="panel">
              <div className="panel-head">
                <h2>Route</h2>
                <span className="spacer" />
                {settings.data?.map_tiles_enabled &&
                  osmLink(
                    streams.data!.channels.lat.data,
                    streams.data!.channels.lng?.data ?? [],
                  ) && (
                    <a
                      className="small"
                      href={osmLink(
                        streams.data!.channels.lat.data,
                        streams.data!.channels.lng?.data ?? [],
                      )!}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      Open area in OSM ↗
                    </a>
                  )}
              </div>
              <div className="panel-body">
                <RouteTrace
                  lat={streams.data!.channels.lat.data}
                  lng={streams.data!.channels.lng?.data ?? []}
                  height={230}
                />
                <p
                  className="small faint"
                  style={{ marginTop: 8, marginBottom: 0 }}
                >
                  Drawn locally from stored GPS samples. No map service is
                  contacted.
                </p>
              </div>
            </section>
          ) : a.has_gps ? (
            <section className="panel">
              <div className="panel-head">
                <h2>Route</h2>
              </div>
              <Empty
                title="Route hidden"
                detail="GPS traces reveal where you live and train, so Paceboard keeps them off by default. Turn on Show route maps in Connections to display them."
                action={
                  <Link className="btn" to="/settings">
                    Open Connections
                  </Link>
                }
              />
            </section>
          ) : null}

          {availableMetrics.length > 0 && <section className="panel"><div className="panel-head"><h2>Derived analysis</h2></div><div className="panel-body"><dl className="kv">{availableMetrics.map(([key, metric]) => <div key={key} style={{ display: "contents" }}><dt>{metricNames[key] ?? key.replace(/_/g, " ")}</dt><dd><MetricValue metric={metric} /></dd></div>)}</dl></div></section>}


          <BestEfforts
            metric={analysis.data?.metrics.best_efforts}
            units={units}
            sport={a.sport}
          />
          <ZonePanel zones={zones.data} loading={zones.isLoading} />
          <SegmentsPanel
            splits={splits.data}
            loading={splits.isLoading}
            units={units}
          />
        </div>
      </div>

          {missing.length > 0 && <details className="panel"><summary className="panel-body">About data coverage</summary><div className="panel-body small muted">{missing.map(([key, metric]) => <p key={key}>{metricNames[key] ?? key.replace(/_/g, " ")}: {metric.unavailable_reason}</p>)}</div></details>}
      <SourceComparison analysis={analysis.data} />
    </>
  );
}

function Metric2({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: string | null;
  unit?: string;
  note?: string;
}) {
  if (value == null) return null;
  return (
    <div className="readout">
      <span className="label">{label}</span>
      {value === null ? (
        <div className="readout-value na">Unavailable</div>
      ) : (
        <div className="readout-value">
          <span>{value}</span>
          {unit && <span className="unit">{unit}</span>}
        </div>
      )}
      {note && <div className="readout-note">{note}</div>}
    </div>
  );
}

function buildChartData(
  streams: StreamSet | undefined,
  units: "metric" | "imperial",
  sport: string,
) {
  const empty = {
    rows: [] as Record<string, any>[],
    charts: [] as {
      title: string;
      series: SeriesSpec[];
      source: string;
      height?: number;
    }[],
  };
  if (!streams?.available) return empty;

  const channels = streams.channels;
  const time = channels.time?.data ?? [];
  const count = Math.max(
    ...Object.values(channels).map((c) => c.data.length),
    0,
  );
  const paceSport = isPaceSport(sport);

  const rows = Array.from({ length: count }, (_, i) => {
    const seconds = typeof time[i] === "number" ? (time[i] as number) : i;
    const velocity = channels.velocity_smooth?.data[i];
    return {
      x: duration(seconds) ?? String(i),
      hr: channels.heartrate?.data[i] ?? null,
      speed:
        typeof velocity === "number"
          ? paceSport
            ? velocity
            : Number(speed(velocity, units))
          : null,
      paceMin:
        typeof velocity === "number" && velocity > 0.2
          ? (units === "imperial" ? 1609.344 : 1000) / velocity / 60
          : null,
      altitude: channels.altitude?.data[i] ?? null,
      cadence: channels.cadence?.data[i] ?? null,
      watts: channels.watts?.data[i] ?? null,
      temp: channels.temp?.data[i] ?? null,
    };
  });

  const charts: {
    title: string;
    series: SeriesSpec[];
    source: string;
    height?: number;
  }[] = [];
  const source =
    channels.heartrate?.source ?? channels.time?.source ?? "garmin";

  if (channels.velocity_smooth) {
    charts.push({
      title: paceSport ? "Pace" : "Speed",
      source: channels.velocity_smooth.source,
      series: paceSport
        ? [
            {
              key: "paceMin",
              name: `Pace`,
              color: CHART.teal,
              unit: `min${paceLabel(units)}`,
              digits: 2,
              type: "line",
            },
          ]
        : [
            {
              key: "speed",
              name: "Speed",
              color: CHART.teal,
              unit: speedLabel(units),
              digits: 1,
              type: "line",
            },
          ],
    });
  }
  if (channels.heartrate) {
    charts.push({
      title: "Heart rate",
      source: channels.heartrate.source,
      series: [
        {
          key: "hr",
          name: "Heart rate",
          color: CHART.rose,
          unit: "bpm",
          digits: 0,
          type: "area",
        },
      ],
    });
  }
  if (channels.altitude) {
    charts.push({
      title: "Elevation",
      source: channels.altitude.source,
      series: [
        {
          key: "altitude",
          name: "Elevation",
          color: CHART.grey,
          unit: "m",
          digits: 0,
          type: "area",
        },
      ],
      height: 120,
    });
  }
  if (channels.watts) {
    charts.push({
      title: "Power",
      source: channels.watts.source,
      series: [
        {
          key: "watts",
          name: "Power",
          color: CHART.amber,
          unit: "W",
          digits: 0,
          type: "area",
        },
      ],
    });
  }
  if (channels.cadence) {
    charts.push({
      title: "Cadence",
      source: channels.cadence.source,
      series: [
        {
          key: "cadence",
          name: "Cadence",
          color: CHART.violet,
          unit: "rpm",
          digits: 0,
          type: "line",
        },
      ],
      height: 120,
    });
  }
  if (channels.temp) {
    charts.push({
      title: "Temperature",
      source: channels.temp.source,
      series: [
        {
          key: "temp",
          name: "Temperature",
          color: CHART.green,
          unit: "°C",
          digits: 0,
          type: "line",
        },
      ],
      height: 110,
    });
  }
  void source;
  return { rows, charts };
}

function BestEfforts({
  metric,
  units,
  sport,
}: {
  metric?: Metric;
  units: "metric" | "imperial";
  sport: string;
}) {
  const points = metric?.detail?.points as Record<string, number> | undefined;
  // "2:08/km" is a strange thing to read about a bike ride.
  const asPace = isPaceSport(sport);
  if (!points || !Object.keys(points).length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Best efforts</h2>
      </div>
      {!points || Object.keys(points).length === 0 ? (
        <Unavailable
          reason={
            metric?.unavailable_reason ??
            "Needs distance and time samples for this activity."
          }
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Distance</th>
                <th className="n">Time</th>
                <th className="n">{asPace ? "Pace" : "Speed"}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(points)
                .sort((a, b) => Number(a[0]) - Number(b[0]))
                .map(([meters, seconds]) => (
                  <tr key={meters}>
                    <td>{distance(Number(meters), units)}</td>
                    <td className="n">{duration(seconds)}</td>
                    <td className="n">
                      {asPace
                        ? `${pace(Number(meters) / seconds, units) ?? "—"}${paceLabel(units)}`
                        : `${speed(Number(meters) / seconds, units) ?? "—"} ${speedLabel(units)}`}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ZonePanel({
  zones,
  loading,
}: {
  zones?: ZoneResponse;
  loading: boolean;
}) {
  const hr = zones?.zones.filter((z) => z.kind === "hr" && z.seconds) ?? [];
  const total = hr.reduce((sum, z) => sum + (z.seconds ?? 0), 0);
  if (!loading && !hr.length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Time in heart-rate zones</h2>
      </div>
      {loading ? (
        <Loading rows={3} />
      ) : !hr.length ? (
        <Unavailable
          reason={
            zones?.unavailable_reason ??
            "The provider did not report zone time for this activity."
          }
        />
      ) : (
        <div className="panel-body">
          <div
            className="zonebar"
            role="img"
            aria-label="Time in heart-rate zones"
          >
            {hr
              .sort((a, b) => a.zone - b.zone)
              .map((z) => (
                <div
                  key={z.zone}
                  className={`zone-${Math.min(5, z.zone)}`}
                  style={{ width: `${((z.seconds ?? 0) / total) * 100}%` }}
                  title={`Zone ${z.zone}: ${duration(z.seconds)}`}
                />
              ))}
          </div>
          <div className="zone-rows" style={{ marginTop: 10 }}>
            {hr.map((z) => (
              <div className="zone-row" key={z.zone}>
                <span className="label">Z{z.zone}</span>
                <div className="zone-track">
                  <div
                    className={`zone-fill zone-${Math.min(5, z.zone)}`}
                    style={{ width: `${((z.seconds ?? 0) / total) * 100}%` }}
                  />
                </div>
                <span className="mono right small">
                  {duration(z.seconds)} ·{" "}
                  {percent(((z.seconds ?? 0) / total) * 100)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

/** Garmin's typed splits: climbs, intervals and run/walk segments.
 *
 * A run/walk session can produce well over a hundred of these, so the panel
 * leads with a per-type summary — which is the number you actually want — and
 * keeps the individual segments in a scrollable list beneath it.
 */
function SegmentsPanel({
  splits,
  loading,
  units,
}: {
  splits?: Split[];
  loading: boolean;
  units: "metric" | "imperial";
}) {
  const typed = (splits ?? []).filter((split) => split.split_type === "typed");

  const summary = useMemo(() => {
    const groups = new Map<
      string,
      { count: number; distance: number; duration: number; ascent: number }
    >();
    for (const split of typed) {
      const key = segmentType(split);
      const bucket = groups.get(key) ?? {
        count: 0,
        distance: 0,
        duration: 0,
        ascent: 0,
      };
      bucket.count += 1;
      bucket.distance += split.distance_m ?? 0;
      bucket.duration += split.duration_s ?? 0;
      bucket.ascent += split.elevation_gain_m ?? 0;
      groups.set(key, bucket);
    }
    return [...groups.entries()].sort((a, b) => b[1].duration - a[1].duration);
  }, [typed]);

  const hasClimbs = typed.some((split) =>
    segmentType(split).toLowerCase().includes("climb"),
  );

  if (!loading && !typed.length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{hasClimbs ? "Climbs and segments" : "Segments"}</h2>
        <span className="spacer" />
        {typed.length > 0 && <SourceBadge source={typed[0].source} />}
      </div>
      {loading ? (
        <Loading rows={3} />
      ) : typed.length === 0 ? (
        <Unavailable reason="Garmin detected no climbs or typed segments in this activity. Detection depends on the sport, the terrain and the watch model." />
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th className="n">Count</th>
                  <th className="n">Distance</th>
                  <th className="n">Time</th>
                  <th className="n">Ascent</th>
                </tr>
              </thead>
              <tbody>
                {summary.map(([type, bucket]) => (
                  <tr key={type}>
                    <td>{type}</td>
                    <td className="n">{bucket.count}</td>
                    <td className="n">
                      {distance(bucket.distance, units) ?? "—"}
                    </td>
                    <td className="n">{duration(bucket.duration) ?? "—"}</td>
                    <td className="n">
                      {bucket.ascent ? elevation(bucket.ascent, units) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary
              className="panel-body small muted"
              style={{ cursor: "pointer" }}
            >
              All {typed.length} segments
            </summary>
            <div className="table-wrap" style={{ maxHeight: 280 }}>
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Type</th>
                    <th className="n">Distance</th>
                    <th className="n">Time</th>
                    <th className="n">Avg HR</th>
                  </tr>
                </thead>
                <tbody>
                  {typed.map((split) => (
                    <tr key={split.split_index}>
                      <td className="n">{split.split_index}</td>
                      <td>
                        {segmentType(split)}
                        {split.details?.climbCategory != null && (
                          <span
                            className="badge neutral"
                            style={{ marginLeft: 6 }}
                          >
                            Cat {String(split.details.climbCategory)}
                          </span>
                        )}
                      </td>
                      <td className="n">
                        {distance(split.distance_m, units) ?? "—"}
                      </td>
                      <td className="n">{duration(split.duration_s) ?? "—"}</td>
                      <td className="n">{round(split.avg_hr, 0) ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}

/** Garmin names these RWD_RUN, CLIMB_ACTIVE, INTERVAL_ACTIVE; make them readable. */
function segmentType(split: Split): string {
  const raw = String(
    split.details?.type ?? split.details?.splitType ?? "Segment",
  );
  return raw
    .replace(/^RWD_/, "")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function SourceComparison({ analysis }: { analysis?: Analysis }) {
  const comparison = analysis?.source_comparison;
  if (!comparison?.available || !comparison.fields.length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Where the providers disagree</h2>
        <span className="spacer" />
        <span className="small faint">
          Both records are kept; the chosen column is what Paceboard shows
          above.
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th className="n">Garmin</th>
              <th className="n">Strava</th>
              <th className="n">Difference</th>
              <th>Paceboard uses</th>
            </tr>
          </thead>
          <tbody>
            {comparison.fields.map((row) => (
              <tr key={row.field}>
                <td>{row.field.replace(/_/g, " ")}</td>
                <td className="n">
                  {row.values.garmin != null
                    ? Number(row.values.garmin).toFixed(1)
                    : "—"}
                </td>
                <td className="n">
                  {row.values.strava != null
                    ? Number(row.values.strava).toFixed(1)
                    : "—"}
                </td>
                <td className="n">
                  {row.difference_pct != null ? `${row.difference_pct}%` : "—"}
                </td>
                <td>
                  {row.chosen_source ? (
                    <SourceBadge source={row.chosen_source} />
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
