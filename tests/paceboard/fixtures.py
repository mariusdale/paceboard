"""Realistic provider fixtures.

The Garmin payloads reproduce the exact shapes the installed MCP server returns
(curated JSON for most tools, bare sentences for the several failure modes), and
the Strava payloads follow the documented v3 response shapes. Values are
synthetic — no real health data lives in the test suite.
"""

from __future__ import annotations

import json
from typing import Any

# --- Garmin: JSON responses ------------------------------------------------

GARMIN_STATS = {
    "date": "2026-08-20",
    "total_steps": 9124,
    "daily_step_goal": 10000,
    "distance_meters": 7310,
    "floors_ascended": 12.0,
    "total_calories": 2870.0,
    "active_calories": 610.0,
    "bmr_calories": 2260.0,
    "highly_active_seconds": 1800,
    "active_seconds": 9000,
    "sedentary_seconds": 40000,
    "sleeping_seconds": 27000,
    "moderate_intensity_minutes": 34,
    "vigorous_intensity_minutes": 11,
    "intensity_minutes_goal": 150,
    "min_heart_rate_bpm": 44,
    "max_heart_rate_bpm": 152,
    "resting_heart_rate_bpm": 48,
    "last_7_days_avg_resting_hr": 49,
    "avg_stress_level": 27,
    "max_stress_level": 84,
    "stress_qualifier": "BALANCED",
    "body_battery_charged": 62,
    "body_battery_drained": 55,
    "body_battery_highest": 88,
    "body_battery_lowest": 26,
    "avg_waking_respiration": 14.2,
    "highest_respiration": 20.0,
    "lowest_respiration": 10.5,
}

GARMIN_SLEEP_SUMMARY = {
    "sleep_seconds": 27180,
    "nap_seconds": 0,
    "sleep_start": 1755380000000,
    "sleep_end": 1755407180000,
    "sleep_score": 82,
    "sleep_score_qualifier": "GOOD",
    "deep_sleep_seconds": 4980,
    "light_sleep_seconds": 15600,
    "rem_sleep_seconds": 6000,
    "awake_seconds": 600,
    "awake_count": 2,
    "avg_sleep_stress": 18.0,
    "avg_overnight_hrv": 71.0,
    "sleep_hours": 7.55,
}

GARMIN_SLEEP_RANGE = {
    "start_date": "2026-08-18",
    "end_date": "2026-08-20",
    "nights_requested": 3,
    "nights_returned": 2,
    "nights": [
        {**GARMIN_SLEEP_SUMMARY, "date": "2026-08-19", "sleep_score": 74},
        {**GARMIN_SLEEP_SUMMARY, "date": "2026-08-20", "sleep_score": 82},
    ],
}

GARMIN_HRV = {
    "date": "2026-08-20",
    "last_night_avg_hrv_ms": 71,
    "last_night_5min_high_hrv_ms": 95,
    "weekly_avg_hrv_ms": 68,
    "baseline_balanced_low_ms": 58,
    "baseline_balanced_upper_ms": 82,
    "baseline_low_upper_ms": 52,
    "status": "BALANCED",
    "feedback": "Your HRV is in your normal range.",
    "sleep_start": "2026-08-19T22:00:00",
    "sleep_end": "2026-08-20T05:30:00",
}

GARMIN_STRESS = {
    "date": "2026-08-20",
    "max_stress_level": 84,
    "avg_stress_level": 27,
    "rest_percent": 41.0,
    "low_stress_percent": 33.0,
    "medium_stress_percent": 20.0,
    "high_stress_percent": 6.0,
    "data_points_count": 960,
}

GARMIN_TRAINING_STATUS = {
    "date": "2026-08-20",
    "training_status": 3,
    "training_status_feedback": "PRODUCTIVE",
    "fitness_trend": 1,
    "acute_load": 412,
    "chronic_load": 380,
    "load_ratio": 1.08,
    "acwr_status": "OPTIMAL",
    "acwr_percent": 62,
    "optimal_chronic_load_min": 320.0,
    "optimal_chronic_load_max": 520.0,
    "monthly_load_aerobic_low": 210.0,
    "monthly_load_aerobic_high": 90.0,
    "monthly_load_anaerobic": 30.0,
    "training_balance_feedback": "Keep the aerobic base going.",
}

