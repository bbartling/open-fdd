import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../lib/api";

type CatalogCode = {
  code: string;
  category: string;
  title: string;
  severity: string;
  cookbook_patterns?: string[];
};

type CatalogFamily = {
  family: string;
  label: string;
  categories: { category: string; label: string; codes: CatalogCode[] }[];
};

type ApplicableResponse = {
  families: CatalogFamily[];
  applicable_families?: string[];
};

type Props = {
  values: string[];
  siteId?: string;
  onChange: (codes: string[]) => void;
  disabled?: boolean;
};

export default function FaultCodeMultiSelect({ values, siteId, onChange, disabled }: Props) {
  const [families, setFamilies] = useState<CatalogFamily[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
    apiFetch<ApplicableResponse>(`/api/faults/applicable${q}`)
      .then((res) => {
        const scoped = res.families ?? [];
        if (scoped.length) {
          setFamilies(scoped);
          return;
        }
        return apiFetch<ApplicableResponse>("/api/faults/tree").then((full) => {
          setFamilies(full.families || []);
        });
      })
      .catch((e) => setError(String(e)));
  }, [siteId]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!open || !rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const codeIndex = useMemo(() => {
    const map = new Map<string, CatalogCode>();
    for (const fam of families) {
      for (const cat of fam.categories) {
        for (const c of cat.codes) map.set(c.code, c);
      }
    }
    return map;
  }, [families]);

  const selected = values.filter((c) => codeIndex.has(c) || c);

  function toggle(code: string) {
    const up = code.toUpperCase();
    if (values.map((v) => v.toUpperCase()).includes(up)) {
      onChange(values.filter((v) => v.toUpperCase() !== up));
    } else {
      onChange([...values, up]);
    }
  }

  return (
    <div className="fault-code-multi" ref={rootRef}>
      <span className="label-text">Check-engine fault codes</span>
      <button
        type="button"
        className="fault-code-multi-trigger"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {selected.length ? (
          <span className="fault-code-multi-badges">
            {selected.map((c) => (
              <span key={c} className="badge code-badge">
                {c}
              </span>
            ))}
          </span>
        ) : (
          <span className="muted">Select catalog codes…</span>
        )}
        <span className="fault-code-multi-chevron" aria-hidden>
          {open ? "▴" : "▾"}
        </span>
      </button>
      {open ? (
        <div className="fault-code-multi-panel" role="listbox" aria-multiselectable>
          {families.map((fam) => (
            <div key={fam.family} className="fault-code-multi-family">
              <div className="fault-code-multi-family-head">
                {fam.label} <span className="muted">({fam.family})</span>
              </div>
              {fam.categories.map((cat) =>
                cat.codes.map((c) => {
                  const checked = values.map((v) => v.toUpperCase()).includes(c.code.toUpperCase());
                  return (
                    <label key={c.code} className="fault-code-multi-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggle(c.code)}
                      />
                      <span>
                        <strong>{c.code}</strong> — {c.title}
                      </span>
                    </label>
                  );
                }),
              )}
            </div>
          ))}
        </div>
      ) : null}
      {error ? <span className="muted">{error}</span> : null}
      <span className="muted fault-code-hint">
        Multi-select letter-suffix codes (e.g. VAV-C, AHU-B). Scoped to your data model when available.
      </span>
    </div>
  );
}
