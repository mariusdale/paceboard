/**
 * Recovery — sleep, HRV, resting heart rate, stress and Body Battery, each shown
 * against its own rolling baseline. A single night means little; the baseline is
 * what makes a number readable.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Metric, type RecoverySeries } from "../lib/api";
import { dayLabel, hours, round } from "../lib/format";
import { CHART, ChartFrame, StackedBars, TimeChart } from "../components/Charts";
import { Empty, Failed, Loading, Unavailable } from "../components/States";
import { Readout, ReadoutRail } from "../components/Readout";
import { SourceBadge } from "../components/SourceBadge";

const WINDOWS = [
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 180, label: "6 months" },
];

interface Correlation {
  x: string; y: string; r: number | null; n: number;
  available: boolean; unavailable_reason?: string; note?: string;
}

export function Recovery() {
  const [days, setDays] = useState(90);

  const series = useQuery({
    queryKey: ["recovery", days],
    queryFn: () => api.get<RecoverySeries>("/health/recovery", { days }),
  });
  const summary = useQuery({
    queryKey: ["recovery-summary"],
    queryFn: () => api.get<Record<string, Metric>>("/health/recovery/summary"),
  });
  const correlations = useQuery({
    queryKey: ["correlations", days],
    queryFn: () => api.get<Correlation[]>("/health/correlations", { days: Math.max(14, days) }),
  });

  if (series.isLoading) return <section className="panel"><Loading label="Loading recovery data" rows={6} /></section>;
  if (series.isError) return <section className="panel"><Failed error={series.error} retry={series.refetch} /></section>;

  const data = series.data!;
  const hasAny = data.sleep_seconds.some((v) => v !== null) || data.hrv_ms.some((v) => v !== null);

  const rows = data.days.map((day, i) => ({
    x: dayLabel(day) ?? day,
    sleepHours: data.sleep_seconds[i] != null ? Number((data.sleep_seconds[i]! / 3600).toFixed(2)) : null,
    sleepScore: data.sleep_score[i],
    deep: data.sleep_stages[i]?.deep != null ? Number((data.sleep_stages[i]!.deep! / 3600).toFixed(2)) : 0,
    light: data.sleep_stages[i]?.light != null ? Number((data.sleep_stages[i]!.light! / 3600).toFixed(2)) : 0,
    rem: data.sleep_stages[i]?.rem != null ? Number((data.sleep_stages[i]!.rem! / 3600).toFixed(2)) : 0,
    awake: data.sleep_stages[i]?.awake != null ? Number((data.sleep_stages[i]!.awake! / 3600).toFixed(2)) : 0,
    hrv: data.hrv_ms[i],
    hrvBase: data.hrv_baseline[i],
    rhr: data.resting_hr[i],
    rhrBase: data.resting_hr_baseline[i],
    stress: data.avg_stress[i],
    bbHigh: data.body_battery_high[i],
    bbLow: data.body_battery_low[i],
    charged: data.body_battery_charged[i],
    drained: data.body_battery_drained[i] != null ? -Math.abs(data.body_battery_drained[i]!) : null,
    respiration: data.respiration[i],
    spo2: data.spo2[i],
    readiness: data.training_readiness[i],
  }));

  if (!hasAny) {
    return (
      <section className="panel">
        <Empty
          title="No recovery data stored"
          detail="Paceboard has not received sleep or HRV records for this window. Run a backfill from Connections, or check that your watch syncs those metrics to Garmin Connect."
        />
      </section>
    );
  }

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h1>Recovery</h1>
          <span className="spacer" />
          <SourceBadge source="garmin" />
          <div className="segmented" role="group" aria-label="Time window">
            {WINDOWS.map((w) => (
              <button key={w.days} aria-pressed={days === w.days} onClick={() => setDays(w.days)}>
                {w.label}
              </button>
            ))}
          </div>
        </div>
        <ReadoutRail>
          <Readout
            label="HRV last night"
            value={summary.data?.hrv_latest?.value != null ? String(Math.round(summary.data.hrv_latest.value)) : null}
            unit="ms"
            raw={summary.data?.hrv_latest?.value ?? null}
            baseline={summary.data?.hrv_baseline?.value ?? null}
            unavailableReason={summary.data?.hrv_latest?.unavailable_reason}
          />
          <Readout
            label="HRV baseline"
            value={summary.data?.hrv_baseline?.value != null ? String(Math.round(summary.data.hrv_baseline.value)) : null}
            unit="ms"
            note="7-night trailing mean"
            unavailableReason={summary.data?.hrv_baseline?.unavailable_reason}
          />
          <Readout
            label="Deviation"
            value={summary.data?.hrv_deviation?.value != null ? `${summary.data.hrv_deviation.value > 0 ? "+" : ""}${summary.data.hrv_deviation.value.toFixed(1)}` : null}
            unit="%"
            note="Against your own baseline"
            unavailableReason={summary.data?.hrv_deviation?.unavailable_reason}
          />
          <Readout
            label="Sleep debt"
            value={summary.data?.sleep_debt_7d?.value != null ? summary.data.sleep_debt_7d.value.toFixed(1) : null}
            unit="h"
            note="Shortfall vs 8 h over 7 nights"
            unavailableReason={summary.data?.sleep_debt_7d?.unavailable_reason}
          />
          <Readout
            label="Sleep consistency"
            value={summary.data?.sleep_consistency_14d?.value != null ? String(Math.round(summary.data.sleep_consistency_14d.value)) : null}
            unit="/100"
            note={bedtimeNote(summary.data?.sleep_consistency_14d)}
            unavailableReason={summary.data?.sleep_consistency_14d?.unavailable_reason}
          />
        </ReadoutRail>
      </section>

      <div className="grid g2">
        <ChartFrame title="Sleep stages" note="Stacked hours per night as reported by Garmin.">
          <StackedBars
            data={rows}
            height={210}
            series={[
              { key: "deep", name: "Deep", color: "#1f4f8f", unit: "h", digits: 2 },
              { key: "light", name: "Light", color: CHART.teal, unit: "h", digits: 2 },
              { key: "rem", name: "REM", color: CHART.violet, unit: "h", digits: 2 },
              { key: "awake", name: "Awake", color: CHART.grey, unit: "h", digits: 2 },
            ]}
          />
        </ChartFrame>

        <ChartFrame title="Sleep duration and score">
          <TimeChart
            data={rows}
            height={210}
            syncId="recovery"
            rightAxis
            series={[
              { key: "sleepHours", name: "Sleep", color: CHART.teal, unit: "h", digits: 2, type: "area" },
              { key: "sleepScore", name: "Sleep score", color: CHART.violet, unit: "/100", digits: 0, type: "line", axis: "right" },
            ]}
          />
        </ChartFrame>

        <ChartFrame title="HRV and baseline" note="Baseline is a 7-night trailing mean; it only appears once 7 nights exist.">
          <TimeChart
            data={rows}
            height={200}
            syncId="recovery"
            series={[
              { key: "hrv", name: "Overnight HRV", color: CHART.teal, unit: "ms", digits: 0, type: "line" },
              { key: "hrvBase", name: "Baseline", color: CHART.grey, unit: "ms", digits: 1, type: "line", dashed: true },
            ]}
          />
        </ChartFrame>

        <ChartFrame title="Resting heart rate" note="Baseline is a 28-day trailing mean.">
          <TimeChart
            data={rows}
            height={200}
            syncId="recovery"
            series={[
              { key: "rhr", name: "Resting HR", color: CHART.rose, unit: "bpm", digits: 0, type: "line" },
              { key: "rhrBase", name: "Baseline", color: CHART.grey, unit: "bpm", digits: 1, type: "line", dashed: true },
            ]}
          />
        </ChartFrame>

        <ChartFrame title="Body Battery">
          <TimeChart
            data={rows}
            height={200}
            syncId="recovery"
            zeroLine
            series={[
              { key: "bbHigh", name: "Daily high", color: CHART.green, unit: "", digits: 0, type: "line" },
              { key: "bbLow", name: "Daily low", color: CHART.amber, unit: "", digits: 0, type: "line" },
              { key: "charged", name: "Charged", color: CHART.teal, unit: "", digits: 0, type: "bar" },
              { key: "drained", name: "Drained", color: CHART.grey, unit: "", digits: 0, type: "bar" },
            ]}
          />
        </ChartFrame>

        <ChartFrame title="Stress, respiration and readiness">
          <TimeChart
            data={rows}
            height={200}
            syncId="recovery"
            rightAxis
            series={[
              { key: "stress", name: "Avg stress", color: CHART.amber, unit: "", digits: 0, type: "area" },
              { key: "readiness", name: "Training readiness", color: CHART.violet, unit: "/100", digits: 0, type: "line" },
              { key: "respiration", name: "Respiration", color: CHART.teal, unit: "br/min", digits: 1, type: "line", axis: "right" },
            ]}
          />
        </ChartFrame>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Recovery against load</h2>
          <span className="spacer" />
          <span className="small faint">
            Pearson correlation over your own history. Association, not cause.
          </span>
        </div>
        {correlations.isLoading ? <Loading rows={3} /> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Relationship</th>
                  <th className="n">r</th>
                  <th className="n">Days compared</th>
                  <th>Reading</th>
                </tr>
              </thead>
              <tbody>
                {(correlations.data ?? []).map((row) => (
                  <tr key={`${row.x}-${row.y}`}>
                    <td>{humanize(row.x)} → {humanize(row.y)}</td>
                    <td className="n">{row.r != null ? row.r.toFixed(2) : "—"}</td>
                    <td className="n">{row.n || "—"}</td>
                    <td className="small muted">
                      {row.available ? strength(row.r!) : row.unavailable_reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <SleepTable rows={rows} />
    </>
  );
}

function SleepTable({ rows }: { rows: Record<string, any>[] }) {
  const recent = rows.slice(-14).reverse();
  if (!recent.length) return <Unavailable reason="No nights in this window." />;
  return (
    <section className="panel">
      <div className="panel-head"><h2>Last 14 nights</h2></div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Night</th>
              <th className="n">Total</th>
              <th className="n">Deep</th>
              <th className="n">REM</th>
              <th className="n">Awake</th>
              <th className="n">Score</th>
              <th className="n">HRV</th>
              <th className="n">Resting HR</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((row) => (
              <tr key={row.x}>
                <td>{row.x}</td>
                <td className="n">{row.sleepHours != null ? hours(row.sleepHours * 3600) : "—"}</td>
                <td className="n">{row.deep ? `${row.deep.toFixed(1)}h` : "—"}</td>
                <td className="n">{row.rem ? `${row.rem.toFixed(1)}h` : "—"}</td>
                <td className="n">{row.awake ? `${(row.awake * 60).toFixed(0)}m` : "—"}</td>
                <td className="n">{row.sleepScore ?? "—"}</td>
                <td className="n">{round(row.hrv, 0) ?? "—"}</td>
                <td className="n">{round(row.rhr, 0) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const LABELS: Record<string, string> = {
  sleep_seconds: "Sleep duration",
  next_day_readiness: "Next-day readiness",
  daily_load: "Training load",
  next_day_hrv: "Next-day HRV",
  next_day_resting_hr: "Next-day resting HR",
  avg_stress: "Average stress",
  sleep_score: "Sleep score",
  body_battery_high: "Body Battery high",
  training_readiness: "Training readiness",
};

/** A bare "0/100" is not actionable; say how much the bedtime actually moves. */
function bedtimeNote(metric?: Metric): string {
  const spread = metric?.detail?.bedtime_spread_minutes as number | undefined;
  if (spread == null) return "Bedtime regularity, 14 nights";
  const hours = Math.floor(spread / 60);
  const minutes = Math.round(spread % 60);
  const span = hours > 0 ? `${hours}h ${String(minutes).padStart(2, "0")}m` : `${minutes}m`;
  return `Bedtime varies by ±${span}`;
}

function humanize(key: string): string {
  return LABELS[key] ?? key.replace(/_/g, " ");
}

function strength(r: number): string {
  const magnitude = Math.abs(r);
  const direction = r > 0 ? "positive" : "negative";
  if (magnitude < 0.2) return "no meaningful relationship";
  if (magnitude < 0.4) return `weak ${direction}`;
  if (magnitude < 0.6) return `moderate ${direction}`;
  return `strong ${direction}`;
}
