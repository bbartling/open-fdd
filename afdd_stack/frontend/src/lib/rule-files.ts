/**
 * True for filenames created by openclaw/bench/e2e/4_hot_reload_test.py:
 * `test_{original_rule_stem}_{unix_timestamp}.yaml` (numeric suffix, typically ≥9 digits).
 */
export function isHotReloadBenchArtifact(filename: string): boolean {
  return /^test_[a-z0-9_]+_\d{9,}\.yaml$/i.test(filename);
}
