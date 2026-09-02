/**
 * The only network surface the dashboard has.
 *
 * Every call goes to Paceboard's own REST API on the same origin (Vite proxies
 * /api to the backend in dev). The browser never talks to Garmin, Strava or an
 * MCP server, and no provider credential is ever present in this bundle.
 */

export interface ApiErrorBody {
  error: { code: string; message: string; detail?: Record<string, unknown> | null };
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly detail?: Record<string, unknown> | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/api/v1";

export type Query = Record<string, string | number | boolean | undefined | null>;

function qs(params?: Query): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request<T>(path: string, init?: RequestInit, params?: Query): Promise<T> {
  const response = await fetch(`${BASE}${path}${qs(params)}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(
      body?.error?.code ?? "http_error",
      body?.error?.message ?? `Request failed with HTTP ${response.status}`,
      response.status,
      body?.error?.detail,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T,>(path: string, params?: Query) => request<T>(path, undefined, params),
  post: <T,>(path: string, body?: unknown, params?: Query) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }, params),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T,>(path: string, params?: Query) => request<T>(path, { method: "DELETE" }, params),
  exportUrl: (format: "csv" | "json", params: Query) => `${BASE}/export.${format}${qs(params)}`,
};

/* ---------------- shared types ---------------- */

export interface Metric {
  value: number | null;
  units: string | null;
  available: boolean;
  unavailable_reason: string | null;
  inputs: string[];
  formula_version: string;
  detail?: Record<string, any> | null;
}

export interface Status {
  version: string;
  timezone: string;
  unit_system: string;
  fixture_mode: boolean;
  database_path: string;
  database_bytes: number;
  bound_host: string;
  api_port: number;
  counts: Record<string, number>;
  last_sync: SyncBrief | null;
  freshness: Freshness[];
}

export interface SyncBrief {
  id: number;
  status: string;
  mode: string;
  started_at: string;
  finished_at: string | null;
  records_written: number;
  errors_count: number;
  current_step: string | null;
}

export interface Freshness {
  provider: string;
  category: string;
  cursor_date: string | null;
  last_success_at: string | null;
  age_seconds: number | null;
  status: string | null;
}

export interface Connection {
  provider: string;
  status: string;
  display_name: string | null;
  endpoint: string | null;
  configured: boolean;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  details: Record<string, any> | null;
}

export interface Capability {
  provider: string;
  name: string;
  category: string;
  scope: string;
  cadence: string;
  enabled: boolean;
  status: string;
  handler: string | null;
  description: string | null;
  expected_arguments: Record<string, any> | null;
  last_called_at: string | null;
  last_status: string | null;
  last_note: string | null;
  call_count: number;
  error_count: number;
}

export interface SyncRun extends SyncBrief {
  providers: string;
  categories: string | null;
  trigger: string;
  range_start: string | null;
  range_end: string | null;
  cancel_requested: boolean;
  summary: { tasks: SyncTask[] } | null;
  errors: SyncErrorRow[];
}

export interface SyncTask {
  name: string;
  provider: string;
  status: string;
  records: number;
  calls: number;
  notes: string[];
}

export interface SyncErrorRow {
  provider: string;
  capability: string | null;
  kind: string;
  message: string;
  occurred_at: string;
}

export interface ActivitySource {
  source: string;
  provider_id: string;
  name: string | null;
  sport: string;
  provider_type: string | null;
  start_time_utc: string;
  duration_s: number | null;
  distance_m: number | null;
  detail_status: string;
}

export interface Activity {
  id: number;
  canonical_key: string;
  primary_source: string;
  name: string | null;
  sport: string;
  provider_type: string | null;
  start_time_utc: string;
  start_time_local: string | null;
  local_date: string | null;
  duration_s: number | null;
  moving_duration_s: number | null;
  distance_m: number | null;
  elevation_gain_m: number | null;
  elevation_loss_m: number | null;
  avg_speed_mps: number | null;
  max_speed_mps: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_cadence: number | null;
  avg_power_w: number | null;
  normalized_power_w: number | null;
  calories: number | null;
  training_load: number | null;
  aerobic_training_effect: number | null;
  anaerobic_training_effect: number | null;
  training_effect_label: string | null;
  avg_temperature_c: number | null;
  device_name: string | null;
  has_gps: boolean;
  has_streams: boolean;
  detail_status: string;
  stream_status: string;
  duplicate_state: string;
  field_provenance: Record<string, string> | null;
  sources: ActivitySource[];
}

export interface Paged<T> {
  items: T[];
  page: { total: number; limit: number; offset: number; has_more: boolean };
}

export interface StreamSet {
  activity_id: number;
  available: boolean;
  unavailable_reason: string | null;
  point_count: number;
  original_point_count?: number;
  channels: Record<string, { source: string; units: string | null; data: (number | null)[] }>;
}

export interface Overview {
  generated_at: string;
  timezone: string;
  unit_system: string;
  today: Record<string, any>;
  last_night: Record<string, any>;
  baselines: Record<string, number | null>;
  form: {
    days: string[];
    ctl: number[];
    atl: number[];
    tsb: number[];
    daily_load: number[];
    latest_ctl: number | null;
    latest_atl: number | null;
    latest_tsb: number | null;
  };
  weekly_volume: VolumeBucket[];
  rolling: RollingTotal[];
  consistency: {
    window_days: number;
    active_days: number;
    active_ratio: number;
    current_streak: number;
    longest_streak: number;
  };
  recent_activities: Activity[];
  recovery: Record<string, Metric & Record<string, any>>;
  sync: SyncBrief & { id: number | null };
}

export interface VolumeBucket {
  week_start: string;
  sport: string;
  distance_m: number;
  duration_s: number;
  elevation_m: number;
  count: number;
}

export interface RollingTotal {
  days: number;
  count: number;
  distance_m: number;
  duration_s: number;
  elevation_m: number;
}

export interface LoadSeries {
  days: string[];
  daily_load: number[];
  ctl: number[];
  atl: number[];
  tsb: number[];
  garmin_acute: (number | null)[];
  garmin_chronic: (number | null)[];
  garmin_acwr: (number | null)[];
  formula: Record<string, string>;
  provider_note: string;
}

export interface RecoverySeries {
  days: string[];
  sleep_seconds: (number | null)[];
  sleep_score: (number | null)[];
  sleep_stages: ({ deep: number | null; light: number | null; rem: number | null; awake: number | null } | null)[];
  hrv_ms: (number | null)[];
  hrv_baseline: (number | null)[];
  resting_hr: (number | null)[];
  resting_hr_baseline: (number | null)[];
  avg_stress: (number | null)[];
  stress_distribution: ({ rest: number | null; low: number | null; medium: number | null; high: number | null } | null)[];
  body_battery_high: (number | null)[];
  body_battery_low: (number | null)[];
  body_battery_charged: (number | null)[];
  body_battery_drained: (number | null)[];
  respiration: (number | null)[];
  spo2: (number | null)[];
  training_readiness: (number | null)[];
}

export interface ZoneTotals {
  available: boolean;
  unavailable_reason: string | null;
  zones: Record<string, number>;
  percent?: Record<string, number>;
  distribution?: { easy: number; moderate: number; hard: number } | null;
}

export interface RawPayloadRow {
  id: number;
  provider: string;
  endpoint: string;
  params: Record<string, any> | null;
  schema_version: string;
  status: string;
  content_type: string;
  byte_size: number;
  duration_ms: number | null;
  retrieved_at: string;
  reference_kind: string | null;
  reference_id: string | null;
}

export interface ToolSpec {
  name: string;
  category: string;
  scope: string;
  cadence: string;
  arguments: string[];
  defaults: Record<string, any>;
  max_range_days: number | null;
  scheduled: boolean;
  notes: string;
}

export interface AppSettings {
  unit_system: string;
  timezone: string;
  backfill_days: number;
  fast_interval_minutes: number;
  show_maps: boolean;
  map_tiles_enabled: boolean;
  scheduler_enabled: boolean;
  reconcile_days: number;
  fixture_mode: boolean;
  storage: {
    database_path: string;
    database_bytes: number;
    database_mb: number;
    rows: Record<string, number>;
    total_rows: number;
  };
  notes: Record<string, any>;
}

export interface StravaStatus {
  configured: boolean;
  connected: boolean;
  scopes_requested: string;
  athlete: Record<string, any> | null;
  tokens_encrypted: boolean;
  rate_limit: Record<string, any>;
  message: string;
}
