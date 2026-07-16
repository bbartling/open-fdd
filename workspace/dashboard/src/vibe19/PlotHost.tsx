import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";

export function PlotHost({
  data,
  layout,
  config,
  height = 320,
}: {
  data: object[];
  layout: object;
  config?: object;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    void (Plotly as any).react(el, data, { ...layout, autosize: true, height }, {
      displaylogo: false,
      responsive: true,
      ...config,
    });
    return () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      void (Plotly as any).purge(el);
    };
  }, [data, layout, config, height]);

  return <div ref={ref} style={{ width: "100%", minHeight: height }} />;
}
