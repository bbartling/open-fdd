// Globals the Lite pages share that no script declares itself (top-level declarations of one
// script are already global to the page's program). ECharts is loaded by a vendored classic script.
declare const echarts: any;
declare var ofddUnits: any;                       // Full only (units.js); the shared charts.js / app-core.js test for it
declare var rcxCurrentOutputSeries: any;          // Full only (rcx.js); app-core.js test for it
declare var OfddPaging: any;                      // static/paging.js (shared/paging.js): the one pager, also required by the hooks
interface Window { echarts: any; Clerk: any; }
/** What `$(id)` returns in the page scripts: an element plus the form-control/table/link props the wiring reads and writes. */
interface AnyEl extends HTMLElement {
  value: string; checked: boolean; disabled: boolean; href: string;
  rows: HTMLCollectionOf<HTMLTableRowElement>; options: HTMLOptionsCollection;
}
