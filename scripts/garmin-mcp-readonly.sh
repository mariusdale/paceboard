#!/usr/bin/env bash
# Start the Garmin MCP server with Paceboard's read-only tool allowlist.
#
# The allowlist below is GENERATED from src/paceboard_api/providers/garmin/catalog.py
# by scripts/generate_garmin_allowlist.py. Every entry is asserted at generation
# time not to match a mutating name pattern (set_/add_/create_/update_/delete_/
# log_/upload_/import_/schedule_/unschedule_/upsert_/remove_/request_) and not to
# be one of the download tools, so nothing exposed here can change your Garmin
# account or write to disk.
#
# Regenerate after adding a tool to the catalog:
#     uv run --extra paceboard python scripts/generate_garmin_allowlist.py
#
# Usage:
#     ./scripts/garmin-mcp-readonly.sh          # http://127.0.0.1:8000/mcp
#     GARMIN_MCP_PORT=8010 ./scripts/garmin-mcp-readonly.sh
#
# Authenticate once first with:  uv run garmin-mcp-auth

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Loopback only: this transport performs no authentication, and the tools it
# exposes read your entire Garmin health history.
export GARMIN_MCP_TRANSPORT="${GARMIN_MCP_TRANSPORT:-streamable-http}"
export GARMIN_MCP_HOST="${GARMIN_MCP_HOST:-127.0.0.1}"
export GARMIN_MCP_PORT="${GARMIN_MCP_PORT:-8000}"

# 82 read-only tools.
GARMIN_ENABLED_TOOLS=$(printf '%s' \
  "count_activities,get_acclimation,get_activities_by_date,get_activities_fordate" \
  "get_activity,get_activity_exercise_sets,get_activity_fit_data" \
  "get_activity_fit_messages,get_activity_gear,get_activity_hr_in_timezones" \
  "get_activity_power_in_timezones,get_activity_split_summaries" \
  "get_activity_splits,get_activity_typed_splits,get_activity_types" \
  "get_activity_weather,get_all_day_stress,get_blood_pressure,get_body_battery" \
  "get_body_battery_events,get_body_composition,get_calendar_events,get_courses" \
  "get_cycling_ftp,get_daily_steps,get_daily_weigh_ins,get_device_alarms" \
  "get_device_last_used,get_device_settings,get_devices,get_earned_badges" \
  "get_endurance_score,get_fitnessage_data,get_floors,get_full_name,get_gear" \
  "get_goals,get_heart_rate_zones,get_heart_rates,get_heart_rates_summary" \
  "get_hill_score,get_hrv_data,get_hrv_trend,get_hydration_data" \
  "get_lactate_threshold,get_morning_training_readiness,get_personal_record" \
  "get_power_duration_curve,get_primary_training_device" \
  "get_progress_summary_between_dates,get_race_predictions,get_respiration_data" \
  "get_respiration_summary,get_respiration_trend,get_rhr_day" \
  "get_running_tolerance,get_running_tolerance_trend,get_scheduled_workouts" \
  "get_sleep_data,get_sleep_summary,get_sleep_summary_range,get_spo2_data" \
  "get_stats,get_stats_and_body,get_steps_data,get_stress_data,get_stress_summary" \
  "get_training_effect,get_training_load_balance,get_training_load_trend" \
  "get_training_readiness,get_training_status,get_unit_system,get_user_profile" \
  "get_user_summary,get_userprofile_settings,get_vo2max_trend" \
  "get_weekly_intensity_minutes,get_weekly_steps,get_weekly_stress,get_weigh_ins" \
  "get_workouts")
export GARMIN_ENABLED_TOOLS

echo "Garmin MCP (read-only, 82 tools)"
echo "  endpoint : http://${GARMIN_MCP_HOST}:${GARMIN_MCP_PORT}/mcp"
echo "  health   : http://${GARMIN_MCP_HOST}:${GARMIN_MCP_PORT}/healthz"

exec uv run --python 3.12 garmin-mcp
