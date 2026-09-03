/**
 * Overview — the daily read.
 *
 * Answers the two questions people actually open this page for first: how am
 * I trending against my own history, and how did I sleep last night. Load,
 * form and provider freshness are still true and still available — they just
 * live on Training and Your data now, in a supporting role rather than the
 * headline. See the "Overview" section of the build notes this screen came
 * with for the reasoning.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type LoadSeries, type Overview as OverviewData, type RecoverySeries } from "../lib/api";
import { useLatestSync, useStartSync, useStatus, useUnits } from "../lib/hooks";
import { usePrefs, jargonLabel } from "../lib/prefs";
import { distance, dayLabel, hours, round, sportLabel } from "../lib/format";
import { Sparkline, useChartPalette } from "../components/Charts";
import { Empty, Failed, Loading } from "../components/States";
import { Icon, sportIcon } from "../lib/icons";

const SPORT_TOKEN: Record<string, { bg: string; fg: string }> = {
  run: { bg: "var(--badge-strava-bg)", fg: "var(--badge-strava-fg)" },
  walk: { bg: "var(--badge-strava-bg)", fg: "var(--badge-strava-fg)" },
  hike: { bg: "var(--badge-strava-bg)", fg: "var(--badge-strava-fg)" },
  ride: { bg: "var(--badge-garmin-bg)", fg: "var(--badge-garmin-fg)" },
  swim: { bg: "var(--badge-garmin-bg)", fg: "var(--badge-garmin-fg)" },
  row: { bg: "var(--badge-garmin-bg)", fg: "var(--badge-garmin-fg)" },
};
function sportToken(sport: string) {
  return SPORT_TOKEN[sport] ?? { bg: "var(--badge-paceboard-bg)", fg: "var(--badge-paceboard-fg)" };
}

/** Like hours(), but drops a redundant "0h" prefix in running prose. */
function shortHours(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export function Overview() {
  const units = useUnits();
  const status = useStatus();
  const { jargon } = usePrefs();
  const palette = useChartPalette();

  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => api.get<OverviewData>("/overview"),
    refetchInterval: 60_000,
  });
  const rhythm = useQuery({
    queryKey: ["overview-rhythm"],
    queryFn: () => api.get<RecoverySeries>("/health/recovery", { days: 14 }),
  });
  const load90 = useQuery({
    queryKey: ["overview-load90"],
    queryFn: () => api.get<LoadSeries>("/training/load", { days: 90 }),
  });

  if (overview.isLoading) return <section className="panel"><Loading label="Loading overview" rows={6} /></section>;
  if (overview.isError) return <section className="panel"><Failed error={overview.error} retry={overview.refetch} /></section>;

  const data = overview.data!;
  const empty = (status.data?.counts.activities ?? 0) === 0 && (status.data?.counts.daily_health ?? 0) === 0;
  if (empty) {
    return (
      <section className="panel">
        <Empty
          title="No data yet"
          detail="Paceboard has not stored anything from Garmin or Strava. Run a backfill from Connections to pull your history, or press Sync now for the last few days."
          action={<Link className="btn primary" to="/settings">Open Connections</Link>}
        />
      </section>
    );
  }

  const today = data.today;
  const night = data.last_night;
  const base = data.baselines;
  const week = data.rolling.find((r) => r.days === 7) ?? data.rolling[0];
  const recovery = data.recovery;

  // The Overview payload's own 28-day load series cold-starts CTL at 0 (it has
  // no warmup runway before the window), which makes a "vs 4 weeks ago" delta
  // meaningless and disagrees with Training's default 90-day view. Prefer the
  // 90-day series — which both this card and Training read — so the two pages
  // never show a different "current" base.
  const ctlSeries = load90.data?.ctl ?? null;
  const ctlNow = ctlSeries ? ctlSeries.at(-1) ?? null : data.form.latest_ctl;
  const ctlThen = ctlSeries && ctlSeries.length > 28 ? ctlSeries[ctlSeries.length - 29] : null;
  const ctlPct = ctlNow != null && ctlThen != null && ctlThen !== 0 ? ((ctlNow - ctlThen) / ctlThen) * 100 : null;
  const atlNow = load90.data?.atl.at(-1) ?? data.form.latest_atl;
  const sleepDeltaS = today.is_today && night.total_sleep_s != null && base.sleep_seconds != null
    ? night.total_sleep_s - base.sleep_seconds
    : null;
  const { title: headline, body: subhead } = buildHeadline({ ctlPct, sleepDeltaS, week, today, base });

  const trendSpark = (ctlSeries ?? data.form.ctl).filter((v): v is number => v != null);
  const weekLoads = data.form.daily_load.slice(-7).map((v) => v ?? 0);
  const rank = weekRank(data.weekly_volume);

  const streak = data.consistency.current_streak;
  const best = data.consistency.longest_streak;
  const nudge = data.consistency.active_days === 0
    ? "No activity yet in this window — the streak starts with your next session."
    : streak > 0
      ? `You've moved ${streak} day${streak === 1 ? "" : "s"} running${streak >= best ? ", your longest stretch on record" : `, ${best - streak} short of your best`}.`
      : `Move today and you'll start a new streak.`;

  const dots = buildDots(load90.data);

  return (
    <>
      <section className="hero">
        <div style={{ maxWidth: 700 }}>
          <div className="hero-eyebrow">{today.day ? dayLabel(today.day) : "No data yet"}{today.is_today ? " · today" : ""}</div>
          <h1>{headline}</h1>
          <p>{subhead}</p>
        </div>
        <span style={{ flex: 1 }} />
        <div className="row" style={{ flex: "none" }}>
          <Link className="btn" to="/explorer">
            Sources <Icon name="chevronDown" size={13} />
          </Link>
          <SyncNowButton />
        </div>
      </section>

      <div className="row" style={{ gap: 7 }}>
        {ctlPct != null && (
          <span className="tag tag-accent-2">
            {jargonLabel("Base", "CTL", jargon)} {ctlPct >= 0 ? "+" : ""}{ctlPct.toFixed(0)}% in 4 weeks
          </span>
        )}
        {week && <span className="tag tag-accent">{week.count} sessions in the last 7 days</span>}
        {recovery.sleep_debt_7d?.available && recovery.sleep_debt_7d.value != null && (
          <span className="tag tag-neutral">Sleep debt {recovery.sleep_debt_7d.value.toFixed(1)}h</span>
        )}
        {today.resting_hr != null && base.resting_hr != null && (
          <span className="tag tag-neutral">
            Resting heart rate {today.resting_hr - base.resting_hr >= 0 ? "+" : ""}{Math.round(today.resting_hr - base.resting_hr)} bpm
          </span>
        )}
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 2fr" }}>
        <div className="stat-card">
          <div className="stat-kicker"><Icon name="trendingUp" />{jargonLabel("Fitness trend", "CTL", jargon)}</div>
          <div className="stat-value">{ctlPct != null ? `${ctlPct >= 0 ? "+" : ""}${ctlPct.toFixed(0)}%` : "—"}</div>
          <div className="stat-sub">{ctlPct == null ? "Not enough history yet" : ctlPct >= 0 ? "Base is higher than four weeks ago" : "Base has eased back over four weeks"}</div>
          <div style={{ marginTop: "auto", paddingTop: 12 }}>
            {trendSpark.length > 1 && <Sparkline values={trendSpark} color={palette.secondary} height={40} />}
            <div className="stat-meta">
              {atlNow != null && ctlNow != null
                ? `Recent load ${atlNow >= ctlNow ? "running ahead of" : "below"} your base`
                : "Recent load unavailable"}
            </div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-kicker"><Icon name="list" />Last 7 days</div>
          <div className="stat-value">{week ? hours(week.duration_s) : "—"}</div>
          <div className="stat-sub">
            {week ? `${week.count} sessions, ${distance(week.distance_m, units) ?? "—"}${rank ? ` — ${rank}` : ""}` : "No sessions yet"}
          </div>
          <div style={{ marginTop: "auto", paddingTop: 12 }}>
            {weekLoads.some((v) => v > 0) && <Sparkline values={weekLoads} color={palette.primary} height={40} />}
            <div className="stat-meta">
              {streak > 0 ? `${streak}-day streak · ` : ""}{data.consistency.active_days} of the last {data.consistency.window_days} days active
            </div>
          </div>
        </div>

        <SleepHero night={night} today={today} base={base} recovery={recovery} jargon={jargon} />
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Your rhythm</h2>
          <span className="small faint">last 14 days · effort against sleep</span>
          <span className="spacer" />
          <span className="legend-item"><span className="legend-swatch" style={{ background: palette.primary }} />Effort</span>
          <span className="legend-item"><span className="legend-swatch" style={{ background: palette.secondary }} />Sleep</span>
        </div>
        <div className="panel-body">
          <RhythmStrip form={data.form} rhythm={rhythm.data} palette={palette} />
        </div>
      </section>

      <div className="grid g-2-1">
        <section className="panel">
          <div className="panel-head">
            <h2>Recent sessions</h2>
            <span className="spacer" />
            <Link to="/activities" className="small">All activities →</Link>
          </div>
          <div className="panel-body flush">
            {data.recent_activities.length === 0 ? (
              <Empty title="No activities stored" detail="Nothing has been ingested yet for this account." />
            ) : (
              <SessionList activities={data.recent_activities} units={units} />
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Showing up</h2>
            <span className="spacer" />
            <span className="small faint">{data.consistency.window_days} days</span>
          </div>
          <div className="panel-body">
            <div className="row" style={{ alignItems: "baseline", gap: 7 }}>
              <span style={{ fontSize: 32, fontWeight: 700, letterSpacing: "-0.032em", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
                {data.consistency.active_days}
              </span>
              <span className="small muted">active days of {data.consistency.window_days}</span>
            </div>
            {dots.length > 0 && (
              <div className="consistency-dots">
                {dots.map((d, i) => <span key={i} style={{ background: d.color }} title={d.title} />)}
              </div>
            )}
            <div className="grid g2" style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
              <div>
                <div className="label">Streak</div>
                <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: "-0.025em", fontVariantNumeric: "tabular-nums", marginTop: 2 }}>{streak} days</div>
              </div>
              <div>
                <div className="label">Best in {data.consistency.window_days} days</div>
                <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: "-0.025em", fontVariantNumeric: "tabular-nums", marginTop: 2 }}>{best} days</div>
              </div>
            </div>
            <div className="nudge">{nudge}</div>
          </div>
        </section>
      </div>
    </>
  );
}

