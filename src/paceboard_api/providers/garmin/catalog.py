"""The Garmin tool map: which MCP tools Paceboard calls, and how.

Every entry is **read-only by construction** — :data:`MUTATING_PREFIXES` and
:data:`MUTATING_TOOLS` are asserted against the catalog at import time, so a
tool that creates, uploads, edits, schedules, sets, logs, imports or deletes
anything can never be added here by accident.

Fields per entry:

``category``   grouping used by the sync orchestrator and the UI
``scope``      daily | range | activity | account — decides how args are built
``cadence``    fast (~15 min) | daily | weekly | per_activity | on_demand
``handler``    the normalizer in :mod:`paceboard_api.ingest.normalize_garmin`
``args``       expected argument names, for validation and documentation
``max_range_days``  provider-enforced window cap, where one exists

To add a tool: append an entry here, write (or reuse) the handler, and it is
picked up by discovery on the next start. Nothing else needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SCHEMA_VERSION = "1"

# Any tool whose name starts with one of these is a mutation and is forbidden.
MUTATING_PREFIXES = (
    "set_",
    "add_",
    "create_",
    "update_",
    "delete_",
    "log_",
    "upload_",
    "import_",
    "schedule_",
    "unschedule_",
    "upsert_",
    "remove_",
    "request_",
)

# Read-shaped names that nonetheless write or leave the process (downloads write
# files to disk; they are excluded from the allowlist too).
MUTATING_TOOLS = frozenset(
    {
        "download_activity_file",
        "download_course_gpx",
        "download_workout",
    }
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    scope: str
    cadence: str
    handler: Optional[str] = None
    enabled: bool = True
    args: tuple[str, ...] = ()
    max_range_days: Optional[int] = None
    notes: str = ""
    extra_args: dict[str, object] = field(default_factory=dict)


def _t(name, category, scope, cadence, handler=None, args=(), **kw) -> ToolSpec:
    return ToolSpec(
        name=name, category=category, scope=scope, cadence=cadence,
        handler=handler, args=tuple(args), **kw
    )


TOOL_SPECS: tuple[ToolSpec, ...] = (
    # --- Activities ------------------------------------------------------
    _t("get_activities_by_date", "activities", "range", "fast", "activities_list",
       ("start_date", "end_date", "page", "page_size"),
       extra_args={"page_size": 100}),
    _t("get_activity", "activities", "activity", "per_activity", "activity_detail",
       ("activity_id",)),
    _t("get_activity_splits", "activities", "activity", "per_activity", "activity_laps",
       ("activity_id",)),
    _t("get_activity_typed_splits", "activities", "activity", "per_activity",
       "activity_typed_splits", ("activity_id",)),
    _t("get_activity_split_summaries", "activities", "activity", "per_activity",
       "activity_split_summaries", ("activity_id",)),
    _t("get_activity_hr_in_timezones", "activities", "activity", "per_activity",
       "activity_hr_zones", ("activity_id",)),
    _t("get_activity_power_in_timezones", "activities", "activity", "per_activity",
       "activity_power_zones", ("activity_id",)),
    _t("get_activity_weather", "activities", "activity", "per_activity",
       "activity_weather", ("activity_id",)),
    _t("get_activity_gear", "activities", "activity", "per_activity",
       "activity_gear", ("activity_id",)),
    _t("get_activity_exercise_sets", "activities", "activity", "per_activity",
       "activity_exercise_sets", ("activity_id",)),
    _t("get_training_effect", "activities", "activity", "per_activity",
       "activity_training_effect", ("activity_id",)),
    _t("get_activity_fit_messages", "activities", "activity", "per_activity",
       "activity_streams", ("activity_id", "message_types", "include_records",
                            "message_offset", "message_limit"),
       notes="Per-sample FIT record stream; paged via message_offset."),

    # --- Daily health ----------------------------------------------------
    _t("get_stats", "daily_health", "daily", "fast", "daily_stats", ("date",)),
    _t("get_heart_rates_summary", "daily_health", "daily", "fast", "heart_rate_summary",
       ("date",)),
    _t("get_sleep_summary", "daily_health", "daily", "daily", "sleep_summary", ("date",)),
    _t("get_sleep_summary_range", "daily_health", "range", "daily", "sleep_range",
       ("start_date", "end_date"), max_range_days=30),
    _t("get_stress_summary", "daily_health", "daily", "daily", "stress_summary", ("date",)),
    _t("get_hrv_data", "daily_health", "daily", "daily", "hrv_daily",
       ("date", "return_timeseries")),
    _t("get_hrv_trend", "daily_health", "range", "daily", "hrv_trend",
       ("start_date", "end_date"), max_range_days=30),
    _t("get_training_readiness", "daily_health", "daily", "fast", "training_readiness",
       ("date",)),
    _t("get_morning_training_readiness", "daily_health", "daily", "daily",
       "training_readiness", ("date",)),
    _t("get_body_battery", "daily_health", "range", "fast", "body_battery",
       ("start_date", "end_date"), max_range_days=30),
    _t("get_respiration_summary", "daily_health", "daily", "daily", "respiration_summary",
       ("date",)),
    _t("get_respiration_trend", "daily_health", "range", "daily", "respiration_trend",
       ("start_date", "end_date"), max_range_days=30),
    _t("get_spo2_data", "daily_health", "daily", "daily", "spo2", ("date",)),
    _t("get_daily_steps", "daily_health", "range", "daily", "daily_steps",
       ("start_date", "end_date")),
    _t("get_weekly_steps", "daily_health", "range", "weekly", "weekly_steps",
       ("end_date", "weeks"), extra_args={"weeks": 8}),
    _t("get_weekly_stress", "daily_health", "range", "weekly", "weekly_stress",
       ("end_date", "weeks"), extra_args={"weeks": 8}),
    _t("get_weekly_intensity_minutes", "daily_health", "range", "weekly",
       "weekly_intensity", ("end_date", "weeks"), extra_args={"weeks": 8}),
    _t("get_body_composition", "daily_health", "range", "daily", "body_composition",
       ("start_date", "end_date")),
    _t("get_weigh_ins", "daily_health", "range", "daily", "weigh_ins",
       ("start_date", "end_date")),

    # --- Training & performance -----------------------------------------
    _t("get_training_status", "training", "daily", "daily", "training_status", ("date",)),
    _t("get_training_load_trend", "training", "range", "daily", "training_load_trend",
       ("start_date", "end_date")),
    _t("get_training_load_balance", "training", "daily", "daily", "training_load_balance",
       ("date",)),
    _t("get_vo2max_trend", "training", "range", "daily", "vo2max_trend",
       ("start_date", "end_date")),
    _t("get_running_tolerance", "training", "daily", "daily", "running_tolerance",
       ("date",)),
    _t("get_running_tolerance_trend", "training", "range", "weekly",
       "running_tolerance_trend", ("start_date", "end_date", "aggregation"),
       extra_args={"aggregation": "weekly"}),
    _t("get_acclimation", "training", "daily", "daily", "acclimation", ("date",)),
    _t("get_lactate_threshold", "training", "account", "daily", "lactate_threshold", ()),
    _t("get_cycling_ftp", "training", "account", "daily", "cycling_ftp", ()),
    _t("get_race_predictions", "training", "account", "daily", "race_predictions", ()),
    _t("get_endurance_score", "training", "range", "daily", "endurance_score",
       ("start_date", "end_date")),
    _t("get_hill_score", "training", "range", "daily", "hill_score",
       ("start_date", "end_date")),
    _t("get_fitnessage_data", "training", "daily", "weekly", "fitness_age",
       ("date", "details")),
    _t("get_progress_summary_between_dates", "training", "range", "weekly",
       "progress_summary", ("start_date", "end_date", "metric"),
       extra_args={"metric": "duration"}),

    # --- Account / device context ---------------------------------------
    _t("get_user_profile", "account", "account", "daily", "user_profile", ()),
    _t("get_unit_system", "account", "account", "daily", "unit_system", ()),
    _t("get_heart_rate_zones", "account", "account", "daily", "hr_zones", ("sport",)),
    _t("get_devices", "account", "account", "daily", "devices", ()),
    _t("get_device_last_used", "account", "account", "daily", "device_last_used", ()),
    _t("get_primary_training_device", "account", "account", "daily",
       "primary_training_device", ()),
    _t("get_gear", "account", "account", "daily", "gear", ("include_stats",),
       extra_args={"include_stats": True}),
    _t("get_personal_record", "account", "account", "daily", "personal_records", ()),
    _t("get_calendar_events", "account", "range", "weekly", "calendar_events",
       ("start_date", "end_date")),

    # --- On-demand only (Data Explorer; never scheduled) ------------------
    _t("get_activities_fordate", "activities", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_activity_types", "activities", "account", "on_demand", None, (), enabled=False),
    _t("count_activities", "activities", "account", "on_demand", None, (), enabled=False),
    _t("get_all_day_stress", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_body_battery_events", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_floors", "daily_health", "daily", "on_demand", None, ("date",), enabled=False),
    _t("get_rhr_day", "daily_health", "daily", "on_demand", None, ("date",), enabled=False),
    _t("get_heart_rates", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_sleep_data", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_stress_data", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_respiration_data", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_steps_data", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_stats_and_body", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_user_summary", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_hydration_data", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_blood_pressure", "daily_health", "range", "on_demand", None,
       ("start_date", "end_date"), enabled=False),
    _t("get_daily_weigh_ins", "daily_health", "daily", "on_demand", None, ("date",),
       enabled=False),
    _t("get_power_duration_curve", "training", "account", "on_demand", None,
       ("num_activities", "activity_type"), enabled=False),
    _t("get_activity_fit_data", "activities", "activity", "on_demand", None,
       ("activity_id", "include_records"), enabled=False),
    _t("get_goals", "account", "account", "on_demand", None, ("goal_type",), enabled=False),
    _t("get_earned_badges", "account", "account", "on_demand", None, (), enabled=False),
    _t("get_device_settings", "account", "account", "on_demand", None, ("device_id",),
       enabled=False),
    _t("get_device_alarms", "account", "account", "on_demand", None, (), enabled=False),
    _t("get_userprofile_settings", "account", "account", "on_demand", None, (),
       enabled=False),
    _t("get_full_name", "account", "account", "on_demand", None, (), enabled=False),
    _t("get_workouts", "account", "account", "on_demand", None, (), enabled=False),
    _t("get_scheduled_workouts", "account", "range", "on_demand", None,
       ("start_date", "end_date"), enabled=False),
    _t("get_courses", "account", "account", "on_demand", None, (), enabled=False),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}

#: Every tool Paceboard may ever invoke — used to build the safe launch
#: allowlist and to reject arbitrary tool names from the Data Explorer.
READ_ONLY_ALLOWLIST: tuple[str, ...] = tuple(sorted(TOOLS_BY_NAME))

#: Tools the scheduler drives. On-demand entries are reachable only through an
#: explicit Data Explorer request.
SCHEDULED_TOOLS: tuple[ToolSpec, ...] = tuple(s for s in TOOL_SPECS if s.enabled)

CATEGORIES: tuple[str, ...] = ("activities", "daily_health", "training", "account")


def is_mutating(name: str) -> bool:
    lowered = name.lower()
    return lowered in MUTATING_TOOLS or lowered.startswith(MUTATING_PREFIXES)


def _assert_read_only() -> None:
    offenders = sorted(n for n in TOOLS_BY_NAME if is_mutating(n))
    if offenders:
        raise RuntimeError(
            "Garmin tool catalog contains mutating tools, refusing to load: "
            + ", ".join(offenders)
        )


_assert_read_only()


def specs_for_cadence(*cadences: str) -> list[ToolSpec]:
    wanted = set(cadences)
    return [s for s in SCHEDULED_TOOLS if s.cadence in wanted]


def specs_for_category(category: str) -> list[ToolSpec]:
    return [s for s in SCHEDULED_TOOLS if s.category == category]