GARMIN_LOAD_TREND = {
    "start_date": "2026-08-18",
    "end_date": "2026-08-20",
    "days_with_data": 3,
    "trend": [
        {"date": "2026-08-18", "atl": 400, "ctl": 372, "tsb": -28, "acwr": 1.07,
         "acwr_status": "OPTIMAL", "acwr_percent": 60, "training_status": "PRODUCTIVE",
         "training_status_code": 3, "fitness_trend": 1, "vo2_max": 52.0},
        {"date": "2026-08-19", "atl": 406, "ctl": 376, "tsb": -30, "acwr": 1.08,
         "acwr_status": "OPTIMAL", "acwr_percent": 61, "training_status": "PRODUCTIVE",
         "training_status_code": 3, "fitness_trend": 1, "vo2_max": 52.0},
        {"date": "2026-08-20", "atl": 412, "ctl": 380, "tsb": -32, "acwr": 1.08,
         "acwr_status": "OPTIMAL", "acwr_percent": 62, "training_status": "PRODUCTIVE",
         "training_status_code": 3, "fitness_trend": 1, "vo2_max": 52.3},
    ],
}

GARMIN_VO2MAX_TREND = {
    "start_date": "2026-08-18",
    "end_date": "2026-08-20",
    "data_points": 2,
    "first_vo2_max": 52.0,
    "latest_vo2_max": 52.3,
    "change": 0.3,
    "sport": "running",
    "trend": [
        {"date": "2026-08-18", "vo2_max": 52.0, "source": "device"},
        {"date": "2026-08-20", "vo2_max": 52.3, "source": "device"},
    ],
}

GARMIN_ACTIVITIES = {
    "count": 2,
    "page": 0,
    "page_size": 100,
    "has_more": False,
    "date_range": {"start": "2026-08-18", "end": "2026-08-20"},
    "activities": [
        {
            "id": 24188138095,
            "name": "Morning Run",
            "type": "running",
            "event_type": "uncategorized",
            "start_time": "2026-08-20T05:32:11",
            "distance_meters": 10120.0,
            "duration_seconds": 3180.0,
            "calories": 720.0,
            "avg_hr_bpm": 148.0,
            "max_hr_bpm": 172.0,
            "elevation_gain_meters": 96.0,
            "elevation_loss_meters": 94.0,
        },
        {
            "id": 24188138096,
            "name": "Evening Ride",
            "type": "cycling",
            "event_type": "uncategorized",
            "start_time": "2026-08-19T16:05:00",
            "distance_meters": 32400.0,
            "duration_seconds": 4500.0,
            "calories": 890.0,
            "avg_hr_bpm": 131.0,
            "max_hr_bpm": 165.0,
            "elevation_gain_meters": 310.0,
            "elevation_loss_meters": 308.0,
        },
    ],
}

GARMIN_ACTIVITY_DETAIL = {
    "id": 24188138095,
    "name": "Morning Run",
    "type": "running",
    "event_type": "uncategorized",
    "parent_type": 17,
    "start_time_local": "2026-08-20T07:32:11",
    "start_time_gmt": "2026-08-20T05:32:11",
    "duration_seconds": 3180.0,
    "moving_duration_seconds": 3140.0,
    "elapsed_duration_seconds": 3200.0,
    "distance_meters": 10120.0,
    "avg_speed_mps": 3.18,
    "max_speed_mps": 4.61,
    "avg_hr_bpm": 148.0,
    "max_hr_bpm": 172.0,
    "min_hr_bpm": 92.0,
    "calories": 720.0,
    "bmr_calories": 90.0,
    "training_effect": 3.4,
    "anaerobic_training_effect": 1.1,
    "training_effect_label": "TEMPO",
    "training_load": 118.0,
    "moderate_intensity_minutes": 12,
    "vigorous_intensity_minutes": 30,
    "elevation_gain_meters": 96.0,
    "elevation_loss_meters": 94.0,
    "max_elevation_meters": 84.0,
    "min_elevation_meters": 12.0,
    "lap_count": 10,
    "has_splits": True,
    "device_manufacturer": "GARMIN",
}

