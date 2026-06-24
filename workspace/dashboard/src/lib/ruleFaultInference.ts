export type FaultInferenceSimilar = {
  code: string;
  title?: string;
  relation?: string;
};

export type FaultInference = {
  ok?: boolean;
  fault_codes?: string[];
  fault_code?: string;
  narrative?: string;
  similar?: FaultInferenceSimilar[];
  related_assigned_rules?: { rule_name?: string; fault_code?: string }[];
  source?: string;
  ollama_ok?: boolean;
  ollama_error?: string;
};

export function formatFaultInferenceBlock(inf: FaultInference | null | undefined): string {
  if (!inf) return "";
  const lines: string[] = [">>> Fault catalog mapping (local Ollama + Haystack scope)"];
  if (inf.narrative) lines.push(inf.narrative);
  const codes = inf.fault_codes ?? (inf.fault_code ? [inf.fault_code] : []);
  if (codes.length) {
    lines.push(`Suggested codes: ${codes.join(", ")} (${inf.source ?? "inference"})`);
  }
  for (const s of inf.similar ?? []) {
    if (!s.code) continue;
    const bit = [s.code, s.title, s.relation].filter(Boolean).join(" — ");
    lines.push(`  · ${bit}`);
  }
  const related = inf.related_assigned_rules ?? [];
  if (related.length) {
    lines.push("Related rules already on site:");
    for (const r of related) {
      lines.push(`  · ${r.rule_name ?? "?"} → ${r.fault_code ?? "?"}`);
    }
  }
  if (!inf.ollama_ok && inf.ollama_error) {
    lines.push(`(Ollama note: ${inf.ollama_error})`);
  }
  return lines.join("\n");
}
