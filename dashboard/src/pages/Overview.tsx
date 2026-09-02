/**
 * Overview — the daily read.
 *
 * Ordered by what the athlete needs first thing: how recovered am I, how much
 * load is on me, what have I actually done, and is the data I am looking at
 * current.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Overview as OverviewData, type Status } from "../lib/api";
import { useStatus, useTimezone, useUnits } from "../lib/hooks";
import {
  dayLabel, distance, duration, elevation, hours, integer, localTime,
  relativeAge, round, sportLabel,
} from "../lib/format";
import { Readout, ReadoutRail } from "../components/Readout";
import { CHART, ChartFrame, TimeChart, StackedBars, type SeriesSpec } from "../components/Charts";
import { buildWeeklyVolume } from "../components/volume";
import { Empty, Failed, Loading, StaleMark } from "../components/States";
import { SourceBadge, StatusBadge } from "../components/SourceBadge";

const FRESHNESS_THRESHOLD = 3 * 3600;

export function Overview() {
  const units = useUnits();
  const timezone = useTimezone();
  const status = useStatus();
  const query = useQuery({
    queryKey: ["overview"],
    queryFn: () => api.get<OverviewData>("/overview"),
    refetchInterval: 60_000,
  });

  if (query.isLoading) {
    return (
      <section className="panel">
        <Loading label="Loading overview" rows={5} />
      </section>
    );
  }
  if (query.isError) return <section className="panel"><Failed error={query.error} retry={query.refetch} /></section>;

  const data = query.data!;
  const empty = (status.data?.counts.activities ?? 0) === 0 && (status.data?.counts.daily_health ?? 0) === 0;

  if (empty) {
    return (
      <section className="panel">
        <Empty
          title="No data yet"
          detail="Paceboard has not stored anything from Garmin or Strava. Run a backfill from Connections to pull your history, or press Sync now for the last few days."
          action={<Link className="btn" to="/settings">Open Connections</Link>}
        />
      </section>
    );
  }

  const today = data.today;
  const night = data.last_night;
  const base = data.baselines;
  const formData = data.form.days.map((day, i) => ({
    x: dayLabel(day) ?? day,
    ctl: data.form.ctl[i],
    atl: data.form.atl[i],
    tsb: data.form.tsb[i],
    load: data.form.daily_load[i],
  }));

  const formSeries: SeriesSpec[] = [
    { key: "load", name: "Daily load", color: CHART.grey, type: "bar", unit: "au", digits: 0 },
    { key: "ctl", name: "Fitness (CTL)", color: CHART.teal, type: "line", unit: "au" },
    { key: "atl", name: "Fatigue (ATL)", color: CHART.amber, type: "line", unit: "au" },
    { key: "tsb", name: "Form (TSB)", color: CHART.violet, type: "line", unit: "au", dashed: true },
  ];

  const volume = buildWeeklyVolume(data.weekly_volume);

  return (
    <>
      <FreshnessStrip status={status.data} timezone={timezone} />

      <section className="panel">
        <div className="panel-head">
          <h2>Today against your own baseline</h2>
          <span className="spacer" />
          <span className="small faint">
            {today.day ? `${today.is_today ? "Today" : "Latest day with data"} · ${today.day}` : "No daily record"}
          </span>
          <SourceBadge source="garmin" />
        </div>
        <ReadoutRail>
          <Readout
            label="Training readiness"
            value={today.training_readiness != null ? String(today.training_readiness) : null}
            unit="/100"
            raw={today.training_readiness}
            baseline={base.training_readiness}
            note={today.readiness_level ?? undefined}
            unavailableReason="Your device did not report training readiness for this day"
          />
          <Readout
            label="Body Battery high"
            value={today.body_battery_high != null ? String(today.body_battery_high) : null}
            unit="/100"
            raw={today.body_battery_high}
            baseline={base.body_battery_high}
            note={today.body_battery_low != null ? `Low ${today.body_battery_low}` : undefined}
            unavailableReason="No Body Battery recorded for this day"
          />
          <Readout
            label="Resting HR"
            value={today.resting_hr != null ? String(today.resting_hr) : null}
            unit="bpm"
            raw={today.resting_hr}
            baseline={base.resting_hr}
            lowerIsBetter
            unavailableReason="No resting heart rate recorded for this day"
          />
          <Readout
            label="Sleep"
            value={hours(night.total_sleep_s)}
            raw={night.total_sleep_s}
            baseline={base.sleep_seconds}
            note={night.sleep_score != null ? `Score ${night.sleep_score}` : undefined}
            unavailableReason="No sleep recorded for last night"
          />
          <Readout
            label="Avg stress"
            value={today.avg_stress != null ? String(today.avg_stress) : null}
            raw={today.avg_stress}
            baseline={base.avg_stress}
            lowerIsBetter
            unavailableReason="No stress data recorded for this day"
          />
          <Readout
            label="Steps"
            value={integer(today.steps)}
            raw={today.steps}
            baseline={base.steps}
            note={today.step_goal ? `Goal ${integer(today.step_goal)}` : undefined}
            unavailableReason="No step count recorded for this day"
          />
        </ReadoutRail>
      </section>

      <div className="grid g-2-1">
        <ChartFrame
          title="Training load and form"
          right={
            <span className="row small">
              <span className="faint">CTL</span>
              <strong className="mono">{round(data.form.latest_ctl, 1) ?? "—"}</strong>
              <span className="faint">ATL</span>
              <strong className="mono">{round(data.form.latest_atl, 1) ?? "—"}</strong>
              <span className="faint">TSB</span>
              <strong className="mono" style={{ color: (data.form.latest_tsb ?? 0) < -10 ? "var(--amber)" : undefined }}>
                {round(data.form.latest_tsb, 1) ?? "—"}
              </strong>
            </span>
          }
          note="Computed by Paceboard from per-activity Banister TRIMP, not taken from Garmin. Negative form means fatigue currently exceeds fitness."
        >
          <TimeChart data={formData} series={formSeries} height={224} zeroLine syncId="overview" />
        </ChartFrame>

        <section className="panel">
          <div className="panel-head"><h2>Rolling totals</h2></div>
          <div className="panel-body stack">
            {data.rolling.map((bucket) => (
              <div key={bucket.days}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="label">Last {bucket.days} days</span>
                  <span className="mono small">{bucket.count} {bucket.count === 1 ? "activity" : "activities"}</span>
                </div>
                <dl className="kv" style={{ marginTop: 4 }}>
                  <dt>Distance</dt><dd>{distance(bucket.distance_m, units) ?? "—"}</dd>
                  <dt>Time</dt><dd>{hours(bucket.duration_s) ?? "—"}</dd>
                  <dt>Ascent</dt><dd>{elevation(bucket.elevation_m, units) ?? "—"}</dd>
                </dl>
              </div>
            ))}
            <div style={{ borderTop: "1px solid var(--line)", paddingTop: 9 }}>
              <span className="label">Consistency · {data.consistency.window_days} days</span>
              <dl className="kv" style={{ marginTop: 4 }}>
                <dt>Active days</dt>
                <dd>{data.consistency.active_days} ({Math.round(data.consistency.active_ratio * 100)}%)</dd>
                <dt>Current streak</dt><dd>{data.consistency.current_streak}</dd>
                <dt>Longest streak</dt><dd>{data.consistency.longest_streak}</dd>
              </dl>
            </div>
          </div>
        </section>
      </div>

      <div className="grid g-1-2">
        <ChartFrame title="Weekly volume by sport" note="Moving time where the provider reports it, otherwise elapsed.">
          {volume.data.length ? (
            <StackedBars data={volume.data} series={volume.series} height={210} />
          ) : (
            <Empty title="No activities in the last 8 weeks" detail="Sync or widen your backfill window to populate this chart." />
          )}
        </ChartFrame>

        <section className="panel">
          <div className="panel-head">
            <h2>Recent activities</h2>
            <span className="spacer" />
            <Link to="/activities" className="small">All activities →</Link>
          </div>
          <div className="table-wrap">
            {data.recent_activities.length === 0 ? (
              <Empty title="No activities stored" detail="Nothing has been ingested yet for this account." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Activity</th>
                    <th>Sport</th>
                    <th className="n">Distance</th>
                    <th className="n">Time</th>
                    <th className="n">Avg HR</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_activities.map((activity) => (
                    <tr key={activity.id}>
                      <td>
                        <Link to={`/activities/${activity.id}`}>{activity.name ?? "Untitled activity"}</Link>
                        <div className="small faint mono">
                          {localTime(activity.start_time_utc, timezone)}
                        </div>
                      </td>
                      <td>{sportLabel(activity.sport)}</td>
                      <td className="n">{distance(activity.distance_m, units) ?? "—"}</td>
                      <td className="n">{duration(activity.moving_duration_s ?? activity.duration_s) ?? "—"}</td>
                      <td className="n">{round(activity.avg_hr, 0) ?? "—"}</td>
                      <td>
                        <span className="row" style={{ gap: 4 }}>
                          {activity.sources.map((s) => <SourceBadge key={s.source} source={s.source} />)}
                          {activity.duplicate_state === "merged" && <StatusBadge status="merged" label="merged" />}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>
    </>
  );
}

function FreshnessStrip({ status, timezone }: { status?: Status; timezone: string }) {
  if (!status?.freshness?.length) return null;
  const stale = status.freshness.filter((f) => (f.age_seconds ?? 0) > FRESHNESS_THRESHOLD);
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Provider freshness</h2>
        <span className="spacer" />
        {stale.length > 0 && (
          <StaleMark ageSeconds={Math.max(...stale.map((f) => f.age_seconds ?? 0))} thresholdSeconds={FRESHNESS_THRESHOLD} />
        )}
      </div>
      <div className="panel-body row" style={{ gap: 18 }}>
        {status.freshness.map((entry) => (
          <div key={`${entry.provider}:${entry.category}`} className="row small">
            <SourceBadge source={entry.provider} />
            <span className="muted">{entry.category}</span>
            <span className="mono">{relativeAge(entry.age_seconds) ?? "never"}</span>
            {entry.cursor_date && <span className="faint">through {entry.cursor_date}</span>}
          </div>
        ))}
        <span className="spacer" />
        <span className="small faint mono">
          {integer(status.counts.raw_payloads)} raw payloads · {localTime(status.last_sync?.finished_at, timezone) ?? "no completed sync"}
        </span>
      </div>
    </section>
  );
}
