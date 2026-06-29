import { useMemo, useState } from "react";
import type { FddInput, SchemaColumn, SchemaTable } from "./types";

type Props = {
  tables: SchemaTable[];
  fddInputs: FddInput[];
  onInsert: (snippet: string) => void;
  selectedTable?: string;
  onSelectTable?: (name: string) => void;
};

function normalizeColumns(table: SchemaTable): SchemaColumn[] {
  if (!table.columns?.length) return [];
  if (typeof table.columns[0] === "string") {
    return (table.columns as string[]).map((name) => ({ name, type: "DOUBLE" }));
  }
  return table.columns as SchemaColumn[];
}

export default function SqlFddSchemaExplorer({
  tables,
  fddInputs,
  onInsert,
  selectedTable,
  onSelectTable,
}: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ telemetry_pivot: true });
  const inputById = useMemo(() => new Map(fddInputs.map((i) => [i.id, i])), [fddInputs]);

  return (
    <aside className="gf-schema" aria-label="DataFusion schema">
      <div className="gf-schema__head">
        <span className="gf-schema__title">Schema</span>
        <span className="gf-pill gf-pill--dialect">DataFusion</span>
      </div>
      <p className="gf-schema__hint muted">
        Historian tables registered for FDD SQL. Click a column to insert into the editor.
      </p>
      <ul className="gf-schema__tree">
        {tables.map((table) => {
          const open = expanded[table.name] ?? false;
          const cols = normalizeColumns(table);
          const active = selectedTable === table.name;
          return (
            <li key={table.name} className="gf-schema__table">
              <button
                type="button"
                className={`gf-schema__table-btn${active ? " is-active" : ""}`}
                onClick={() => {
                  setExpanded((e) => ({ ...e, [table.name]: !open }));
                  onSelectTable?.(table.name);
                }}
              >
                <span className="gf-schema__chev">{open ? "▾" : "▸"}</span>
                <span className="gf-schema__table-name">{table.name}</span>
                <span className="gf-schema__count">{cols.length}</span>
              </button>
              {table.description && open ? (
                <p className="gf-schema__desc muted">{table.description}</p>
              ) : null}
              {open ? (
                <ul className="gf-schema__cols">
                  {cols.map((col) => {
                    const meta = inputById.get(col.name);
                    return (
                      <li key={col.name}>
                        <button
                          type="button"
                          className="gf-schema__col-btn"
                          title={meta ? `${meta.label}${meta.unit ? ` (${meta.unit})` : ""}` : col.type}
                          onClick={() => onInsert(col.name)}
                        >
                          <span className="gf-schema__col-name">{col.name}</span>
                          <span className="gf-schema__col-type">{col.type}</span>
                          {col.is_primary ? <span className="gf-pill gf-pill--pk">PK</span> : null}
                          {meta ? <span className="gf-pill gf-pill--fdd">FDD</span> : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
