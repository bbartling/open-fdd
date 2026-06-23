export type InsightResponse = {
  ok: boolean;
  sentence: string;
  zone_sentence?: string;
  device_sentence?: string;
  lookback_days?: number;
  methodology?: {
    lookback_days?: number;
    zone_temperatures?: string;
    recovery_rates?: string;
    device_poll_health?: string;
  };
  fault_sentences?: string[];
  fault_catalog?: {
    code?: string;
    title?: string;
    description?: string;
    suggested_checks?: string[];
  }[];
  faults_linked?: { code?: string; title?: string; equipment_name?: string }[];
  brick_model?: { feeds_chains?: string[]; equipment_count?: number };
  worst_zones?: {
    label?: string;
    equipment_name?: string;
    day_avg_f?: number;
    night_avg_f?: number;
    recovery_f_per_min?: number;
    worst_reason?: string;
  }[];
  zone_temps?: {
    topology_mode?: string;
    zone_sensor_count?: number;
    struggling_zones?: { label?: string; ahu_name?: string; reason?: string }[];
    research?: {
      site_flags?: string[];
      opportunities?: { topic?: string; suggestion?: string; signal?: string }[];
      suspicious_sensors?: string[];
    };
    refresh_interval_s?: number;
  };
  device_poll_health?: {
    healthy_count?: number;
    offline_equipment?: {
      equipment_name?: string;
      points_stale?: number;
      points_polled?: number;
    }[];
    flaky_equipment?: { equipment_name?: string; max_flips_per_day?: number }[];
  };
  source?: string;
  generated_at?: number;
  next_refresh_at?: number;
  refresh_interval_s?: number;
  cached?: boolean;
  error?: string;
  ollama_ok?: boolean;
};
