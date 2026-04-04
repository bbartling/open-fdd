/**
 * Brick RDF **class** local names (no `brick:` prefix) used by predefined Data Model Testing SPARQL.
 * Curated to match **Brick Schema 1.4.x** vocabulary — same identifiers the TTL builder emits for `rdf:type`.
 *
 * When adding a preset that introduces `brick:New_Class`, append it here and extend the LLM prompt
 * `equipment_type` list in `docs/modeling/llm_workflow.md` so AI-assisted import stays button-testable.
 *
 * Predicate names (`feeds`, `isPointOf`, …) are **not** classes and must not appear here.
 */
export const BRICK_14_QUERY_CLASS_ALLOWLIST = new Set<string>([
  "Site",
  "Building",
  "Floor",
  "HVAC_Equipment",
  "HVAC_Zone",
  "Equipment",
  "Point",
  "Air_Handling_Unit",
  "Variable_Air_Volume_Box",
  "Variable_Air_Volume_Box_With_Reheat",
  "Chiller",
  "Cooling_Tower",
  "Boiler",
  "Heat_Exchanger",
  "Water_Pump",
  "Chilled_Water_System",
  "Condenser_Water_System",
  "Hot_Water_System",
  "Building_Electrical_Meter",
  "Electrical_Energy_Usage_Sensor",
]);

/** Predicates in the Brick namespace that appear as `brick:local` but are not classes. */
export const BRICK_PREDICATE_LOCAL_NAMES = new Set<string>([
  "feeds",
  "isFedBy",
  "isPointOf",
  "isPartOf",
]);
