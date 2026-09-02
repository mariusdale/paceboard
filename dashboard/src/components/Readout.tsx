/**
 * The readout rail — Paceboard's signature component.
 *
 * A measured value, its unit, and where it currently sits against its own
 * trailing baseline. The deviation strip is a hairline with a centre tick at the
 * baseline and a marker at today's value, so "am I above or below normal" reads
 * at a glance without parsing a number. It is the piece that makes the app feel
 * like an instrument rather than a report.
 */
import type { ReactNode } from "react";

export interface ReadoutProps {
  label: string;
  value: string | null;
  unit?: string | null;
  /** Current numeric value, used only for the deviation strip. */
  raw?: number | null;
  baseline?: number | null;
  /** True when a lower number is the better outcome (resting HR, stress). */
  lowerIsBetter?: boolean;
  note?: ReactNode;
  unavailableReason?: string | null;
  /** Half-width of the strip in the value's own units. Defaults to 20% of baseline. */
  span?: number;
}

export function Readout({
  label, value, unit, raw, baseline, lowerIsBetter = false, note, unavailableReason, span,
}: ReadoutProps) {
  const hasDeviation =
    typeof raw === "number" && Number.isFinite(raw) &&
    typeof baseline === "number" && Number.isFinite(baseline) && baseline !== 0;

  let offsetPct = 50;
  let direction: "up" | "down" | "flat" = "flat";
  let deltaText: string | null = null;

  if (hasDeviation) {
    const width = span ?? (Math.abs(baseline!) * 0.2 || 1);
    const delta = raw! - baseline!;
    offsetPct = Math.max(3, Math.min(97, 50 + (delta / width) * 50));
    const better = lowerIsBetter ? delta < 0 : delta > 0;
    direction = Math.abs(delta) < width * 0.06 ? "flat" : better ? "up" : "down";
    const pct = (delta / Math.abs(baseline!)) * 100;
    deltaText = `${pct >= 0 ? "+" : ""}${pct.toFixed(pct >= 10 || pct <= -10 ? 0 : 1)}% vs 30-day avg`;
  }

  return (
    <div className="readout">
      <span className="label">{label}</span>
      {value === null ? (
        <div className="readout-value na" title={unavailableReason ?? undefined}>
          Unavailable
        </div>
      ) : (
        <div className="readout-value">
          <span>{value}</span>
          {unit ? <span className="unit">{unit}</span> : null}
        </div>
      )}
      {hasDeviation && (
        <div
          className="dev"
          role="img"
          aria-label={`${label}: ${deltaText}`}
          title={deltaText ?? undefined}
        >
          <span className="dev-mid" />
          <span className={`dev-mark ${direction}`} style={{ left: `${offsetPct}%` }} />
        </div>
      )}
      {(note || deltaText || unavailableReason) && (
        <div className="readout-note">
          {note ?? (value === null ? unavailableReason : deltaText)}
        </div>
      )}
    </div>
  );
}

export function ReadoutRail({ children }: { children: ReactNode }) {
  return <div className="readouts">{children}</div>;
}
