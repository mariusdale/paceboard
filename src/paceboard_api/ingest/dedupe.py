"""Cross-provider activity matching.

A ride recorded on a Garmin watch usually shows up in Strava a few minutes
later. Both raw records are kept forever; what deduplication decides is whether
they describe the *same session* and should therefore share one canonical
activity row.

Scoring is deliberately conservative and explainable:

* an exact provider link (Strava's ``external_id`` naming the Garmin activity,
  or a shared ``upload_id``) is decisive on its own;
* otherwise the pair must agree on sport family, start within a tolerance, and —
  where both report them — duration and distance within tolerances;
* the resulting score decides automatically only at the extremes. Anything in
  between becomes a :class:`DuplicateCandidate` for the user to confirm in the
  Activities view. Nothing is ever discarded either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.models import Activity, ActivitySourceRecord, DuplicateCandidate
from ..logging_conf import get_logger
from .activities import rebuild_canonical

log = get_logger("paceboard.dedupe")

AUTO_MERGE_SCORE = 0.85
REVIEW_SCORE = 0.55

#: Sports that may legitimately be labelled differently by the two providers.
COMPATIBLE_SPORTS: tuple[frozenset[str], ...] = (
    frozenset({"run", "hike", "walk"}),
    frozenset({"ride", "other"}),
    frozenset({"cardio", "strength", "other"}),
    frozenset({"row", "paddle"}),
)


@dataclass
class MatchScore:
    score: float
    reasons: dict[str, Any] = field(default_factory=dict)

    @property
    def decision(self) -> str:
        if self.score >= AUTO_MERGE_SCORE:
            return "auto"
        if self.score >= REVIEW_SCORE:
            return "review"
        return "reject"


def sports_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    return any({left, right} <= group for group in COMPATIBLE_SPORTS)


def _agreement(a: Optional[float], b: Optional[float], tolerance: float) -> Optional[float]:
    """How much two measurements agree, as 1.0 (within tolerance) down to 0.0.

    Returns ``None`` when one side did not report the value — that is neither
    agreement nor disagreement, and must not be scored as either. Beyond the
    tolerance the score decays linearly and reaches zero at four times it, so a
    provider reporting elapsed time where the other reports moving time degrades
    the match rather than destroying it.
    """
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    relative_error = abs(a - b) / max(a, b)
    if relative_error <= tolerance:
        return 1.0
    decay = 1.0 - (relative_error - tolerance) / (tolerance * 3)
    return max(0.0, decay)


#: Weights sum to 1.0. Start proximity dominates because two providers recording
#: the same session always agree on when it began, while their distance and
#: duration routinely differ by a few percent.
W_START = 0.45
W_SPORT = 0.15
W_DURATION = 0.20
W_DISTANCE = 0.20

#: Credit given when a measurement is simply absent on one side.
NEUTRAL = 0.5


def _explicit_link(left: ActivitySourceRecord, right: ActivitySourceRecord) -> Optional[str]:
    for a, b in ((left, right), (right, left)):
        if a.external_id and b.provider_id and b.provider_id in str(a.external_id):
            return "external_id references the other provider's activity id"
        if a.upload_id and b.upload_id and a.upload_id == b.upload_id:
            return "shared upload id"
    return None


def score_pair(
    left: ActivitySourceRecord,
    right: ActivitySourceRecord,
    settings: Optional[Settings] = None,
) -> MatchScore:
    settings = settings or get_settings()
    reasons: dict[str, Any] = {}

    if left.source == right.source:
        return MatchScore(0.0, {"rejected": "same provider"})

    link = _explicit_link(left, right)
    if link:
        return MatchScore(1.0, {"explicit_link": link})

    if not sports_compatible(left.sport, right.sport):
        return MatchScore(
            0.0, {"rejected": f"incompatible sports {left.sport}/{right.sport}"}
        )
    reasons["sport"] = (
        "exact" if left.sport == right.sport else f"compatible {left.sport}/{right.sport}"
    )

    delta = abs((left.start_time_utc - right.start_time_utc).total_seconds())
    tolerance = settings.dedupe_start_tolerance_seconds
    if delta > tolerance:
        return MatchScore(
            0.0, {"rejected": f"start times differ by {int(delta)}s (> {tolerance}s)"}
        )
    reasons["start_delta_seconds"] = int(delta)

    score = W_START * (1.0 - delta / tolerance)
    score += W_SPORT if left.sport == right.sport else W_SPORT * 0.5

    duration = _agreement(left.duration_s, right.duration_s,
                          settings.dedupe_duration_tolerance_pct)
    score += W_DURATION * (NEUTRAL if duration is None else duration)
    reasons["duration"] = (
        "not comparable" if duration is None
        else "within tolerance" if duration == 1.0
        else f"differs ({duration:.0%} agreement)"
    )

    distance = _agreement(left.distance_m, right.distance_m,
                          settings.dedupe_distance_tolerance_pct)
    score += W_DISTANCE * (NEUTRAL if distance is None else distance)
    reasons["distance"] = (
        "not comparable" if distance is None
        else "within tolerance" if distance == 1.0
        else f"differs ({distance:.0%} agreement)"
    )

    return MatchScore(max(0.0, min(1.0, score)), reasons)


def find_candidates(
    session: Session, row: ActivitySourceRecord, settings: Optional[Settings] = None
) -> list[tuple[ActivitySourceRecord, MatchScore]]:
    settings = settings or get_settings()
    window = timedelta(seconds=settings.dedupe_start_tolerance_seconds)
    others = session.execute(
        select(ActivitySourceRecord).where(
            ActivitySourceRecord.source != row.source,
            ActivitySourceRecord.start_time_utc >= row.start_time_utc - window,
            ActivitySourceRecord.start_time_utc <= row.start_time_utc + window,
        )
    ).scalars()
    scored = []
    for other in others:
        match = score_pair(row, other, settings)
        if match.score > 0:
            scored.append((other, match))
    scored.sort(key=lambda pair: pair[1].score, reverse=True)
    return scored


def merge_records(
    session: Session, keep: ActivitySourceRecord, absorb: ActivitySourceRecord
) -> Activity:
    """Point both source records at one canonical activity.

    The absorbed activity row is removed only if it has no other sources; the
    absorbed *source record* and its raw payload always survive.
    """
    from .activities import ensure_canonical

    activity = ensure_canonical(session, keep)
    stale_activity_id = absorb.activity_id
    absorb.activity_id = activity.id
    session.flush()
    for child_model_name in ("ActivityLap", "ActivitySplit", "ActivityZone", "ActivityStream"):
        model = getattr(__import__("paceboard_api.db.models", fromlist=[child_model_name]),
                        child_model_name)
        session.query(model).filter(model.source_record_id == absorb.id).update(
            {"activity_id": activity.id}
        )
    if stale_activity_id and stale_activity_id != activity.id:
        stale = session.get(Activity, stale_activity_id)
        remaining = session.execute(
            select(ActivitySourceRecord.id).where(
                ActivitySourceRecord.activity_id == stale_activity_id
            )
        ).first()
        # The now-empty canonical row goes; the source record it used to hold is
        # untouched and now belongs to the surviving activity.
        if stale is not None and remaining is None:
            session.delete(stale)
    session.flush()
    return rebuild_canonical(session, activity)


def link_source_record(
    session: Session, row: ActivitySourceRecord, settings: Optional[Settings] = None
) -> tuple[Activity, Optional[DuplicateCandidate]]:
    """Attach ``row`` to the right canonical activity, queueing uncertain matches."""
    from .activities import ensure_canonical

    settings = settings or get_settings()
    candidates = find_candidates(session, row, settings)
    pending: Optional[DuplicateCandidate] = None

    for other, match in candidates:
        if match.decision == "auto":
            if other.activity_id and other.activity_id == row.activity_id:
                break
            activity = merge_records(session, other, row)
            log.info(
                "Merged cross-provider activity",
                extra={"kept": other.source, "absorbed": row.source,
                       "score": round(match.score, 3)},
            )
            return activity, None
        if match.decision == "review" and pending is None:
            pending = _record_candidate(session, row, other, match)
            break

    return ensure_canonical(session, row), pending


def _record_candidate(
    session: Session,
    left: ActivitySourceRecord,
    right: ActivitySourceRecord,
    match: MatchScore,
) -> DuplicateCandidate:
    first, second = sorted([left, right], key=lambda r: r.id)
    existing = session.execute(
        select(DuplicateCandidate).where(
            DuplicateCandidate.left_source_record_id == first.id,
            DuplicateCandidate.right_source_record_id == second.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.score = match.score
        existing.reasons = match.reasons
        session.flush()
        return existing
    candidate = DuplicateCandidate(
        left_source_record_id=first.id,
        right_source_record_id=second.id,
        score=match.score,
        reasons=match.reasons,
    )
    session.add(candidate)
    session.flush()
    return candidate


def resolve_candidate(
    session: Session, candidate_id: int, accept: bool
) -> Optional[Activity]:
    from datetime import datetime

    candidate = session.get(DuplicateCandidate, candidate_id)
    if candidate is None:
        return None
    candidate.state = "confirmed" if accept else "rejected"
    candidate.decided_at = datetime.utcnow()
    session.flush()
    if not accept:
        return None
    left = session.get(ActivitySourceRecord, candidate.left_source_record_id)
    right = session.get(ActivitySourceRecord, candidate.right_source_record_id)
    if left is None or right is None:
        return None
    keep = left if left.source == "garmin" else right
    absorb = right if keep is left else left
    return merge_records(session, keep, absorb)
