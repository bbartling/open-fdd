// GENERATED COPY of shared/types/shapes.d.ts by scripts/nf/sync_shared.py: edit the source, then re-run the script.
// Shared data shapes (global types; used from JSDoc as {OfddPoint}, {OfddModel}, ...).

/** A raw NF point/entity record (point/query result row). */
interface NfRecord {
  uuid: string; name: string; pointType?: string; latestValue?: any;
  attrs?: Record<string, string>; [k: string]: any;
}

/** A point as model.js toPoint() builds it. */
interface OfddPoint {
  uuid: string; tags: string[]; dis: string; units: string; kind: string; name: string;
  equipRef: string; weatherStationRef: string; siteRef: string; deviceRef: string;
  objectId: string; bacnet: string; cls: string; latest: any; rec: NfRecord;
}

/** The loadModel() result: entity records plus every point on every modeled site. */
interface OfddModel { sites: NfRecord[]; equips: NfRecord[]; devices: NfRecord[]; points: OfddPoint[]; }

/** Roles bound to points on one equipment: { role: [points] }. */
type OfddBound = Record<string, OfddPoint[]>;

/** An equipment that can feed a view/rule: rcxBind() / bindRoles() output. */
interface OfddEquip { rec: NfRecord; id: string; name: string; kinds: string[]; bound: OfddBound; }

/** One rule of static/fdd-catalog.json (built by scripts/nf/build_rule_catalog.py). */
interface CatalogRule {
  id: string; equipment_kinds?: string[]; required_roles?: string[]; optional_roles?: string[];
  [k: string]: any;
}

/** static/fdd-catalog.json. */
interface FddCatalog {
  equipment_kinds: Record<string, string[]>; rules: CatalogRule[]; roles?: Record<string, any>;
  [k: string]: any;
}

/** An RCx view definition (rcxView(def)); see the header of static/rcx.js. */
interface RcxViewDef {
  id: string; group: string; title: string; kinds?: string[];
  roles?: { required: string[]; optional?: string[] };
  scope?: "equip" | "site"; minEquips?: number; hours?: number;
  render: (el: HTMLElement, ctx: RcxContext) => Promise<string | void> | string | void;
  [k: string]: any;
}

/** What a view's render() receives (rcxContext()). Chart options stay `any` (ECharts). */
interface RcxContext {
  view: RcxViewDef; equips: OfddEquip[]; hours: number; model: OfddModel; catalog: FddCatalog; range: any; siteTz: string;
  first(eq: OfddEquip, role: string): OfddPoint | null;
  series(pts: OfddPoint[], o?: { hours?: number; method?: string; windowSec?: number }): Promise<Map<string, [number, number][]>>;
  aligned(cols: Record<string, OfddPoint>, o?: { hours?: number; method?: string; windowSec?: number }): Promise<{ t: number[]; cols: Record<string, (number | null)[]> }>;
  alignedFine(cols: Record<string, OfddPoint>, o?: { hours?: number; method?: string; windowSec?: number }): Promise<{ t: number[]; cols: Record<string, (number | null)[]>; windowSec: number; fine: boolean }>;
  chart(el: Element): any;
  siUnit(p: OfddPoint): string;
  disp(v: number, siUnit: string): { value: number; unit: string };
  dispDelta(d: number, siUnit: string): { value: number; unit: string };
  dispUnit(siUnit: string): string;
  dispSystem(): string;
  dispSeries(arr: any[][], siUnit: string, delta?: boolean): [number, number][];
  unit(p: OfddPoint): string;
  weather: OfddPoint[];
}
