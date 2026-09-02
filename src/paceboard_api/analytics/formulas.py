"""Pure derived-metric functions with documented formulas.

Every function here is side-effect free and returns ``None`` when its inputs are
insufficient. That is the core rule of Paceboard's analytics: a metric that
cannot be computed is reported as unavailable *with a reason*, never as zero and
never estimated from a proxy.

Each formula carries a ``FORMULA_VERSION``; persisted derived metrics record the
version that produced them, so a later change to a formula is visible rather
than silently rewriting history.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

FORMULA_VERSION = "1"

Number = Optional[float]


@dataclass(frozen=True)
class Unavailable:
    """Why a metric could not be computed. Rendered verbatim in the UI."""

    reason: str


def _clean(values: Sequence[Number]) -> list[float]:
    return [v for v in values if v is not None and not math.isnan(v)]


# -- training load ---------------------------------------------------------


def exponential_load(
    daily_load: Sequence[float], time_constant_days: float, seed: Optional[float] = None
) -> list[float]:
    """Exponentially weighted moving average over daily training load.

    ``CTL`` uses a 42-day constant, ``ATL`` a 7-day one (Banister/TRIMP impulse
    response, as popularised by the Performance Management Chart). Day *n*:

        L[n] = L[n-1] + (load[n] - L[n-1]) / tau
    """
    if time_constant_days <= 0:
        return []
    out: list[float] = []
    previous = seed if seed is not None else 0.0
    for load in daily_load:
        previous = previous + (load - previous) / time_constant_days
        out.append(previous)
    return out


def training_stress_balance(ctl: float, atl: float) -> float:
    """Form = fitness - fatigue, using the previous day's values by convention."""
    return ctl - atl


def trimp_banister(
    duration_minutes: Number,
    avg_hr: Number,
    resting_hr: Number,
    max_hr: Number,
    sex: Optional[str] = None,
) -> Number:
    """Banister TRIMP.

        HRr   = (HRavg - HRrest) / (HRmax - HRrest)
        TRIMP = minutes x HRr x 0.64 x e^(k x HRr)

    with k = 1.92 for men and 1.67 for women (Banister 1991). When sex is
    unknown the male constant is used and the caller is told so, rather than the
    metric being withheld — the ranking between sessions is unaffected.
    """
    if not duration_minutes or avg_hr is None or resting_hr is None or max_hr is None:
        return None
    if max_hr <= resting_hr:
        return None
    reserve = (avg_hr - resting_hr) / (max_hr - resting_hr)
    if reserve <= 0:
        return None
    reserve = min(reserve, 1.2)
    k = 1.67 if (sex or "").lower().startswith("f") else 1.92
    return duration_minutes * reserve * 0.64 * math.exp(k * reserve)


def monotony(daily_loads: Sequence[Number]) -> Number:
    """Foster monotony: mean daily load / standard deviation over the week."""
    values = _clean(daily_loads)
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    sd = math.sqrt(variance)
    if sd <= 0:
        return None
    return mean / sd


def strain(weekly_load: Number, monotony_value: Number) -> Number:
    """Foster strain: weekly load x monotony."""
    if weekly_load is None or monotony_value is None:
        return None
    return weekly_load * monotony_value


def acwr(acute: Number, chronic: Number) -> Number:
    """Acute:chronic workload ratio; undefined without a chronic baseline."""
    if acute is None or not chronic:
        return None
    return acute / chronic


# -- power -----------------------------------------------------------------


def normalized_power(watts: Sequence[Number], sample_seconds: float = 1.0) -> Number:
    """Coggan Normalized Power.

    30-second rolling average of power, raised to the 4th power, averaged, then
    the 4th root. Requires at least 30 seconds of power data.
    """
    values = [v if v is not None else 0.0 for v in watts]
    window = max(1, int(round(30.0 / max(sample_seconds, 0.001))))
    if len(values) < window:
        return None
    rolling: list[float] = []
    total = sum(values[:window])
    rolling.append(total / window)
    for index in range(window, len(values)):
        total += values[index] - values[index - window]
        rolling.append(total / window)
    if not rolling:
        return None
    fourth = sum(v**4 for v in rolling) / len(rolling)
    return fourth**0.25


def intensity_factor(np_watts: Number, ftp_watts: Number) -> Number:
    """IF = NP / FTP."""
    if np_watts is None or not ftp_watts:
        return None
    return np_watts / ftp_watts


