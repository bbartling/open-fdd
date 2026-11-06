// Globals shared between the classic <script> files (see static/index.html load order).
declare const echarts: any;
declare function api(path: string, body?: unknown): Promise<any>;
declare function queryAll(body: unknown): Promise<any[]>;
declare function field(property: string, text: string): unknown;
declare function esc(s: unknown): string;
declare const model: any;
declare const scope: { site: string; equip: string };
declare function ofddChart(el: Element): any;
declare function ofddRender(chart: any, option: any, name?: string): void;
declare const FAULT_LANE: any;
declare function fetchSeries(list: any[], hours: number, opts?: any): Promise<Map<string, [number, number][]>>;
declare function pickWindow(hours: number): number;
interface Window { ofddUnits: any; Clerk: any; }