GARMIN_RIDE_DETAIL = {
    **{k: v for k, v in GARMIN_ACTIVITY_DETAIL.items()},
    "id": 24188138096,
    "name": "Evening Ride",
    "type": "cycling",
    "start_time_local": "2026-08-19T18:05:00",
    "start_time_gmt": "2026-08-19T16:05:00",
    "duration_seconds": 4500.0,
    "moving_duration_seconds": 4380.0,
    "distance_meters": 32400.0,
    "avg_speed_mps": 7.2,
    "avg_hr_bpm": 131.0,
    "max_hr_bpm": 165.0,
    "training_load": 96.0,
    "elevation_gain_meters": 310.0,
    "elevation_loss_meters": 308.0,
}

GARMIN_ACTIVITY_SPLITS = {
    "activity_id": 24188138095,
    "lap_count": 2,
    "laps": [
        {"lap_number": 1, "start_time": "2026-08-20T05:32:11", "distance_meters": 5000.0,
         "duration_seconds": 1580.0, "moving_duration_seconds": 1570.0,
         "avg_speed_mps": 3.16, "avg_moving_speed_mps": 3.18, "max_speed_mps": 4.2,
         "avg_hr_bpm": 145.0, "max_hr_bpm": 160.0, "calories": 350.0,
         "bmr_calories": 45.0, "intensity_type": "ACTIVE",
         "elevation_gain_meters": 48.0, "elevation_loss_meters": 46.0},
        {"lap_number": 2, "start_time": "2026-08-20T05:58:31", "distance_meters": 5120.0,
         "duration_seconds": 1600.0, "moving_duration_seconds": 1570.0,
         "avg_speed_mps": 3.2, "avg_moving_speed_mps": 3.26, "max_speed_mps": 4.61,
         "avg_hr_bpm": 151.0, "max_hr_bpm": 172.0, "calories": 370.0,
         "bmr_calories": 45.0, "intensity_type": "ACTIVE",
         "elevation_gain_meters": 48.0, "elevation_loss_meters": 48.0},
    ],
}

GARMIN_HR_ZONES_IN_ACTIVITY = [
    {"zoneNumber": 1, "secsInZone": 300.0, "zoneLowBoundary": 93},
    {"zoneNumber": 2, "secsInZone": 900.0, "zoneLowBoundary": 111},
    {"zoneNumber": 3, "secsInZone": 1500.0, "zoneLowBoundary": 130},
    {"zoneNumber": 4, "secsInZone": 420.0, "zoneLowBoundary": 148},
    {"zoneNumber": 5, "secsInZone": 60.0, "zoneLowBoundary": 167},
]

GARMIN_USER_PROFILE = {
    "id": 55512345,
    "userData": {
        "gender": "MALE",
        "weight": 74500.0,
        "height": 181.0,
        "birthDate": "1994-04-12",
        "measurementSystem": "metric",
        "vo2MaxRunning": 52.3,
        "vo2MaxCycling": None,
        "lactateThresholdSpeed": 3.61,
        "lactateThresholdHeartRate": 168,
    },
}

GARMIN_HR_ZONE_CONFIG = [
    {"trainingMethod": "HR_RESERVE", "restingHeartRateUsed": 48,
     "lactateThresholdHeartRateUsed": 168, "zone1Floor": 93, "zone2Floor": 111,
     "zone3Floor": 130, "zone4Floor": 148, "zone5Floor": 167,
     "maxHeartRateUsed": 190, "restingHrAutoUpdateUsed": True,
     "sport": "DEFAULT", "changeState": "NO_CHANGE"},
]