def training_stress_score(
    duration_seconds: Number, np_watts: Number, ftp_watts: Number
) -> Number:
    """TSS = (s x NP x IF) / (FTP x 3600) x 100."""
    if not duration_seconds or np_watts is None or not ftp_watts:
        return None
    factor = intensity_factor(np_watts, ftp_watts)
    if factor is None:
        return None
    return (duration_seconds * np_watts * factor) / (ftp_watts * 3600) * 100


def watts_per_kg(watts: Number, weight_kg: Number) -> Number:
    if watts is None or not weight_kg:
        return None
    return watts / weight_kg


# -- endurance / efficiency ------------------------------------------------


def aerobic_decoupling(
    output: Sequence[Number], heart_rate: Sequence[Number]
) -> Number:
    """Cardiac drift: percent change in output-per-heartbeat, first half vs second.

        Pw:Hr = ((EF_first - EF_second) / EF_first) x 100

    where EF is mean(output) / mean(HR). Positive means efficiency fell — the
    classic aerobic-decoupling signal. Needs at least 20 usable paired samples.
    """
    pairs = [
        (o, h)
        for o, h in zip(output, heart_rate)
        if o is not None and h is not None and h > 0 and o > 0
    ]
    if len(pairs) < 20:
        return None
    middle = len(pairs) // 2
    halves = (pairs[:middle], pairs[middle:])
    factors: list[float] = []
    for half in halves:
        mean_output = sum(p[0] for p in half) / len(half)
        mean_hr = sum(p[1] for p in half) / len(half)
        if mean_hr <= 0:
            return None
        factors.append(mean_output / mean_hr)
    if factors[0] <= 0:
        return None
    return (factors[0] - factors[1]) / factors[0] * 100


def grade_adjusted_pace(speed_mps: Number, grade_percent: Number) -> Number:
    """Grade-adjusted speed using Minetti's metabolic cost of gradient running.

    Cost (J/kg/m) is a 5th-order polynomial in gradient *i*; the adjusted speed
    scales actual speed by cost(i)/cost(0). Valid for |grade| <= 45 %, which is
    the range Minetti et al. (2002) measured — outside it, ``None``.
    """
    if speed_mps is None or grade_percent is None or speed_mps <= 0:
        return None
    i = grade_percent / 100.0
    if abs(i) > 0.45:
        return None
    def cost(g: float) -> float:
        return 155.4 * g**5 - 30.4 * g**4 - 43.3 * g**3 + 46.3 * g**2 + 19.5 * g + 3.6
    flat = cost(0.0)
    return speed_mps * (cost(i) / flat)


# -- curves ----------------------------------------------------------------


def best_average_curve(
    values: Sequence[Number], durations: Sequence[int], sample_seconds: float = 1.0
) -> dict[int, float]:
    """Best sustained average of ``values`` for each requested duration.

    Powers both the power-duration and the pace-duration curve. Uses a prefix-sum
    sweep, so the whole curve costs O(n x len(durations)) rather than O(n^2).
    """
    series = [v if v is not None else 0.0 for v in values]
    if not series:
        return {}
    prefix = [0.0]
    for value in series:
        prefix.append(prefix[-1] + value)
    out: dict[int, float] = {}
    for duration in durations:
        window = max(1, int(round(duration / max(sample_seconds, 0.001))))
        if window > len(series):
            continue
        best = max(
            (prefix[i + window] - prefix[i]) / window
            for i in range(len(series) - window + 1)
        )
        out[duration] = best
    return out


def best_efforts(
    distance: Sequence[Number], elapsed: Sequence[Number], targets: Sequence[float]
) -> dict[float, float]:
    """Fastest time to cover each target distance, via a two-pointer sweep."""
    points = [
        (d, t)
        for d, t in zip(distance, elapsed)
        if d is not None and t is not None
    ]
    if len(points) < 2:
        return {}
    out: dict[float, float] = {}
    for target in targets:
        if points[-1][0] - points[0][0] < target:
            continue
        best: Optional[float] = None
        left = 0
        for right in range(len(points)):
            while points[right][0] - points[left][0] >= target:
                span = points[right][1] - points[left][1]
                if span > 0 and (best is None or span < best):
                    best = span
                left += 1
        if best is not None:
            out[target] = best
    return out


