import { describe, expect, it } from "vitest";
import { mappingRevisionLabels } from "./mappingDraft";

describe("quiet draft feedback vs saved-model validation", () => {
  it("keeps draft revision copy separate from validation headlines", () => {
    const labels = mappingRevisionLabels({
      dirty: true,
      draftRoles: { DA_T: "sat", SF_SPD: "" },
      savedRoles: { DA_T: "sat", SF_SPD: "fan_speed" },
      savedAuthorityLabel: "Saved column map",
      activeIngestRevision: "rev-1",
    });

    expect(labels.draft).toMatch(/^Draft:/);
    expect(labels.draft).toContain("SF_SPD unmapped");
    expect(labels.saved).toMatch(/^Saved column map:/);
    expect(labels.saved).toContain("DA_T → sat");
    expect(labels.active).toBe("Active ingest: rev-1");

    // Saved-model validation chrome (`summarizeMappingValidation`) uses a
    // different vocabulary and must not reuse quiet Draft: feedback.
    const validationHeadlines = [
      "Validation: validated",
      "Validation: incomplete",
      "Validation: not evaluated",
    ];
    for (const headline of validationHeadlines) {
      expect(headline).not.toMatch(/Draft:/);
      expect(labels.draft).not.toBe(headline);
      expect(labels.saved).not.toBe(headline);
    }
  });

  it("reports a quiet match when draft equals saved", () => {
    const labels = mappingRevisionLabels({
      dirty: false,
      draftRoles: { DA_T: "sat" },
      savedRoles: { DA_T: "sat" },
      savedAuthorityLabel: "Saved column map",
      activeIngestRevision: null,
    });
    expect(labels.draft).toBe("Draft: matches saved");
    expect(labels.saved).toContain("DA_T → sat");
  });
});
