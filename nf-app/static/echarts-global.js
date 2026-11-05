// ECharts 5.5.1 is vendored as an ES module (no CDN). The page scripts are classic
// `defer` scripts that run after this module, in document order, so expose it once here.
import * as echarts from "./vendor/echarts.esm.min.js";

window.echarts = echarts;
