/** Shared props for parity widget primitives (P1-M3-02). */
export interface WidgetBaseProps {
  id: string;
  label: string;
  description?: string;
  disabled?: boolean;
  loading?: boolean;
  error?: string;
  testId?: string;
  density?: "comfortable" | "compact";
}

export function widgetTestId(base: string, testId?: string): string {
  return testId ?? base;
}