function SyncNowButton() {
  const sync = useLatestSync();
  const start = useStartSync();
  const running = sync.data?.status === "running";
  return (
    <button
      className="primary"
      disabled={running || start.isPending}
      onClick={() => start.mutate({ providers: ["garmin", "strava"], mode: "incremental" })}
    >
      {running ? "Syncing…" : start.isPending ? "Starting…" : "Sync now"}
    </button>
  );
}

function SleepHero({
  night, today, base, recovery, jargon,
}: {
  night: OverviewData["last_night"];
  today: OverviewData["today"];
  base: OverviewData["baselines"];
  recovery: OverviewData["recovery"];
  jargon: boolean;
}) {
  const total = night.total_sleep_s as number | null;
  const stages = [
    { label: "Deep", s: night.deep_s as number | null, color: "var(--color-accent-2-300)" },
    { label: "Light", s: night.light_s as number | null, color: "var(--color-accent-2-500)" },
    { label: "REM", s: night.rem_s as number | null, color: "var(--color-accent-400)" },
    { label: "Awake", s: night.awake_s as number | null, color: "var(--color-neutral-500)" },
  ].filter((s) => s.s != null && s.s > 0);
  const stageTotal = stages.reduce((sum, s) => sum + (s.s ?? 0), 0) || 1;

  const rhrDelta = today.resting_hr != null && base.resting_hr != null ? today.resting_hr - base.resting_hr : null;

  return (
    <div className="sleep-hero">
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div className="sh-kicker"><Icon name="moon" />Last night</div>
        <div className="sh-value">{total != null ? hours(total) : "—"}</div>
        <div className="sh-sub">
          {total != null && base.sleep_seconds != null
            ? total >= base.sleep_seconds ? `About ${shortHours(total - base.sleep_seconds)} more than your 30-day average` : `${shortHours(base.sleep_seconds - total)} short of your 30-day average`
            : "No sleep recorded for last night"}
        </div>
        {stages.length > 0 && (
          <>
            <div className="sleep-stages">
              {stages.map((s) => <div key={s.label} style={{ width: `${((s.s ?? 0) / stageTotal) * 100}%`, background: s.color }} title={`${s.label} — ${hours(s.s ?? 0)}`} />)}
            </div>
            <div className="sleep-stage-legend">
              {stages.map((s) => (
                <span key={s.label}><span className="swatch" style={{ background: s.color }} />{s.label} {hours(s.s ?? 0)}</span>
              ))}
            </div>
          </>
        )}
        <div className="sh-note">
          {recovery.sleep_debt_7d?.available && recovery.sleep_debt_7d.value != null
            ? `Sleep debt ${recovery.sleep_debt_7d.value.toFixed(1)}h over the last 7 nights.`
            : "Sleep debt needs more nights of history to compute."}
        </div>
      </div>
      <div className="grid g2" style={{ alignContent: "start" }}>
        <Vital label="Sleep score" value={night.sleep_score != null ? String(night.sleep_score) : null} unit="/100" />
        <Vital
          label={jargonLabel("Recovery", "HRV", jargon)}
          value={recovery.hrv_latest?.value != null ? String(Math.round(recovery.hrv_latest.value)) : null}
          unit="ms"
          delta={recovery.hrv_deviation?.value != null ? `${recovery.hrv_deviation.value > 0 ? "+" : ""}${recovery.hrv_deviation.value.toFixed(0)}% vs baseline` : undefined}
        />
        <Vital
          label="Resting heart rate"
          value={today.resting_hr != null ? String(today.resting_hr) : null}
          unit="bpm"
          delta={rhrDelta != null ? `${rhrDelta >= 0 ? "+" : ""}${Math.round(rhrDelta)} vs 30-day avg` : undefined}
        />
        <Vital
          label={jargonLabel("Energy", "Body Battery", jargon)}
          value={today.body_battery_high != null ? String(today.body_battery_high) : null}
          unit="/100"
          delta={today.body_battery_low != null ? `Low ${today.body_battery_low}` : undefined}
        />
      </div>
    </div>
  );
}

