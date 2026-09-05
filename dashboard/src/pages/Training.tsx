/**
 * Training — load, intensity distribution, volume and the performance metrics
 * Garmin derives (VO2 max, FTP, thresholds, scores) alongside personal records.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type LoadSeries, type Metric, type RollingTotal, type VolumeBucket, type ZoneTotals } from "../lib/api";
import { useUnits } from "../lib/hooks";
import { dayLabel, distance, duration, elevation, hours, percent, round } from "../lib/format";
import { CHART, ChartFrame, StackedBars, TimeChart, type SeriesSpec } from "../components/Charts";
import { buildWeeklyVolume } from "../components/volume";
import { Empty, Failed, Loading, Unavailable } from "../components/States";
import { Readout, ReadoutRail } from "../components/Readout";
import { SourceBadge } from "../components/SourceBadge";

const WINDOWS = [
  { days: 42, label: "6 weeks" },
  { days: 90, label: "90 days" },
  { days: 365, label: "1 year" },
];

interface PerformanceResponse {
  metrics: Record<string, { day: string; value: number | null; display: string | null; units: string | null; source: string }[]>;
  available: boolean;
  unavailable_reason: string | null;
}

interface RecordRow {
  record: string; source: string; day: string | null;
  value: number | null; display: string | null; units: string | null;
}

export function Training() {
  const units = useUnits();
  const [days, setDays] = useState(90);

  const load = useQuery({ queryKey: ["load", days], queryFn: () => api.get<LoadSeries>("/training/load", { days }) });
  const volume = useQuery({ queryKey: ["volume", days], queryFn: () => api.get<VolumeBucket[]>("/training/volume", { days }) });
  const zones = useQuery({ queryKey: ["train-zones", days], queryFn: () => api.get<ZoneTotals>("/training/zones", { days }) });
  const perf = useQuery({ queryKey: ["performance", days], queryFn: () => api.get<PerformanceResponse>("/training/performance", { days }) });
  const rolling = useQuery({ queryKey: ["rolling"], queryFn: () => api.get<RollingTotal[]>("/training/rolling") });
  const monotony = useQuery({ queryKey: ["monotony"], queryFn: () => api.get<Record<string, Metric>>("/training/monotony") });
  const records = useQuery({ queryKey: ["records"], queryFn: () => api.get<RecordRow[]>("/training/records") });

  if (load.isLoading) return <section className="panel"><Loading label="Loading training data" rows={6} /></section>;
  if (load.isError) return <section className="panel"><Failed error={load.error} retry={load.refetch} /></section>;

  const series = load.data!;
  const rows = series.days.map((day, i) => ({
    x: dayLabel(day) ?? day,
    load: series.daily_load[i],
    ctl: series.ctl[i],
    atl: series.atl[i],
    tsb: series.tsb[i],
    gAcute: series.garmin_acute[i],
    gChronic: series.garmin_chronic[i],
    gAcwr: series.garmin_acwr[i],
  }));

  const hasGarminLoad = series.garmin_chronic.some((v) => v !== null);
  const volumeChart = buildWeeklyVolume(volume.data ?? []);
  const distribution = zones.data?.distribution;

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h1>Training</h1>
          <span className="spacer" />
          <div className="segmented" role="group" aria-label="Time window">
            {WINDOWS.map((w) => (
              <button key={w.days} aria-pressed={days === w.days} onClick={() => setDays(w.days)}>
                {w.label}
              </button>
            ))}
          </div>
        </div>
        <ReadoutRail>
          <Readout label="Fitness (CTL)" value={round(series.ctl.at(-1), 1)} unit="au" note="42-day load average" />
          <Readout label="Fatigue (ATL)" value={round(series.atl.at(-1), 1)} unit="au" note="7-day load average" />
          <Readout
            label="Form (TSB)"
            value={round(series.tsb.at(-1), 1)}
            unit="au"
            note={formNote(series.tsb.at(-1))}
          />
          <Readout
            label="Weekly load"
            value={monotony.data?.weekly_load?.value != null ? round(monotony.data.weekly_load.value, 0) : null}
            unit="au"
            unavailableReason={monotony.data?.weekly_load?.unavailable_reason}
          />
          <Readout
            label="Monotony"
            value={monotony.data?.monotony?.value != null ? monotony.data.monotony.value.toFixed(2) : null}
            note="Load sameness across the week"
            unavailableReason={monotony.data?.monotony?.unavailable_reason}
          />
          <Readout
            label="Strain"
            value={monotony.data?.strain?.value != null ? round(monotony.data.strain.value, 0) : null}
            unit="au"
            note="Weekly load × monotony"
            unavailableReason={monotony.data?.strain?.unavailable_reason}
          />
        </ReadoutRail>
      </section>

      <ChartFrame
        title="Performance management chart"
        right={<SourceBadge source="paceboard" title="Computed by Paceboard" />}
        note={series.provider_note}
      >
        <TimeChart
          data={rows}
          height={250}
          zeroLine
          syncId="training"
          series={[
            { key: "load", name: "Daily load", color: CHART.grey, unit: "au", digits: 0, type: "bar" },
            { key: "ctl", name: "Fitness (CTL)", color: CHART.teal, unit: "au", digits: 1, type: "line" },
            { key: "atl", name: "Fatigue (ATL)", color: CHART.amber, unit: "au", digits: 1, type: "line" },
            { key: "tsb", name: "Form (TSB)", color: CHART.violet, unit: "au", digits: 1, type: "line", dashed: true },
          ]}
        />
      </ChartFrame>

      {hasGarminLoad && (
        <ChartFrame
          title="Garmin acute and chronic load"
          right={<SourceBadge source="garmin" />}
          note="Garmin's own load figures, in Garmin's units. Shown separately because the two scales are not comparable."
        >
          <TimeChart
            data={rows}
            height={190}
            rightAxis
            series={[
              { key: "gAcute", name: "Acute load", color: CHART.amber, unit: "", digits: 0, type: "line" },
              { key: "gChronic", name: "Chronic load", color: CHART.teal, unit: "", digits: 0, type: "line" },
              { key: "gAcwr", name: "Acute:chronic", color: CHART.violet, unit: "ratio", digits: 2, type: "line", axis: "right", dashed: true },
            ]}
          />
        </ChartFrame>
      )}

      <div className="grid g-2-1">
        <ChartFrame title="Weekly volume by sport" note="Minutes of moving time per ISO week.">
          {volumeChart.data.length ? (
            <StackedBars data={volumeChart.data} series={volumeChart.series} height={210} />
          ) : (
            <Empty title="No activities in this window" detail="Widen the window or run a backfill." />
          )}
        </ChartFrame>

        <section className="panel">
          <div className="panel-head"><h2>Intensity distribution</h2></div>
          {zones.isLoading ? <Loading rows={3} /> : !zones.data?.available ? (
            <Unavailable reason={zones.data?.unavailable_reason} />
          ) : (
            <div className="panel-body">
              <div className="zonebar" role="img" aria-label="Time in heart-rate zones across the window">
                {Object.entries(zones.data.zones).sort((a, b) => Number(a[0]) - Number(b[0])).map(([zone, seconds]) => {
                  const total = Object.values(zones.data!.zones).reduce((s, v) => s + v, 0);
                  return (
                    <div
                      key={zone}
                      className={`zone-${Math.min(5, Number(zone))}`}
                      style={{ width: `${(seconds / total) * 100}%` }}
                      title={`Zone ${zone}: ${duration(seconds)}`}
                    />
                  );
                })}
              </div>
              <div className="zone-rows" style={{ marginTop: 12 }}>
                {Object.entries(zones.data.zones).sort((a, b) => Number(a[0]) - Number(b[0])).map(([zone, seconds]) => (
                  <div className="zone-row" key={zone}>
                    <span className="label">Z{zone}</span>
                    <div className="zone-track">
                      <div className={`zone-fill zone-${Math.min(5, Number(zone))}`} style={{ width: `${zones.data!.percent?.[zone] ?? 0}%` }} />
                    </div>
                    <span className="mono right small">{duration(seconds)}</span>
                  </div>
                ))}
              </div>
              {distribution && (
                <dl className="kv" style={{ marginTop: 14 }}>
                  <dt>Easy (Z1–2)</dt><dd>{percent(distribution.easy)}</dd>
                  <dt>Moderate (Z3)</dt><dd>{percent(distribution.moderate)}</dd>
                  <dt>Hard (Z4–5)</dt><dd>{percent(distribution.hard)}</dd>
                </dl>
              )}
            </div>
          )}
        </section>
      </div>

      <div className="grid g2">
        <PerformancePanel perf={perf.data} loading={perf.isLoading} />

        <section className="panel">
          <div className="panel-head"><h2>Rolling totals</h2></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Window</th>
                  <th className="n">Activities</th>
                  <th className="n">Distance</th>
                  <th className="n">Time</th>
                  <th className="n">Ascent</th>
                </tr>
              </thead>
              <tbody>
                {(rolling.data ?? []).map((bucket) => (
                  <tr key={bucket.days}>
                    <td>Last {bucket.days} days</td>
                    <td className="n">{bucket.count}</td>
                    <td className="n">{distance(bucket.distance_m, units) ?? "—"}</td>
                    <td className="n">{hours(bucket.duration_s) ?? "—"}</td>
                    <td className="n">{elevation(bucket.elevation_m, units) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Personal records</h2>
          <span className="spacer" />
          <SourceBadge source="garmin" />
        </div>
        {records.isLoading ? <Loading rows={3} /> : !records.data?.length ? (
          <Unavailable reason="No personal records have been ingested. They come from Garmin's records endpoint during an account sync." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Record</th><th className="n">Value</th><th>Set</th></tr></thead>
              <tbody>
                {records.data.map((row) => (
                  <tr key={`${row.record}-${row.day}`}>
                    <td>{row.record.replace(/_/g, " ")}</td>
                    <td className="n">{row.display ?? round(row.value, 1) ?? "—"}</td>
                    <td className="mono small">{row.day ?? <span className="na-inline">not reported</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

const METRIC_LABELS: Record<string, { label: string; color: string; digits: number }> = {
  vo2max: { label: "VO₂ max", color: CHART.teal, digits: 1 },
  "vo2max:running": { label: "VO₂ max (run)", color: CHART.teal, digits: 1 },
  "vo2max:cycling": { label: "VO₂ max (ride)", color: CHART.amber, digits: 1 },
  "ftp:ride": { label: "FTP", color: CHART.amber, digits: 0 },
  lactate_threshold_hr: { label: "Lactate threshold HR", color: CHART.rose, digits: 0 },
  lactate_threshold_speed: { label: "Lactate threshold speed", color: CHART.violet, digits: 2 },
  endurance_score: { label: "Endurance score", color: CHART.green, digits: 0 },
  hill_score: { label: "Hill score", color: CHART.violet, digits: 0 },
  "running_tolerance:run": { label: "Running tolerance", color: CHART.teal, digits: 0 },
  heat_acclimation: { label: "Heat acclimation", color: CHART.rose, digits: 0 },
  altitude_acclimation: { label: "Altitude acclimation", color: CHART.grey, digits: 0 },
  fitness_age: { label: "Fitness age", color: CHART.grey, digits: 1 },
};

function PerformancePanel({ perf, loading }: { perf?: PerformanceResponse; loading: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  if (loading) return <section className="panel"><Loading rows={4} /></section>;
  if (!perf?.available) {
    return (
      <section className="panel">
        <div className="panel-head"><h2>Performance metrics</h2></div>
        <Unavailable reason={perf?.unavailable_reason} />
      </section>
    );
  }

  const known = Object.keys(perf.metrics).filter((key) => METRIC_LABELS[key] && perf.metrics[key].some((p) => p.value !== null));
  const active = selected && known.includes(selected) ? selected : known[0];
  if (!active) {
    return (
      <section className="panel">
        <div className="panel-head"><h2>Performance metrics</h2></div>
        <Unavailable reason="Garmin returned no charted performance metric for this window. Race predictions and PRs are listed separately." />
      </section>
    );
  }

  const meta = METRIC_LABELS[active];
  const rows = perf.metrics[active].map((point) => ({ x: dayLabel(point.day) ?? point.day, v: point.value }));
  const spec: SeriesSpec[] = [{ key: "v", name: meta.label, color: meta.color, digits: meta.digits, type: "line" }];
  const predictions = Object.keys(perf.metrics).filter((k) => k.startsWith("race_prediction_"));

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Performance metrics</h2>
        <span className="spacer" />
        <select value={active} onChange={(e) => setSelected(e.target.value)} aria-label="Metric">
          {known.map((key) => (
            <option key={key} value={key}>{METRIC_LABELS[key].label}</option>
          ))}
        </select>
      </div>
      <div className="panel-body flush">
        <TimeChart data={rows} series={spec} height={200} />
      </div>
      {predictions.length > 0 && (
        <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
          <span className="label">Race predictions</span>
          <div className="row" style={{ gap: 18, marginTop: 6 }}>
            {predictions.map((key) => {
              const latest = perf.metrics[key].at(-1);
              return (
                <div key={key}>
                  <div className="label">{key.replace("race_prediction_", "").replace(/:.*$/, "").replace(/_/g, " ")}</div>
                  <div className="mono" style={{ fontSize: 15 }}>{latest?.display ?? duration(latest?.value ?? null) ?? "—"}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function formNote(tsb: number | null | undefined): string {
  if (tsb == null) return "";
  if (tsb < -25) return "Deep fatigue";
  if (tsb < -10) return "Building";
  if (tsb < 5) return "Balanced";
  if (tsb < 20) return "Fresh";
  return "Very fresh — or detraining";
}