# -- recovery --------------------------------------------------------------


def rolling_baseline(values: Sequence[Number], window: int) -> list[Number]:
    """Trailing mean over ``window`` observations; ``None`` until it is filled."""
    out: list[Number] = []
    buffer: list[float] = []
    for value in values:
        if value is not None:
            buffer.append(value)
        if len(buffer) > window:
            buffer.pop(0)
        out.append(sum(buffer) / len(buffer) if len(buffer) >= window else None)
    return out


def deviation_from_baseline(value: Number, baseline: Number) -> Number:
    """Percent deviation from a rolling baseline."""
    if value is None or not baseline:
        return None
    return (value - baseline) / baseline * 100


def sleep_debt(sleep_seconds: Sequence[Number], target_hours: float = 8.0) -> Number:
    """Cumulative shortfall against a nightly target, in hours (never negative).

    Surplus nights offset deficits, but the total floors at zero: "sleep credit"
    is not a thing the physiology supports.
    """
    values = _clean(sleep_seconds)
    if not values:
        return None
    target = target_hours * 3600
    return max(0.0, sum(target - v for v in values) / 3600)


#: Bedtime SD at which the consistency score reaches zero.
CONSISTENCY_FLOOR_MINUTES = 120.0


def bedtime_spread_minutes(bed_times_seconds: Sequence[Number]) -> Number:
    """Standard deviation of bedtime, in minutes. Needs at least 3 nights."""
    values = _clean(bed_times_seconds)
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance) / 60


def sleep_consistency(bed_times_seconds: Sequence[Number]) -> Number:
    """Consistency score 0-100 from the SD of bedtime, in seconds-past-midnight.

    A 0-minute SD scores 100; the score decays linearly to 0 at a
    ``CONSISTENCY_FLOOR_MINUTES`` SD, beyond which the timing signal stops
    discriminating. The score alone is hard to act on, so callers should report
    :func:`bedtime_spread_minutes` alongside it — "0/100" means much more when it
    reads "bedtime varies by +/- 3h 12m".
    """
    spread = bedtime_spread_minutes(bed_times_seconds)
    if spread is None:
        return None
    return max(0.0, min(100.0, 100.0 * (1 - spread / CONSISTENCY_FLOOR_MINUTES)))


def pearson(xs: Sequence[Number], ys: Sequence[Number]) -> Optional[tuple[float, int]]:
    """Pearson r with the pair count, or ``None`` below 5 usable pairs."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None
    n = len(pairs)
    mean_x = sum(p[0] for p in pairs) / n
    mean_y = sum(p[1] for p in pairs) / n
    cov = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pairs)
    var_x = sum((p[0] - mean_x) ** 2 for p in pairs)
    var_y = sum((p[1] - mean_y) ** 2 for p in pairs)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y), n


# -- zones & consistency ---------------------------------------------------


def zone_distribution(seconds_by_zone: dict[int, Number]) -> dict[int, float]:
    """Percent of time in each zone; empty when no zone has time recorded."""
    total = sum(v for v in seconds_by_zone.values() if v)
    if not total:
        return {}
    return {
        zone: (seconds or 0) / total * 100 for zone, seconds in seconds_by_zone.items()
    }


def intensity_distribution(seconds_by_zone: dict[int, Number]) -> Optional[dict[str, float]]:
    """Collapse HR zones into the polarised easy/moderate/hard split.

    Zones 1-2 easy, zone 3 moderate, zones 4-5 hard — the standard three-bin
    model used to check an 80/20-style distribution.
    """
    distribution = zone_distribution(seconds_by_zone)
    if not distribution:
        return None
    easy = sum(v for z, v in distribution.items() if z <= 2)
    moderate = sum(v for z, v in distribution.items() if z == 3)
    hard = sum(v for z, v in distribution.items() if z >= 4)
    return {"easy": easy, "moderate": moderate, "hard": hard}


def streaks(active_days: Sequence[bool]) -> tuple[int, int]:
    """``(current, longest)`` streak of consecutive active days."""
    longest = current = 0
    for active in active_days:
        current = current + 1 if active else 0
        longest = max(longest, current)
    trailing = 0
    for active in reversed(active_days):
        if not active:
            break
        trailing += 1
    return trailing, longest