function Vital({
  label, value, unit, delta,
}: { label: string; value: string | null; unit: string; delta?: string }) {
  return (
    <div className="vital">
      <span className="label">{label}</span>
      <div className="vital-value">
        {value != null ? <strong>{value}</strong> : <span style={{ color: "var(--hero-fg-muted)" }}>—</span>}
        {value != null && <span>{unit}</span>}
      </div>
      {delta && <div className="vital-delta">{delta}</div>}
    </div>
  );
}

function RhythmStrip({
  form, rhythm, palette,
}: { form: OverviewData["form"]; rhythm?: RecoverySeries; palette: ReturnType<typeof useChartPalette> }) {
  const days = form.days.slice(-14);
  const loads = form.daily_load.slice(-14);
  const maxLoad = Math.max(1, ...loads.map((l) => l ?? 0));
  const sleepByDay = new Map((rhythm?.days ?? []).map((d, i) => [d, rhythm!.sleep_seconds[i]]));

  return (
    <div className="rhythm-row">
      {days.map((day, i) => {
        const load = loads[i] ?? 0;
        const sleepS = sleepByDay.get(day) ?? null;
        const d = new Date(`${day}T12:00:00Z`);
        const isToday = i === days.length - 1;
        return (
          <div key={day} className="rhythm-day" style={{ background: isToday ? "var(--tag-accent-bg)" : "transparent" }}>
            <div className="rhythm-bars">
              <span style={{ height: `${Math.max(3, (load / maxLoad) * 74)}px`, background: load === 0 ? "var(--line-strong)" : palette.primary }} title={load === 0 ? "Rest day" : `Load ${round(load, 0)}`} />
              <span style={{ height: sleepS != null ? `${Math.max(3, ((sleepS / 3600 - 4) / 6) * 74)}px` : "3px", background: palette.secondaryFill }} title={sleepS != null ? `Slept ${hours(sleepS)}` : "No sleep data"} />
            </div>
            <div className="rhythm-dow" style={{ color: isToday ? "var(--accent-ink)" : "var(--text-faint)" }}>
              {new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" }).format(d).slice(0, 2)}
            </div>
            <div className="rhythm-date">{new Intl.DateTimeFormat("en-GB", { day: "2-digit", timeZone: "UTC" }).format(d)}</div>
          </div>
        );
      })}
    </div>
  );
}

function SessionList({ activities, units }: { activities: OverviewData["recent_activities"]; units: "metric" | "imperial" }) {
  const maxLoad = Math.max(1, ...activities.map((a) => a.training_load ?? 0));
  return (
    <>
      {activities.slice(0, 6).map((a) => {
        const token = sportToken(a.sport);
        const pct = a.training_load != null ? Math.round((a.training_load / maxLoad) * 100) : null;
        return (
          <Link key={a.id} to={`/activities/${a.id}`} className="session-row">
            <span className="session-icon" style={{ background: token.bg, color: token.fg }}>
              <Icon name={sportIcon(a.sport)} />
            </span>
            <span style={{ minWidth: 0 }}>
              <span className="session-name">{a.name ?? sportLabel(a.sport)}</span>
              <span className="session-when">{relativeDay(a.start_time_utc)}</span>
            </span>
            <span className="mono" style={{ fontSize: 13 }}>{distance(a.distance_m, units) ?? "—"}</span>
            <span className="mono" style={{ fontSize: 13 }}>{a.duration_s ? hours(a.duration_s) : "—"}</span>
            <span className="row" style={{ gap: 8 }}>
              <span className="effort-bar"><span style={{ width: `${pct ?? 0}%`, background: (pct ?? 0) > 66 ? "var(--chart-primary)" : "var(--chart-secondary)" }} /></span>
              <span className="small faint nowrap">{pct != null ? `${pct}%` : "—"}</span>
            </span>
          </Link>
        );
      })}
    </>
  );
}

function relativeDay(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) - Date.UTC(then.getUTCFullYear(), then.getUTCMonth(), then.getUTCDate())) / 86400000);
  const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false }).format(then);
  if (diffDays === 0) return `Today, ${time}`;
  if (diffDays === 1) return `Yesterday, ${time}`;
  if (diffDays < 7) return `${new Intl.DateTimeFormat("en-GB", { weekday: "short" }).format(then)}, ${time}`;
  return `${dayLabel(iso.slice(0, 10))}, ${time}`;
}

