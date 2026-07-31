import { AppShell } from "../components/AppShell";
import { useSessionQuery, useFormDraft, useDirtyFormWarning } from "../session";
import { Select, Button } from "../components/widgets";

export function MappingPage() {
  const { query, setQuery } = useSessionQuery();
  const [draft, setDraft, clearDraft, dirty] = useFormDraft("mapping-demo", {
    note: "",
  });
  const { confirmLeave } = useDirtyFormWarning(dirty);

  return (
    <AppShell
      title="Mapping"
      caption="Equipment selection in URL (?eq=); form note is sessionStorage draft only."
      activeSectionId="data-model"
    >
      <div className="page-placeholder">
        <h2>Mapping</h2>
        <p>Equipment role mapping — placeholder for P1-M4 slice.</p>
        <Select
          id="map-equipment"
          label="Selected equipment"
          description="Maps Streamlit selected_equipment → URL ?eq="
          value={query.equipment ?? ""}
          options={[
            { value: "", label: "— none —" },
            { value: "AHU-1", label: "AHU-1" },
            { value: "VAV-2", label: "VAV-2" },
          ]}
          onChange={(value) => setQuery({ equipment: value }, true)}
          testId="map-equipment-select"
        />
        <label htmlFor="map-note">
          Draft note (sessionStorage; not durable domain state)
          <input
            id="map-note"
            data-testid="map-draft-note"
            value={String(draft.note ?? "")}
            onChange={(e) => setDraft({ ...draft, note: e.target.value })}
          />
        </label>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
          <Button
            id="map-clear-draft"
            label="Clear draft"
            onClick={() => {
              if (confirmLeave()) clearDraft();
            }}
            testId="map-clear-draft"
          />
        </div>
        {dirty ? (
          <p className="alert alert--warning" data-testid="map-dirty-banner">
            Unsaved draft — browser unload will warn.
          </p>
        ) : null}
      </div>
    </AppShell>
  );
}
