/**
 * Shared chart primitives.
 *
 * All charts share one tooltip, one axis treatment and one palette so a colour
 * means the same thing on every page: terracotta (--chart-primary) for load,
 * effort and "look here", sage (--chart-secondary) for fitness and recovery,
 * and neutral tones for comparisons and baselines. Series names are always
 * spelled out in the legend — colour alone never carries meaning, for the
 * sake of readers who cannot distinguish them.
 *
 * Colours are read from the CSS custom properties in styles.css rather than
 * hard-coded, so every chart repaints when the appearance preference (or the
 * OS, in "auto") switches between light and dark.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, ComposedChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { usePrefs } from "../lib/prefs";

/** Reads the resolved value of a CSS custom property so charts follow the theme. */
export function useThemeColor(variable: string, fallback: string): string {
  const { appearance } = usePrefs();
  const [color, setColor] = useState(fallback);
  useEffect(() => {
    const read = () => {
      const value = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
      if (value) setColor(value);
    };
    read();
    const media = matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", read);
    return () => media.removeEventListener("change", read);
    // `appearance` isn't read directly, but an explicit switch must re-resolve
    // the variable immediately rather than waiting on a system event.
  }, [variable, appearance]);
  return color;
}

export interface Palette {
  primary: string; primaryFill: string;
  secondary: string; secondaryFill: string;
  tertiary: string; quaternary: string; quinary: string;
}

/** The chart palette as live values, recomputed whenever the theme changes. */
export function useChartPalette(): Palette {
  return {
    primary: useThemeColor("--chart-primary", "#b2622d"),
    primaryFill: useThemeColor("--chart-primary-fill", "#ffc6a5"),
    secondary: useThemeColor("--chart-secondary", "#56633f"),
    secondaryFill: useThemeColor("--chart-secondary-fill", "#ccdbb2"),
    tertiary: useThemeColor("--chart-tertiary", "#a19786"),
    quaternary: useThemeColor("--chart-quaternary", "#f6a06b"),
    quinary: useThemeColor("--chart-quinary", "#82796a"),
  };
}

export interface SeriesSpec {
  key: string;
  name: string;
  color: string;
  unit?: string;
  digits?: number;
  type?: "line" | "area" | "bar";
  dashed?: boolean;
  axis?: "left" | "right";
}

function TipContent({ active, payload, label, series }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tip-title">{label}</div>
      {payload.map((entry: any) => {
        const spec: SeriesSpec | undefined = series.find((s: SeriesSpec) => s.key === entry.dataKey);
        if (entry.value === null || entry.value === undefined) return null;
        return (
          <div className="tip-row" key={entry.dataKey}>
            <span className="k">
              <span className="legend-swatch" style={{ background: entry.color, height: 8, width: 8, borderRadius: 2 }} />
              {spec?.name ?? entry.name}
            </span>
            <span className="v">
              {typeof entry.value === "number" ? entry.value.toFixed(spec?.digits ?? 1) : entry.value}
              {spec?.unit ? ` ${spec.unit}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function Legend({ series }: { series: SeriesSpec[] }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <span className="legend-item" key={s.key}>
          <span
            className="legend-swatch"
            style={{ background: s.color, height: s.dashed ? 0 : 3, borderTop: s.dashed ? `2px dashed ${s.color}` : undefined, width: 14 }}
          />
          {s.name}
          {s.unit ? <span className="faint"> ({s.unit})</span> : null}
        </span>
      ))}
    </div>
  );
}

export interface TimeChartProps {
  data: Record<string, any>[];
  series: SeriesSpec[];
  xKey?: string;
  height?: number;
  zeroLine?: boolean;
  rightAxis?: boolean;
  syncId?: string;
  yDomain?: [any, any];
}

/** One composed chart handles lines, areas and bars so hover behaviour is identical. */
export function TimeChart({
  data, series, xKey = "x", height = 200, zeroLine = false, rightAxis = false, syncId, yDomain,
}: TimeChartProps) {
  return (
    <div className="chart">
      <Legend series={series} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} syncId={syncId} margin={{ top: 10, right: rightAxis ? 6 : 12, bottom: 4, left: -14 }}>
          <CartesianGrid vertical={false} strokeDasharray="2 3" />
          <XAxis dataKey={xKey} tickLine={false} axisLine={false} minTickGap={26} />
          <YAxis yAxisId="left" tickLine={false} axisLine={false} width={46} domain={yDomain ?? ["auto", "auto"]} />
          {rightAxis && <YAxis yAxisId="right" orientation="right" tickLine={false} axisLine={false} width={40} />}
          <Tooltip content={<TipContent series={series} />} cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }} />
          {zeroLine && <ReferenceLine yAxisId="left" y={0} stroke="var(--line-strong)" />}
          {series.map((s) =>
            s.type === "bar" ? (
              <Bar key={s.key} yAxisId={s.axis ?? "left"} dataKey={s.key} name={s.name} fill={s.color} radius={[2, 2, 0, 0]} isAnimationActive={false} />
            ) : s.type === "area" ? (
              <Area key={s.key} yAxisId={s.axis ?? "left"} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} fill={s.color} fillOpacity={0.18} strokeWidth={1.8} dot={false} isAnimationActive={false} connectNulls />
            ) : (
              <Line key={s.key} yAxisId={s.axis ?? "left"} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={1.8} strokeDasharray={s.dashed ? "4 3" : undefined} dot={false} isAnimationActive={false} connectNulls />
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StackedBars({
  data, series, xKey = "x", height = 200,
}: { data: Record<string, any>[]; series: SeriesSpec[]; xKey?: string; height?: number }) {
  return (
    <div className="chart">
      <Legend series={series} />
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 10, right: 12, bottom: 4, left: -14 }}>
          <CartesianGrid vertical={false} strokeDasharray="2 3" />
          <XAxis dataKey={xKey} tickLine={false} axisLine={false} minTickGap={20} />
          <YAxis tickLine={false} axisLine={false} width={46} />
          <Tooltip content={<TipContent series={series} />} cursor={{ fill: "var(--surface-inset)" }} />
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.name} stackId="a" fill={s.color} radius={s === series[series.length - 1] ? [2, 2, 0, 0] : undefined} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Sparkline({ values, color, height = 34 }: { values: (number | null)[]; color: string; height?: number }) {
  const data = values.map((v, i) => ({ i, v }));
  if (!values.some((v) => v !== null)) return <span className="na-inline">No data</span>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <Area type="monotone" dataKey="v" stroke={color} fill={color} fillOpacity={0.2} strokeWidth={1.6} dot={false} isAnimationActive={false} connectNulls />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function ChartFrame({ title, right, children, note }: { title: string; right?: ReactNode; children: ReactNode; note?: ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <span className="spacer" />
        {right}
      </div>
      <div className="panel-body flush">{children}</div>
      {note && <div className="panel-body small muted" style={{ paddingTop: 0 }}>{note}</div>}
    </section>
  );
}
