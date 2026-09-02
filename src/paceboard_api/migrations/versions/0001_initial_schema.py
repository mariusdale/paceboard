"""Initial Paceboard schema.

Creates the full normalized store: provider plumbing, raw payloads, activities
and their child records, daily health, training/performance metrics and derived
metrics. Written to run against a completely empty database.

Revision ID: 0001_initial
Revises: 
Create Date: 2026-09-02 09:48:55.645487+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('athletes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('sex', sa.String(length=16), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('height_cm', sa.Float(), nullable=True),
    sa.Column('weight_kg', sa.Float(), nullable=True),
    sa.Column('measurement_system', sa.String(length=16), nullable=True),
    sa.Column('vo2max_running', sa.Float(), nullable=True),
    sa.Column('vo2max_cycling', sa.Float(), nullable=True),
    sa.Column('lactate_threshold_hr', sa.Integer(), nullable=True),
    sa.Column('lactate_threshold_speed_mps', sa.Float(), nullable=True),
    sa.Column('ftp_watts', sa.Integer(), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'provider_id', name='uq_athlete_source')
    )
    op.create_table('body_battery_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('charged', sa.Integer(), nullable=True),
    sa.Column('drained', sa.Integer(), nullable=True),
    sa.Column('highest', sa.Integer(), nullable=True),
    sa.Column('lowest', sa.Integer(), nullable=True),
    sa.Column('level_label', sa.String(length=48), nullable=True),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('events', sa.JSON(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_bb_day')
    )
    op.create_table('body_composition',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('weight_kg', sa.Float(), nullable=True),
    sa.Column('bmi', sa.Float(), nullable=True),
    sa.Column('body_fat_pct', sa.Float(), nullable=True),
    sa.Column('body_water_pct', sa.Float(), nullable=True),
    sa.Column('bone_mass_kg', sa.Float(), nullable=True),
    sa.Column('muscle_mass_kg', sa.Float(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_body_comp_day')
    )
    op.create_table('daily_health',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('steps', sa.Integer(), nullable=True),
    sa.Column('step_goal', sa.Integer(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('floors_ascended', sa.Float(), nullable=True),
    sa.Column('total_calories', sa.Float(), nullable=True),
    sa.Column('active_calories', sa.Float(), nullable=True),
    sa.Column('bmr_calories', sa.Float(), nullable=True),
    sa.Column('moderate_intensity_minutes', sa.Integer(), nullable=True),
    sa.Column('vigorous_intensity_minutes', sa.Integer(), nullable=True),
    sa.Column('intensity_minutes_goal', sa.Integer(), nullable=True),
    sa.Column('resting_hr', sa.Integer(), nullable=True),
    sa.Column('min_hr', sa.Integer(), nullable=True),
    sa.Column('max_hr', sa.Integer(), nullable=True),
    sa.Column('avg_hr', sa.Float(), nullable=True),
    sa.Column('rhr_7day_avg', sa.Integer(), nullable=True),
    sa.Column('avg_stress', sa.Integer(), nullable=True),
    sa.Column('max_stress', sa.Integer(), nullable=True),
    sa.Column('body_battery_high', sa.Integer(), nullable=True),
    sa.Column('body_battery_low', sa.Integer(), nullable=True),
    sa.Column('body_battery_charged', sa.Integer(), nullable=True),
    sa.Column('body_battery_drained', sa.Integer(), nullable=True),
    sa.Column('avg_waking_respiration', sa.Float(), nullable=True),
    sa.Column('lowest_respiration', sa.Float(), nullable=True),
    sa.Column('highest_respiration', sa.Float(), nullable=True),
    sa.Column('avg_sleep_respiration', sa.Float(), nullable=True),
    sa.Column('spo2_avg', sa.Float(), nullable=True),
    sa.Column('spo2_lowest', sa.Float(), nullable=True),
    sa.Column('sleeping_seconds', sa.Integer(), nullable=True),
    sa.Column('training_readiness', sa.Integer(), nullable=True),
    sa.Column('readiness_level', sa.String(length=48), nullable=True),
    sa.Column('readiness_factors', sa.JSON(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_daily_health')
    )
    with op.batch_alter_table('daily_health', schema=None) as batch_op:
        batch_op.create_index('ix_daily_health_day', ['day'], unique=False)

    op.create_table('derived_metrics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=32), nullable=False),
    sa.Column('scope_key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('units', sa.String(length=32), nullable=True),
    sa.Column('formula_version', sa.String(length=16), nullable=False),
    sa.Column('input_sources', sa.JSON(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('calculated_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('metric', 'scope', 'scope_key', name='uq_derived_metric')
    )
    with op.batch_alter_table('derived_metrics', schema=None) as batch_op:
        batch_op.create_index('ix_derived_metric_scope', ['metric', 'scope'], unique=False)

    op.create_table('devices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.Column('serial_number', sa.String(length=128), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'provider_id', name='uq_device_source')
    )
    op.create_table('gear',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('brand', sa.String(length=128), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('gear_type', sa.String(length=64), nullable=True),
    sa.Column('retired', sa.Boolean(), nullable=False),
    sa.Column('provider_distance_m', sa.Float(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'provider_id', name='uq_gear_source')
    )
    op.create_table('heart_rate_zones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('sport', sa.String(length=32), nullable=False),
    sa.Column('method', sa.String(length=48), nullable=True),
    sa.Column('resting_hr', sa.Integer(), nullable=True),
    sa.Column('max_hr', sa.Integer(), nullable=True),
    sa.Column('lactate_threshold_hr', sa.Integer(), nullable=True),
    sa.Column('zone_floors', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'sport', name='uq_hr_zone_sport')
    )
    op.create_table('hrv_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('last_night_avg_ms', sa.Float(), nullable=True),
    sa.Column('last_night_5min_high_ms', sa.Float(), nullable=True),
    sa.Column('weekly_avg_ms', sa.Float(), nullable=True),
    sa.Column('baseline_low_ms', sa.Float(), nullable=True),
    sa.Column('baseline_balanced_low_ms', sa.Float(), nullable=True),
    sa.Column('baseline_balanced_upper_ms', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=48), nullable=True),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_hrv_day')
    )
    op.create_table('performance_metrics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('metric', sa.String(length=64), nullable=False),
    sa.Column('sport', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('text_value', sa.String(length=255), nullable=True),
    sa.Column('units', sa.String(length=32), nullable=True),
    sa.Column('context', sa.JSON(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'metric', 'sport', 'day', name='uq_performance_metric')
    )
    with op.batch_alter_table('performance_metrics', schema=None) as batch_op:
        batch_op.create_index('ix_performance_metric', ['metric', 'day'], unique=False)

    op.create_table('provider_capabilities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=32), nullable=False),
    sa.Column('cadence', sa.String(length=32), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('handler', sa.String(length=64), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('expected_arguments', sa.JSON(), nullable=True),
    sa.Column('input_schema', sa.JSON(), nullable=True),
    sa.Column('last_called_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=32), nullable=True),
    sa.Column('last_note', sa.Text(), nullable=True),
    sa.Column('call_count', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'name', name='uq_capability_provider_name')
    )
    with op.batch_alter_table('provider_capabilities', schema=None) as batch_op:
        batch_op.create_index('ix_capability_status', ['provider', 'status'], unique=False)

    op.create_table('provider_connections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('external_id', sa.String(length=64), nullable=True),
    sa.Column('endpoint', sa.String(length=512), nullable=True),
    sa.Column('scopes', sa.String(length=512), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(), nullable=True),
    sa.Column('last_success_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider')
    )
    op.create_table('raw_payloads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('endpoint', sa.String(length=128), nullable=False),
    sa.Column('params', sa.JSON(), nullable=True),
    sa.Column('params_hash', sa.String(length=64), nullable=False),
    sa.Column('schema_version', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('content_type', sa.String(length=16), nullable=False),
    sa.Column('content_json', sa.JSON(), nullable=True),
    sa.Column('content_text', sa.Text(), nullable=True),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(), nullable=False),
    sa.Column('sync_run_id', sa.Integer(), nullable=True),
    sa.Column('reference_kind', sa.String(length=32), nullable=True),
    sa.Column('reference_id', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'endpoint', 'params_hash', name='uq_raw_payload')
    )
    with op.batch_alter_table('raw_payloads', schema=None) as batch_op:
        batch_op.create_index('ix_raw_payload_ref', ['reference_kind', 'reference_id'], unique=False)
        batch_op.create_index('ix_raw_payload_retrieved', ['provider', 'retrieved_at'], unique=False)

    op.create_table('sleep_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('sleep_start_utc', sa.DateTime(), nullable=True),
    sa.Column('sleep_end_utc', sa.DateTime(), nullable=True),
    sa.Column('total_sleep_s', sa.Integer(), nullable=True),
    sa.Column('nap_s', sa.Integer(), nullable=True),
    sa.Column('deep_s', sa.Integer(), nullable=True),
    sa.Column('light_s', sa.Integer(), nullable=True),
    sa.Column('rem_s', sa.Integer(), nullable=True),
    sa.Column('awake_s', sa.Integer(), nullable=True),
    sa.Column('awake_count', sa.Integer(), nullable=True),
    sa.Column('sleep_score', sa.Integer(), nullable=True),
    sa.Column('score_qualifier', sa.String(length=48), nullable=True),
    sa.Column('avg_sleep_stress', sa.Float(), nullable=True),
    sa.Column('avg_overnight_hrv', sa.Float(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_sleep_day')
    )
    with op.batch_alter_table('sleep_records', schema=None) as batch_op:
        batch_op.create_index('ix_sleep_day', ['day'], unique=False)

    op.create_table('stress_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('avg_stress', sa.Integer(), nullable=True),
    sa.Column('max_stress', sa.Integer(), nullable=True),
    sa.Column('rest_pct', sa.Float(), nullable=True),
    sa.Column('low_pct', sa.Float(), nullable=True),
    sa.Column('medium_pct', sa.Float(), nullable=True),
    sa.Column('high_pct', sa.Float(), nullable=True),
    sa.Column('data_points', sa.Integer(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_stress_day')
    )
    op.create_table('sync_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('providers', sa.String(length=128), nullable=False),
    sa.Column('mode', sa.String(length=32), nullable=False),
    sa.Column('categories', sa.String(length=512), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('trigger', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('range_start', sa.Date(), nullable=True),
    sa.Column('range_end', sa.Date(), nullable=True),
    sa.Column('tasks_total', sa.Integer(), nullable=False),
    sa.Column('tasks_done', sa.Integer(), nullable=False),
    sa.Column('records_written', sa.Integer(), nullable=False),
    sa.Column('errors_count', sa.Integer(), nullable=False),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('current_step', sa.String(length=255), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sync_runs', schema=None) as batch_op:
        batch_op.create_index('ix_sync_runs_started', ['started_at'], unique=False)

    op.create_table('sync_watermarks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('cursor_date', sa.Date(), nullable=True),
    sa.Column('cursor_time', sa.DateTime(), nullable=True),
    sa.Column('cursor_value', sa.String(length=255), nullable=True),
    sa.Column('last_success_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'category', 'key', name='uq_watermark')
    )
    op.create_table('training_load',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('acute_load', sa.Float(), nullable=True),
    sa.Column('chronic_load', sa.Float(), nullable=True),
    sa.Column('balance', sa.Float(), nullable=True),
    sa.Column('acwr', sa.Float(), nullable=True),
    sa.Column('acwr_status', sa.String(length=48), nullable=True),
    sa.Column('optimal_min', sa.Float(), nullable=True),
    sa.Column('optimal_max', sa.Float(), nullable=True),
    sa.Column('training_status', sa.String(length=64), nullable=True),
    sa.Column('vo2max', sa.Float(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_training_load_day')
    )
    with op.batch_alter_table('training_load', schema=None) as batch_op:
        batch_op.create_index('ix_training_load_day', ['day'], unique=False)

    op.create_table('training_status',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('status_label', sa.String(length=64), nullable=True),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('fitness_trend', sa.Integer(), nullable=True),
    sa.Column('acwr', sa.Float(), nullable=True),
    sa.Column('acwr_status', sa.String(length=48), nullable=True),
    sa.Column('load_aerobic_low', sa.Float(), nullable=True),
    sa.Column('load_aerobic_high', sa.Float(), nullable=True),
    sa.Column('load_anaerobic', sa.Float(), nullable=True),
    sa.Column('balance_feedback', sa.Text(), nullable=True),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'day', name='uq_training_status_day')
    )
    op.create_table('activities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('canonical_key', sa.String(length=80), nullable=False),
    sa.Column('primary_source', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=512), nullable=True),
    sa.Column('sport', sa.String(length=48), nullable=False),
    sa.Column('sub_sport', sa.String(length=48), nullable=True),
    sa.Column('provider_type', sa.String(length=64), nullable=True),
    sa.Column('start_time_utc', sa.DateTime(), nullable=False),
    sa.Column('start_time_local', sa.String(length=32), nullable=True),
    sa.Column('utc_offset_seconds', sa.Integer(), nullable=True),
    sa.Column('local_date', sa.Date(), nullable=True),
    sa.Column('duration_s', sa.Float(), nullable=True),
    sa.Column('moving_duration_s', sa.Float(), nullable=True),
    sa.Column('elapsed_duration_s', sa.Float(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('elevation_gain_m', sa.Float(), nullable=True),
    sa.Column('elevation_loss_m', sa.Float(), nullable=True),
    sa.Column('avg_speed_mps', sa.Float(), nullable=True),
    sa.Column('max_speed_mps', sa.Float(), nullable=True),
    sa.Column('avg_hr', sa.Float(), nullable=True),
    sa.Column('max_hr', sa.Float(), nullable=True),
    sa.Column('avg_cadence', sa.Float(), nullable=True),
    sa.Column('avg_power_w', sa.Float(), nullable=True),
    sa.Column('max_power_w', sa.Float(), nullable=True),
    sa.Column('normalized_power_w', sa.Float(), nullable=True),
    sa.Column('calories', sa.Float(), nullable=True),
    sa.Column('training_load', sa.Float(), nullable=True),
    sa.Column('aerobic_training_effect', sa.Float(), nullable=True),
    sa.Column('anaerobic_training_effect', sa.Float(), nullable=True),
    sa.Column('training_effect_label', sa.String(length=64), nullable=True),
    sa.Column('perceived_effort', sa.Float(), nullable=True),
    sa.Column('avg_temperature_c', sa.Float(), nullable=True),
    sa.Column('device_name', sa.String(length=255), nullable=True),
    sa.Column('gear_id', sa.Integer(), nullable=True),
    sa.Column('start_lat', sa.Float(), nullable=True),
    sa.Column('start_lng', sa.Float(), nullable=True),
    sa.Column('has_gps', sa.Boolean(), nullable=False),
    sa.Column('has_streams', sa.Boolean(), nullable=False),
    sa.Column('detail_status', sa.String(length=24), nullable=False),
    sa.Column('stream_status', sa.String(length=24), nullable=False),
    sa.Column('field_provenance', sa.JSON(), nullable=True),
    sa.Column('duplicate_state', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['gear_id'], ['gear.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('canonical_key')
    )
    with op.batch_alter_table('activities', schema=None) as batch_op:
        batch_op.create_index('ix_activities_sport', ['sport', 'start_time_utc'], unique=False)
        batch_op.create_index('ix_activities_start', ['start_time_utc'], unique=False)

    op.create_table('sync_errors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sync_run_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('capability', sa.String(length=128), nullable=True),
    sa.Column('kind', sa.String(length=48), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('context', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['sync_run_id'], ['sync_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sync_errors', schema=None) as batch_op:
        batch_op.create_index('ix_sync_errors_run', ['sync_run_id'], unique=False)

    op.create_table('activity_source_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('external_id', sa.String(length=128), nullable=True),
    sa.Column('upload_id', sa.String(length=128), nullable=True),
    sa.Column('name', sa.String(length=512), nullable=True),
    sa.Column('sport', sa.String(length=48), nullable=False),
    sa.Column('provider_type', sa.String(length=64), nullable=True),
    sa.Column('start_time_utc', sa.DateTime(), nullable=False),
    sa.Column('start_time_local', sa.String(length=32), nullable=True),
    sa.Column('utc_offset_seconds', sa.Integer(), nullable=True),
    sa.Column('duration_s', sa.Float(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=True),
    sa.Column('detail_status', sa.String(length=24), nullable=False),
    sa.Column('raw_payload_id', sa.Integer(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'provider_id', name='uq_source_record')
    )
    with op.batch_alter_table('activity_source_records', schema=None) as batch_op:
        batch_op.create_index('ix_source_record_activity', ['activity_id'], unique=False)
        batch_op.create_index('ix_source_record_start', ['source', 'start_time_utc'], unique=False)

    op.create_table('activity_laps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=True),
    sa.Column('source_record_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('lap_index', sa.Integer(), nullable=False),
    sa.Column('start_time_utc', sa.DateTime(), nullable=True),
    sa.Column('duration_s', sa.Float(), nullable=True),
    sa.Column('moving_duration_s', sa.Float(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('avg_speed_mps', sa.Float(), nullable=True),
    sa.Column('max_speed_mps', sa.Float(), nullable=True),
    sa.Column('avg_hr', sa.Float(), nullable=True),
    sa.Column('max_hr', sa.Float(), nullable=True),
    sa.Column('avg_power_w', sa.Float(), nullable=True),
    sa.Column('avg_cadence', sa.Float(), nullable=True),
    sa.Column('elevation_gain_m', sa.Float(), nullable=True),
    sa.Column('elevation_loss_m', sa.Float(), nullable=True),
    sa.Column('calories', sa.Float(), nullable=True),
    sa.Column('intensity_type', sa.String(length=32), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_record_id'], ['activity_source_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_record_id', 'lap_index', name='uq_lap')
    )
    with op.batch_alter_table('activity_laps', schema=None) as batch_op:
        batch_op.create_index('ix_lap_activity', ['activity_id'], unique=False)

    op.create_table('activity_splits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=True),
    sa.Column('source_record_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('split_type', sa.String(length=48), nullable=False),
    sa.Column('split_index', sa.Integer(), nullable=False),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('duration_s', sa.Float(), nullable=True),
    sa.Column('elevation_gain_m', sa.Float(), nullable=True),
    sa.Column('avg_speed_mps', sa.Float(), nullable=True),
    sa.Column('avg_hr', sa.Float(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_record_id'], ['activity_source_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_record_id', 'split_type', 'split_index', name='uq_split')
    )
    with op.batch_alter_table('activity_splits', schema=None) as batch_op:
        batch_op.create_index('ix_split_activity', ['activity_id'], unique=False)

    op.create_table('activity_streams',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=True),
    sa.Column('source_record_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('units', sa.String(length=24), nullable=True),
    sa.Column('point_count', sa.Integer(), nullable=False),
    sa.Column('encoding', sa.String(length=24), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_record_id'], ['activity_source_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_record_id', 'channel', name='uq_stream_channel')
    )
    with op.batch_alter_table('activity_streams', schema=None) as batch_op:
        batch_op.create_index('ix_stream_activity', ['activity_id'], unique=False)

    op.create_table('activity_zones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=True),
    sa.Column('source_record_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('zone_kind', sa.String(length=16), nullable=False),
    sa.Column('zone_number', sa.Integer(), nullable=False),
    sa.Column('seconds_in_zone', sa.Float(), nullable=True),
    sa.Column('low_boundary', sa.Float(), nullable=True),
    sa.Column('high_boundary', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_record_id'], ['activity_source_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_record_id', 'zone_kind', 'zone_number', name='uq_zone')
    )
    with op.batch_alter_table('activity_zones', schema=None) as batch_op:
        batch_op.create_index('ix_zone_activity', ['activity_id'], unique=False)

    op.create_table('duplicate_candidates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('left_source_record_id', sa.Integer(), nullable=False),
    sa.Column('right_source_record_id', sa.Integer(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('reasons', sa.JSON(), nullable=True),
    sa.Column('state', sa.String(length=24), nullable=False),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['left_source_record_id'], ['activity_source_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['right_source_record_id'], ['activity_source_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('left_source_record_id', 'right_source_record_id', name='uq_dupe_pair')
    )


def downgrade() -> None:
    op.drop_table('duplicate_candidates')
    with op.batch_alter_table('activity_zones', schema=None) as batch_op:
        batch_op.drop_index('ix_zone_activity')

    op.drop_table('activity_zones')
    with op.batch_alter_table('activity_streams', schema=None) as batch_op:
        batch_op.drop_index('ix_stream_activity')

    op.drop_table('activity_streams')
    with op.batch_alter_table('activity_splits', schema=None) as batch_op:
        batch_op.drop_index('ix_split_activity')

    op.drop_table('activity_splits')
    with op.batch_alter_table('activity_laps', schema=None) as batch_op:
        batch_op.drop_index('ix_lap_activity')

    op.drop_table('activity_laps')
    with op.batch_alter_table('activity_source_records', schema=None) as batch_op:
        batch_op.drop_index('ix_source_record_start')
        batch_op.drop_index('ix_source_record_activity')

    op.drop_table('activity_source_records')
    with op.batch_alter_table('sync_errors', schema=None) as batch_op:
        batch_op.drop_index('ix_sync_errors_run')

    op.drop_table('sync_errors')
    with op.batch_alter_table('activities', schema=None) as batch_op:
        batch_op.drop_index('ix_activities_start')
        batch_op.drop_index('ix_activities_sport')

    op.drop_table('activities')
    op.drop_table('training_status')
    with op.batch_alter_table('training_load', schema=None) as batch_op:
        batch_op.drop_index('ix_training_load_day')

    op.drop_table('training_load')
    op.drop_table('sync_watermarks')
    with op.batch_alter_table('sync_runs', schema=None) as batch_op:
        batch_op.drop_index('ix_sync_runs_started')

    op.drop_table('sync_runs')
    op.drop_table('stress_records')
    with op.batch_alter_table('sleep_records', schema=None) as batch_op:
        batch_op.drop_index('ix_sleep_day')

    op.drop_table('sleep_records')
    with op.batch_alter_table('raw_payloads', schema=None) as batch_op:
        batch_op.drop_index('ix_raw_payload_retrieved')
        batch_op.drop_index('ix_raw_payload_ref')

    op.drop_table('raw_payloads')
    op.drop_table('provider_connections')
    with op.batch_alter_table('provider_capabilities', schema=None) as batch_op:
        batch_op.drop_index('ix_capability_status')

    op.drop_table('provider_capabilities')
    with op.batch_alter_table('performance_metrics', schema=None) as batch_op:
        batch_op.drop_index('ix_performance_metric')

    op.drop_table('performance_metrics')
    op.drop_table('hrv_records')
    op.drop_table('heart_rate_zones')
    op.drop_table('gear')
    op.drop_table('devices')
    with op.batch_alter_table('derived_metrics', schema=None) as batch_op:
        batch_op.drop_index('ix_derived_metric_scope')

    op.drop_table('derived_metrics')
    with op.batch_alter_table('daily_health', schema=None) as batch_op:
        batch_op.drop_index('ix_daily_health_day')

    op.drop_table('daily_health')
    op.drop_table('body_composition')
    op.drop_table('body_battery_records')
    op.drop_table('athletes')
    op.drop_table('app_settings')