function buildDots(load90?: LoadSeries) {
  if (!load90) return [];
  const max = Math.max(1, ...load90.daily_load.map((l) => l ?? 0));
  return load90.days.map((day, i) => {
    const load = load90.daily_load[i] ?? 0;
    const color = load === 0 ? "var(--surface-inset)" : load / max > 0.6 ? "var(--chart-primary)" : "var(--chart-primary-fill)";
    return { color, title: `${dayLabel(day)} · ${load ? `load ${round(load, 0)}` : "rest"}` };
  });
}

function weekRank(buckets: OverviewData["weekly_volume"]): string | null {
  if (!buckets.length) return null;
  const totals = new Map<string, number>();
  for (const b of buckets) totals.set(b.week_start, (totals.get(b.week_start) ?? 0) + b.distance_m);
  const weeks = [...totals.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  if (weeks.length < 2) return null;
  const current = weeks[weeks.length - 1];
  const sorted = [...totals.values()].sort((a, b) => b - a);
  const rank = sorted.indexOf(current[1]) + 1;
  const ORD = ["", "biggest", "second-biggest", "third-biggest", "fourth-biggest"];
  return rank === 1 ? `your biggest week of the last ${weeks.length}` : `${ORD[rank] ?? `${rank}th-biggest`} of the last ${weeks.length}`;
}

function buildHeadline({
  ctlPct, sleepDeltaS, week, today, base,
}: {
  ctlPct: number | null;
  sleepDeltaS: number | null;
  week?: OverviewData["rolling"][number];
  today: OverviewData["today"];
  base: OverviewData["baselines"];
}): { title: string; body: string } {
  const fitnessClause = ctlPct == null
    ? "Your training base is still building a picture"
    : ctlPct > 3 ? "You're fitter than a month ago"
    : ctlPct < -3 ? "Your base has eased back from a month ago"
    : "Your base is holding steady from a month ago";

  const sleepClause = sleepDeltaS == null ? null
    : Math.abs(sleepDeltaS) < 15 * 60 ? "you slept about as usual last night"
    : sleepDeltaS < 0 ? `you slept ${shortHours(Math.abs(sleepDeltaS))} short of usual` : `you slept ${shortHours(sleepDeltaS)} more than usual`;

  const title = sleepClause ? `${fitnessClause} — and ${sleepClause}.` : `${fitnessClause}.`;

  const bodyParts: string[] = [];
  if (week) bodyParts.push(`${week.count} session${week.count === 1 ? "" : "s"} in the last 7 days`);
  const drifting: string[] = [];
  if (sleepDeltaS != null && sleepDeltaS < -15 * 60) drifting.push("sleep");
  if (today.resting_hr != null && base.resting_hr != null && today.resting_hr - base.resting_hr > 1) drifting.push("resting heart rate");
  if (drifting.length) bodyParts.push(`${drifting.join(" and ")} ${drifting.length > 1 ? "are" : "is"} drifting the wrong way`);
  const body = bodyParts.length ? `${bodyParts.join(", ")}.` : "Numbers are steady across the board right now.";

  return { title, body };
}
