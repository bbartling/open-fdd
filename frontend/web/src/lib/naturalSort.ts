/** Natural compare so AHU_2 sorts before AHU_10 (vibe19 equipment lists). */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

export function naturalSorted(ids: string[]): string[] {
  return [...ids].sort(naturalCompare);
}
