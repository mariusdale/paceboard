import { useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Overview as OverviewData, type RecoverySeries } from "../lib/api";
import { useConnections, useTimezone, useUnits } from "../lib/hooks";
import { dayLabel, distance, duration, elevation, hours, integer, localTime, round, sportLabel } from "../lib/format";
import { CHART, ChartFrame, Sparkline, StackedBars, TimeChart } from "../components/Charts";
import { Empty, Failed, Loading } from "../components/States";
import { buildWeeklyVolume } from "../components/volume";
import { SourceBadge } from "../components/SourceBadge";

export function Overview() {
  const units = useUnits();
  const timezone = useTimezone();
  const connections = useConnections();
  const [windowDays, setWindowDays] = useState(14);
  const [metric, setMetric] = useState<"sleep" | "hrv" | "load">("sleep");
  const query = useQuery({ queryKey: ["overview"], queryFn: () => api.get<OverviewData>("/overview"), refetchInterval: 60_000 });
  const history = useQuery({ queryKey: ["recovery", 30], queryFn: () => api.get<RecoverySeries>("/health/recovery", { days: 30 }), refetchInterval: 60_000 });
  if (query.isLoading) return <section className="panel"><Loading label="Gathering your daily picture" rows={5} /></section>;
  if (query.isError) return <section className="panel"><Failed error={query.error} retry={query.refetch} /></section>;
  const data = query.data!;
  const today = data.today;
  const latest = (key: string) => data.latest_observations?.[key];
  const rhr = latest("resting_hr");
  const battery = latest("body_battery_high");
  const readiness = latest("training_readiness");
  const night = data.last_night;
  const weekly = data.rolling.find(r => r.days === 7);
  const volume = buildWeeklyVolume(data.weekly_volume);
  const firstName = connections.data?.find(c => c.display_name)?.display_name?.split(" ")[0];
  const recovery = history.data;
  const score = night.sleep_score as number | null;
  const stages = [{ label: "Deep", value: night.deep_s, color: "#7d83ff" }, { label: "Light", value: night.light_s, color: "#b2b4ff" }, { label: "REM", value: night.rem_s, color: "#5bcae5" }, { label: "Awake", value: night.awake_s, color: "#f1bb7b" }];
  const stageTotal = stages.reduce((sum, s) => sum + (s.value ?? 0), 0);
  const sleepRows = recovery?.days.map((day, i) => ({ x: dayLabel(day), sleep: recovery.sleep_seconds[i] == null ? null : recovery.sleep_seconds[i]! / 3600, hrv: recovery.hrv_ms[i], baseline: recovery.hrv_baseline[i] })).slice(-windowDays) ?? [];
  const loadRows = data.form.days.map((day, i) => ({ x: dayLabel(day), fitness: data.form.ctl[i], fatigue: data.form.atl[i], load: data.form.daily_load[i] })).slice(-windowDays);
  const hasLoad = data.form.daily_load.some(v => v > 0);
  const hrv = data.recovery.hrv_latest?.value;
  const deviation = data.recovery.hrv_deviation?.value;
  const currentDate = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: timezone }).format(new Date());

  return <>
    <div className="overview-heading">
      <div><div className="eyebrow">YOUR DAILY PICTURE</div><h1>A little more in tune{firstName ? `, ${firstName}` : ""}.</h1><p>Your health, recovery and training. All together.</p></div>
      <div className="date-chip"><span aria-hidden="true">◷</span>{currentDate}</div>
    </div>
    {!today.day && !night.day && !data.recent_activities.length && <div className="banner info"><span>Connect your accounts to bring your daily picture to life.</span><Link to="/settings">Open Connections →</Link></div>}
    <div className="daily-grid">
      <Link to="/recovery" className="hero-score panel">
        <div className="card-top"><span className="eyebrow">SLEEP SCORE</span><span className="circle-arrow">↗</span></div>
        <div className="score-orbit">
          <svg viewBox="0 0 220 220" aria-hidden="true"><circle className="orbit-guide" cx="110" cy="110" r="103"/><circle className="orbit-track" cx="110" cy="110" r="87"/><circle className="orbit-progress" cx="110" cy="110" r="87" strokeDasharray={`${Math.max(0, Math.min(100, score ?? 0)) * 5.466} 546.6`} /></svg>
          <div className="score-center"><span>{score ?? "—"}</span><small>{score == null ? "Awaiting sleep data" : "OUT OF 100"}</small></div>
        </div>
        <div className="score-caption"><h2>{score == null ? "Your next night awaits" : "Your night, at a glance"}</h2><p>{night.day ? `Garmin sleep score · ${dayLabel(night.day)}` : "Sync Garmin to see your sleep score"}</p></div>
      </Link>
      <section className="sleep-card panel">
        <div className="card-top"><span className="card-label"><span className="metric-symbol violet">☾</span> Sleep</span><Link to="/recovery" className="circle-arrow" aria-label="Explore sleep">↗</Link></div>
        <div className="feature-value">{hours(night.total_sleep_s) ?? "—"}</div>
        <p className="feature-note">{night.day ? `Latest night · ${dayLabel(night.day)}` : "No sleep recorded yet"}</p>
        <div className="sleep-stage-bar" aria-label="Total time in each sleep stage">{stages.map(s => <div key={s.label} title={`${s.label}: ${duration(s.value) ?? "unavailable"}`} style={{ flex: stageTotal ? (s.value ?? 0) / stageTotal : 1, background: s.value == null ? "var(--line)" : s.color }} />)}</div>
        <div className="sleep-stage-labels">{stages.map(s => <div key={s.label}><span><i style={{ background: s.color }} />{s.label}</span><strong>{duration(s.value) ?? "—"}</strong></div>)}</div>
        <div className="card-bottom"><span>30-day average</span><strong>{hours(data.baselines.sleep_seconds) ?? "—"}</strong></div>
      </section>
      <section className="week-card panel">
        <div className="card-top"><span className="card-label"><span className="metric-symbol mint">↗</span> Your movement</span><span className="subtle-pill">7 DAYS</span></div>
        <div className="feature-value">{distance(weekly?.distance_m, units) ?? "—"}</div><p className="feature-note">Across {weekly?.count ?? 0} recorded activities</p>
        <div className="week-bars" aria-label="Weekly activity time over the last eight weeks">{Array.from({ length: 8 }, (_, i) => {
          const d = new Date(`${data.form.days[data.form.days.length - 1] ?? new Date().toISOString().slice(0, 10)}T12:00:00Z`);
          d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) - (7 - i) * 7);
          const key = d.toISOString().slice(0, 10);
          const seconds = data.weekly_volume.filter(v => v.week_start === key).reduce((sum, v) => sum + v.duration_s, 0);
          const peak = Math.max(1, ...data.weekly_volume.map(v => data.weekly_volume.filter(w => w.week_start === v.week_start).reduce((sum, w) => sum + w.duration_s, 0)));
          return <div key={key} title={`Week of ${key}: ${hours(seconds)}`}><div className="week-bar-track"><span style={{ height: `${seconds / peak * 100}%` }} /></div><small>{d.getUTCDate()}</small></div>;
        })}</div><p className="week-history-note">Weekly activity time · last 8 weeks</p>
        <div className="card-bottom"><span>{hours(weekly?.duration_s) ?? "—"} moving</span><strong>{elevation(weekly?.elevation_m, units) ?? "—"} ascent</strong></div>
      </section>
    </div>
    <div className="vital-grid">
      <Vital label="Overnight HRV" value={round(hrv, 0)} unit="ms" color="#6ce4bf" symbol="⌁" note={deviation == null ? "No baseline yet" : `${deviation > 0 ? "+" : ""}${deviation.toFixed(1)}% vs your 7-night baseline`} values={recovery?.hrv_ms} />
      <Vital label="Resting heart rate" value={rhr?.value ?? today.resting_hr} unit="bpm" color="#ee91a5" symbol="♡" note={rhr ? `Latest measurement · ${rhr.day}` : "No recent resting heart rate"} values={recovery?.resting_hr} />
      <Vital label="Body Battery" value={battery?.value ?? today.body_battery_high} unit="/ 100" color="#efbf75" symbol="ϟ" note={battery ? `Daily high · ${battery.day}` : "No recent Body Battery measurement"} values={recovery?.body_battery_high} />
      {(readiness || today.training_readiness != null) && <Vital label="Training readiness" value={readiness?.value ?? today.training_readiness} unit="/ 100" color="#a5a2ff" symbol="◎" note={readiness ? `Latest measurement · ${readiness.day}` : today.readiness_level} values={recovery?.training_readiness} />}
    </div>
    <div className="overview-lower">
      <section className="panel trend-panel">
        <div className="card-top"><div><div className="eyebrow">THE BIGGER PICTURE</div><h2>Your rhythm over time</h2></div><div className="segmented" aria-label="Trend window">{[7, 14, 28].map(d => <button key={d} aria-pressed={windowDays === d} onClick={() => setWindowDays(d)}>{d}D</button>)}</div></div>
        <div className="trend-tabs" role="group" aria-label="Trend metric">{([['sleep', 'Sleep'], ['hrv', 'HRV'], ['load', 'Training load']] as const).map(([key, label]) => <button key={key} aria-pressed={metric === key} onClick={() => setMetric(key)}>{label}</button>)}</div>
        {metric === "load" ? hasLoad ? <TimeChart data={loadRows} height={245} series={[{ key: "fitness", name: "Fitness", color: CHART.teal, type: "area" }, { key: "fatigue", name: "Fatigue", color: CHART.amber }]} /> : <Empty title="Training load is not available yet" detail="Your stored activities do not yet have a calculated load. Explore Training for the available metrics and input requirements." action={<Link to="/training">Explore training →</Link>} /> : history.isError ? <Failed error={history.error} retry={history.refetch} /> : history.isLoading ? <Loading rows={3} /> : <TimeChart data={sleepRows} height={245} series={metric === "sleep" ? [{ key: "sleep", name: "Sleep duration", color: "#aaa6ff", type: "area", unit: "h", digits: 2 }] : [{ key: "hrv", name: "Overnight HRV", color: "#6ce4bf", type: "area", unit: "ms" }, { key: "baseline", name: "7-night baseline", color: "#8b9aae", dashed: true, unit: "ms" }]} />}
        <div className="trend-foot">{metric === "load" ? "Calculated from activity load · fitness and fatigue in arbitrary units" : "From Garmin · gaps indicate missing measurements"}<Link to={metric === "load" ? "/training" : "/recovery"}>Explore details ↗</Link></div>
      </section>
      <section className="panel activity-panel"><div className="card-top"><div><div className="eyebrow">KEEP SHOWING UP</div><h2>Recent activities</h2></div><Link to="/activities" className="small">View all ↗</Link></div>
        {data.recent_activities.length ? data.recent_activities.slice(0, 3).map(a => <Link className="activity-item" key={a.id} to={`/activities/${a.id}`}><span className={`activity-symbol ${a.sport === "run" ? "run" : "ride"}`}>{a.sport === "run" ? "↗" : "◎"}</span><div className="activity-copy"><strong>{a.name ?? sportLabel(a.sport)}</strong><span>{localTime(a.start_time_utc, timezone)}</span><div className="activity-numbers">{distance(a.distance_m, units) ?? "—"}<i />{duration(a.moving_duration_s ?? a.duration_s) ?? "—"}</div></div><span className="activity-source">{a.sources.map(s => <SourceBadge key={s.source} source={s.source} />)}<span>↗</span></span></Link>) : <Empty title="Your next activity starts here" detail="Sync Garmin or connect Strava to bring your sessions together." action={<Link to="/settings">Open Connections →</Link>} />}
      </section>
    </div>
    <div className="grid g-2-1">
      <ChartFrame title="Weekly volume by sport" note="Moving time where available, otherwise elapsed time.">{volume.data.length ? <StackedBars data={volume.data} series={volume.series} height={200} /> : <Empty title="No weekly activities yet" detail="Sync your accounts to see your training volume." />}</ChartFrame>
      <section className="panel"><div className="panel-head"><h2>Your longer view</h2></div><div className="panel-body stack">{data.rolling.filter(r => r.days !== 7).map(r => <div key={r.days}><span className="label">Last {r.days} days · {r.count} activities</span><dl className="kv"><dt>Distance</dt><dd>{distance(r.distance_m, units)}</dd><dt>Time</dt><dd>{hours(r.duration_s)}</dd><dt>Ascent</dt><dd>{elevation(r.elevation_m, units)}</dd></dl></div>)}<div><span className="label">Consistency · {data.consistency.window_days} days</span><dl className="kv"><dt>Active days</dt><dd>{data.consistency.active_days}</dd><dt>Current streak</dt><dd>{data.consistency.current_streak} days</dd><dt>Longest streak</dt><dd>{data.consistency.longest_streak} days</dd></dl></div></div></section>
    </div>
    {!readiness && today.training_readiness == null && <details className="panel"><summary className="panel-body small">About training readiness</summary><p className="panel-body small muted">Garmin has not supplied a training readiness score for this day. Availability depends on your device and Garmin data; sleep and HRV remain available independently. Check Connections if other metrics are missing too.</p></details>}
    <div className="daily-footer"><span>Daily metrics: {today.day ?? "awaiting data"} · Sleep: {night.day ?? "awaiting data"}</span><span>{integer(today.steps) ?? "—"} steps · {integer(today.avg_stress) ?? "—"} average stress</span><Link to="/settings">Manage your connections ↗</Link></div>
  </>;
}

function Vital({ label, value, unit, color, symbol, note, values }: { label: string; value: string | number | null | undefined; unit: string; color: string; symbol: string; note: string; values?: (number | null)[] }) {
  return <Link to="/recovery" className="panel vital" style={{ "--vital-color": color } as CSSProperties}><div className="vital-label"><span className="vital-icon">{symbol}</span>{label}<span className="vital-arrow">↗</span></div><div className="vital-middle"><div className="vital-value">{value ?? "—"}<small>{unit}</small></div><div className="vital-spark">{values?.some(v => v != null) ? <Sparkline values={values.slice(-14)} color={color} height={42} /> : <span className="missing-line" />}</div></div><p>{note}</p></Link>;
}
