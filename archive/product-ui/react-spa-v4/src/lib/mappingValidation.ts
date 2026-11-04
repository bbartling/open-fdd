import type {
  MappingValidationCheck,
  PackageMappingResponse,
} from "../api/mappingApi";
import { activeIngestRevision } from "./mappingDraft";

export type ValidationHeadline = "validated" | "incomplete" | "not_evaluated";

export interface MappingValidationSummary {
  status: ValidationHeadline;
  headline: string;
  checks: MappingValidationCheck[];
  sourceLabel: string;
}

const PROVENANCE = "mapping_revision_v1";

function phrase(status: string): string {
  if (status === "not_evaluated") return "not evaluated";
  return status;
}

export function checkLine(check: MappingValidationCheck): string {
  const head = `${check.label}: ${phrase(check.status)}`;
  const detail = (check.detail ?? "").trim();
  return detail ? `${head} — ${detail}` : head;
}

export function sourceLabelFromChecks(checks: MappingValidationCheck[]): string {
  const evaluated = checks
    .filter((check) => check.status !== "not_evaluated")
    .map((check) => check.label);
  const skipped = checks
    .filter((check) => check.status === "not_evaluated")
    .map((check) => check.label);
  const evaluatedText = evaluated.length > 0 ? evaluated.join(", ") : "nothing";
  const skippedText = skipped.length > 0 ? skipped.join(", ") : "nothing";
  return `Evaluated: ${evaluatedText}. Not evaluated: ${skippedText}.`;
}

function headlineFor(status: ValidationHeadline): string {
  if (status === "validated") return "Validation: validated";
  if (status === "incomplete") return "Validation: incomplete";
  return "Validation: not evaluated";
}

function rollup(checks: MappingValidationCheck[]): ValidationHeadline {
  const failed = checks.some(
    (check) =>
      check.status === "fail" ||
      check.status === "incomplete" ||
      check.status === "warning",
  );
  if (failed) return "incomplete";
  if (checks.length === 0 || checks.some((check) => check.status === "not_evaluated")) {
    return "not_evaluated";
  }
  if (checks.every((check) => check.status === "pass")) return "validated";
  return "not_evaluated";
}

type MappingSource = "timescale_sample" | "historian_inventory" | "csv_column_map";

function classifySource(inventory: PackageMappingResponse): MappingSource {
  if (inventory.source === "timescale_sample") return "timescale_sample";
  if ((inventory.warnings ?? []).some((warning) => warning.includes("historian-backed"))) {
    return "historian_inventory";
  }
  return "csv_column_map";
}

function count(validation: PackageMappingResponse["validation"], key: "blocker_count" | "warning_count"): number {
  const value = validation?.[key];
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function stampIncomplete(inventory: PackageMappingResponse): boolean {
  return (inventory.equipment ?? []).some((equipment) => {
    const type = (equipment.equipment_type ?? "").trim().toLowerCase();
    return type.length === 0 || type === "unclassified";
  });
}

function columnDetail(blockers: number, warnings: number): string {
  if (blockers > 0 && warnings > 0) {
    return `${blockers} blocker(s), ${warnings} warning(s)`;
  }
  if (blockers > 0) return `${blockers} blocker(s)`;
  if (warnings > 0) return `${warnings} warning(s)`;
  return "Column roles were checked.";
}

function deriveChecks(inventory: PackageMappingResponse): MappingValidationCheck[] {
  const source = classifySource(inventory);
  const blockers = count(inventory.validation, "blocker_count");
  const warnings = count(inventory.validation, "warning_count");
  const revision = activeIngestRevision(inventory);

  let column: MappingValidationCheck;
  if (source === "timescale_sample") {
    column = {
      id: "column_role_map",
      label: "Column role map",
      status: "not_evaluated",
      detail: "CSV column map was not read.",
    };
  } else if (source === "historian_inventory" && warnings === 0 && blockers === 0) {
    column = {
      id: "column_role_map",
      label: "Column role map",
      status: "not_evaluated",
      detail: "Historian inventory did not report a column-role result.",
    };
  } else if (blockers > 0) {
    column = {
      id: "column_role_map",
      label: "Column role map",
      status: "fail",
      detail: columnDetail(blockers, warnings),
    };
  } else if (warnings > 0) {
    column = {
      id: "column_role_map",
      label: "Column role map",
      status: "warning",
      detail: columnDetail(blockers, warnings),
    };
  } else {
    column = {
      id: "column_role_map",
      label: "Column role map",
      status: "pass",
      detail: columnDetail(blockers, warnings),
    };
  }

  const sample: MappingValidationCheck =
    source === "timescale_sample"
      ? {
          id: "sample_role_keys",
          label: "Sample role keys",
          status: "pass",
          detail: "Listed from historian sample keys.",
        }
      : {
          id: "sample_role_keys",
          label: "Sample role keys",
          status: "not_evaluated",
          detail: "Historian sample keys were not the mapping source.",
        };

  const stamp: MappingValidationCheck = stampIncomplete(inventory)
    ? {
        id: "equipment_stamp",
        label: "Equipment stamp",
        status: "incomplete",
        detail: "Type is unclassified.",
      }
    : {
        id: "equipment_stamp",
        label: "Equipment stamp",
        status: "not_evaluated",
        detail: "A stored type string was not checked against a semantic model.",
      };

  const active: MappingValidationCheck = {
    id: "active_ingest_plan",
    label: "Active ingest plan",
    status: "not_evaluated",
    detail: revision
      ? `Active ingest revision ${revision} is loaded. This response did not compare the mapping to that plan.`
      : "No active ingest revision is loaded for this request.",
  };

  return [
    sample,
    column,
    stamp,
    {
      id: "semantic_tags",
      label: "Semantic tags",
      status: "not_evaluated",
      detail: "No semantic model was checked.",
    },
    {
      id: "kind_unit",
      label: "Kind and unit",
      status: "not_evaluated",
      detail: "Kind and unit were not checked.",
    },
    {
      id: "provider_bindings",
      label: "Provider bindings",
      status: "not_evaluated",
      detail: "Provider bindings were not checked.",
    },
    active,
  ];
}

function fromServer(inventory: PackageMappingResponse): MappingValidationSummary {
  const checks = inventory.validation?.checks ?? [];
  const status = rollup(checks);
  const provided = (inventory.validation?.source_label ?? "").trim();
  return {
    status,
    headline: headlineFor(status),
    checks,
    sourceLabel: provided || sourceLabelFromChecks(checks),
  };
}

/** One summary. A zero issue count is not a pass for a check that did not run. */
export function summarizeMappingValidation(
  inventory: PackageMappingResponse | null,
): MappingValidationSummary | null {
  if (!inventory?.validation) return null;
  if (
    inventory.validation.provenance === PROVENANCE &&
    (inventory.validation.checks?.length ?? 0) > 0
  ) {
    return fromServer(inventory);
  }
  const checks = deriveChecks(inventory);
  const status = rollup(checks);
  return {
    status,
    headline: headlineFor(status),
    checks,
    sourceLabel: sourceLabelFromChecks(checks),
  };
}
