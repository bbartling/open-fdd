import { AppShell } from "../components/AppShell";
import { useSessionQuery } from "../session";
import { RadioGroup } from "../components/widgets";

const WATTLab_PAGES = [
  { value: "Uploads", label: "Uploads" },
  { value: "Fuel dashboard", label: "Fuel dashboard" },
  { value: "Twin / calibrate", label: "Twin / calibrate" },
  { value: "ECMs", label: "ECMs" },
] as const;

export function WattLabPage() {
  const { query, setQuery } = useSessionQuery();
  const page = query.wattlabPage ?? "Uploads";

  return (
    <AppShell
      title="WattLab"
      caption="Sub-page mirrors Streamlit wattlab_studio_page via ?wl="
      activeSectionId="wattlab"
    >
      <div className="page-placeholder">
        <h2>WattLab</h2>
        <RadioGroup
          id="wattlab-page"
          label="WattLab workflow"
          description="Maps st.session_state wattlab_studio_page → URL"
          value={page}
          options={[...WATTLab_PAGES]}
          onChange={(value) => setQuery({ wattlabPage: value }, true)}
          testId="wattlab-page-radio"
        />
        <p data-testid="wattlab-active-page">
          Active: <strong>{page}</strong>
        </p>
      </div>
    </AppShell>
  );
}
