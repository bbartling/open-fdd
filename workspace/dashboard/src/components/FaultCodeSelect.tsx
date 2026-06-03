import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type CatalogCode = {
  code: string;
  category: string;
  title: string;
  severity: string;
  cookbook_patterns?: string[];
  suffix?: string;
};

type CatalogFamily = {
  family: string;
  label: string;
  codes: CatalogCode[];
};

type CatalogResponse = {
  version: number;
  code_format?: string;
  families: CatalogFamily[];
};

type Props = {
  value: string;
  onChange: (code: string) => void;
  disabled?: boolean;
};

export default function FaultCodeSelect({ value, onChange, disabled }: Props) {
  const [families, setFamilies] = useState<CatalogFamily[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<CatalogResponse>("/api/faults/catalog")
      .then((c) => setFamilies(c.families || []))
      .catch((e) => setError(String(e)));
  }, []);

  const selected = families.flatMap((f) => f.codes).find((c) => c.code === value);

  return (
    <label className="fault-code-select">
      <span className="label-text">Check-engine fault code</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Fault code from catalog"
      >
        <option value="">— none —</option>
        {families.map((fam) => (
          <optgroup key={fam.family} label={`${fam.label} (${fam.family})`}>
            {fam.codes.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} — {c.title}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {error ? <span className="muted">{error}</span> : null}
      {selected ? (
        <span className="muted fault-code-hint">
          {selected.category.replace(/_/g, " ")}
          {selected.cookbook_patterns?.length
            ? ` · cookbook: ${selected.cookbook_patterns.join(", ")}`
            : ""}
        </span>
      ) : (
        <span className="muted fault-code-hint">
          Letter suffix only (e.g. VAV-C) — not equipment names like VAV-03.
        </span>
      )}
    </label>
  );
}
