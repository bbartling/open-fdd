export type BuilderState = {
  name: string;
  input: string;
  operator: string;
  value: number;
  equipment_id: string;
  confirmation_seconds: number;
  severity: string;
  fault_code: string;
};

export type FddInput = {
  id: string;
  label: string;
  unit?: string;
  equipment_types?: string[];
};

export type SchemaColumn = {
  name: string;
  type: string;
  is_primary?: boolean;
  fdd_input?: boolean;
  unit?: string;
};

export type SchemaTable = {
  name: string;
  description?: string;
  columns: SchemaColumn[] | string[];
};

export type EquipmentRow = {
  id?: string;
  equipment_id?: string;
  name?: string;
  equipment_type?: string;
};

export function ruleIdFromBuilder(builder: BuilderState): string {
  const base = builder.fault_code.trim() || builder.name.trim() || "fdd-rule";
  return base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "fdd-rule";
}

export const DEFAULT_BUILDER: BuilderState = {
  name: "OA Temperature Out Of Range",
  input: "oa_t",
  operator: ">",
  value: 110,
  equipment_id: "",
  confirmation_seconds: 300,
  severity: "medium",
  fault_code: "OA_TEMP_OUT_OF_RANGE",
};
