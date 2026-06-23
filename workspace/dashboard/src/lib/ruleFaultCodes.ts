/** Parse fault_code / fault_codes from a saved rule record. */
export function faultCodesFromRule(rule: {
  fault_code?: string;
  fault_codes?: string[];
}): string[] {
  const list = rule.fault_codes;
  if (Array.isArray(list) && list.length) {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const raw of list) {
      const c = String(raw || "").trim().toUpperCase();
      if (c && !seen.has(c)) {
        seen.add(c);
        out.push(c);
      }
    }
    if (out.length) return out;
  }
  const single = String(rule.fault_code || "").trim().toUpperCase();
  return single ? [single] : [];
}

export function primaryFaultCode(codes: string[]): string {
  return codes[0] ?? "";
}