GARMIN_DEVICES = [
    {"device_id": 3312345678, "device_name": "Forerunner 965",
     "model": "FR965", "serial_number": "3312345678"},
]

GARMIN_PERSONAL_RECORDS = [
    {"record_type": "Fastest 1K", "type_id": 1, "value": "3:41", "raw_value": 221.0,
     "date": None, "activity_id": 24188138095},
    {"record_type": "Longest Run", "type_id": 7, "value": "21.10 km",
     "raw_value": 21100.0, "date": "2026-05-04", "activity_id": 24188138000},
]

GARMIN_BODY_BATTERY = [
    {"date": "2026-08-20", "charged": 62, "drained": 55,
     "events": [{"type": "sleep", "start_time": "2026-08-19T22:00:00",
                 "duration_minutes": 450.0, "body_battery_impact": 62,
                 "feedback": "Good recovery"}],
     "current_feedback": "Recovering well", "body_battery_level": "HIGH"},
]

#: A FIT record page as returned by get_activity_fit_messages.
GARMIN_FIT_RECORDS = {
    "activity_id": 24188138095,
    "source": "garmin_original_fit",
    "fit_size_bytes": 184245,
    "message_counts": {"record": 4},
    "returned_message_counts": {"record": 4},
    "record_stream": {"included": True, "total_count": 4, "returned_count": 4},
    "pagination": {"total_eligible_count": 4, "returned_count": 4, "offset": 0,
                   "limit": 1000, "next_offset": 4},
    "messages": [
        {
            "message_index": i,
            "type": "record",
            "global_message_number": 20,
            "fields": [
                {"name": "timestamp", "value": f"2026-08-20T05:32:{11 + i:02d}",
                 "base_type": "uint32", "raw_value": 1155000000 + i},
                {"name": "position_lat", "value": None, "units": "semicircles",
                 "raw_value": 715827882 + i * 100},
                {"name": "position_long", "value": None, "units": "semicircles",
                 "raw_value": 127775692 + i * 100},
                {"name": "distance", "value": float(i * 3), "units": "m",
                 "raw_value": i * 300},
                {"name": "enhanced_altitude", "value": 20.0 + i, "units": "m",
                 "raw_value": 2600 + i},
                {"name": "heart_rate", "value": 140 + i, "units": "bpm",
                 "raw_value": 140 + i},
                {"name": "enhanced_speed", "value": 3.1 + i * 0.05, "units": "m/s",
                 "raw_value": 3100 + i * 50},
                {"name": "cadence", "value": 86 + i, "units": "rpm", "raw_value": 86 + i},
                {"name": "unknown_107", "value": 0, "raw_value": 0},
            ],
        }
        for i in range(4)
    ],
}

# --- Garmin: plain-text responses -----------------------------------------

GARMIN_TEXT_RESPONSES: dict[str, str] = {
    "no_gear": "No gear found.",
    "no_readiness": "No training readiness data found for 2026-09-01",
    "no_weight": "No weight measurements found between 2026-07-04 and 2026-09-02.",
    "unsupported": "Your device does not support this metric.",
    "range_too_large": "Date range too large (61 days). Maximum is 30 days.",
    "tool_error": "Error retrieving endurance score data: 'NoneType' object has no attribute 'get'",
    "rate_limited": "Garmin rate limit hit. Wait a few minutes before retrying.",
    "auth_expired": "Garmin authentication expired. Re-run 'garmin-mcp-auth' to refresh your tokens.",
    "timeout": "Garmin request 'get_stats' did not return within 90s and was abandoned.",
}

#: Valid JSON that nonetheless carries nothing usable.
GARMIN_EMPTY_JSON = [
    {"date": "2026-08-31"},
    {"start_date": "2026-08-01", "end_date": "2026-08-31", "daily_scores": []},
    [],
    {},
]

# --- Strava ----------------------------------------------------------------

