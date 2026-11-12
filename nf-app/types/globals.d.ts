// Globals shared between the classic <script> files that are NOT declared by a script itself
// (functions/consts a script declares at top level are already global to the page's program).
declare const echarts: any;                       // vendored ECharts, exposed by echarts-global.js (options stay `any`)
declare var ofddUnits: any;                       // static/units.js (classic global / CommonJS export)
declare var ofddExport: any;
declare var ofddTuning: any;
declare var ofddRoleLimits: any;
declare var OfddPaging: any;                      // static/paging.js (shared/paging.js): the one pager, also required by the hooks
declare const fddRulePlot: any;
interface Window { echarts: any; ofddUnits: any; Clerk: any; }
/** What `$(id)` returns in the page scripts: an element plus the form-control/table/link props the wiring reads and writes. */
interface AnyEl extends HTMLElement {
  value: string; checked: boolean; disabled: boolean; href: string;
  rows: HTMLCollectionOf<HTMLTableRowElement>; options: HTMLOptionsCollection;
}