STRAVA_TOKEN_RESPONSE = {
    "token_type": "Bearer",
    "expires_at": 1_900_000_000,
    "expires_in": 21600,
    "refresh_token": "REFRESH_TOKEN_PLACEHOLDER",
    "access_token": "ACCESS_TOKEN_PLACEHOLDER",
    "athlete": {"id": 987654, "firstname": "Test", "lastname": "Athlete"},
}

STRAVA_ATHLETE = {
    "id": 987654,
    "firstname": "Test",
    "lastname": "Athlete",
    "sex": "M",
    "weight": 74.5,
    "measurement_preference": "meters",
    "bikes": [{"id": "b123", "name": "Gravel", "distance": 1_204_000, "retired": False}],
    "shoes": [{"id": "g456", "name": "Trainers", "distance": 402_000, "retired": False}],
}

STRAVA_ACTIVITY = {
    "id": 15123456789,
    "name": "Morning Run",
    "sport_type": "Run",
    "type": "Run",
    "start_date": "2026-08-20T05:33:00Z",
    "start_date_local": "2026-08-20T07:33:00Z",
    "utc_offset": 7200,
    "elapsed_time": 3200,
    "moving_time": 3140,
    "distance": 10118.0,
    "total_elevation_gain": 95.0,
    "average_speed": 3.22,
    "max_speed": 4.6,
    "average_heartrate": 147.5,
    "max_heartrate": 171.0,
    "average_cadence": 86.0,
    "calories": 715.0,
    "start_latlng": [59.9139, 10.7522],
    "external_id": "garmin_push_24188138095",
    "upload_id": 16000000001,
    "gear_id": "g456",
    "trainer": False,
    "commute": False,
    "manual": False,
}

STRAVA_STREAMS = {
    "time": {"data": [0, 1, 2, 3], "series_type": "distance"},
    "distance": {"data": [0.0, 3.2, 6.4, 9.6], "series_type": "distance"},
    "latlng": {"data": [[59.9139, 10.7522], [59.9140, 10.7523],
                        [59.9141, 10.7524], [59.9142, 10.7525]],
               "series_type": "distance"},
    "heartrate": {"data": [140, 141, 142, 143], "series_type": "distance"},
    "altitude": {"data": [20.0, 21.0, 22.0, 23.0], "series_type": "distance"},
    "velocity_smooth": {"data": [3.1, 3.15, 3.2, 3.25], "series_type": "distance"},
    "moving": {"data": [True, True, True, True], "series_type": "distance"},
}

STRAVA_LAPS = [
    {"lap_index": 1, "start_date": "2026-08-20T05:33:00Z", "elapsed_time": 1600,
     "moving_time": 1570, "distance": 5000.0, "average_speed": 3.18,
     "max_speed": 4.2, "average_heartrate": 145.0, "max_heartrate": 160.0,
     "total_elevation_gain": 48.0},
    {"lap_index": 2, "start_date": "2026-08-20T05:59:40Z", "elapsed_time": 1600,
     "moving_time": 1570, "distance": 5118.0, "average_speed": 3.26,
     "max_speed": 4.6, "average_heartrate": 150.0, "max_heartrate": 171.0,
     "total_elevation_gain": 47.0},
]

STRAVA_ZONES = [
    {"type": "heartrate", "distribution_buckets": [
        {"min": 0, "max": 110, "time": 300},
        {"min": 110, "max": 130, "time": 900},
        {"min": 130, "max": 148, "time": 1500},
        {"min": 148, "max": 167, "time": 420},
        {"min": 167, "max": -1, "time": 60},
    ]},
]

STRAVA_RATE_LIMIT_HEADERS = {
    "X-RateLimit-Limit": "200,2000",
    "X-RateLimit-Usage": "47,1203",
    "X-ReadRateLimit-Limit": "100,1000",
    "X-ReadRateLimit-Usage": "12,340",
}


def as_text(payload: Any) -> str:
    """Render a fixture the way the MCP server does: JSON inside text content."""
    return json.dumps(payload)
