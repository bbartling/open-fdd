/** Natural compare so AHU_1 sorts before AHU_10. */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

export function naturalSorted<T>(items: T[], key: (item: T) => string): T[] {
  return [...items].sort((x, y) => naturalCompare(key(x), key(y)));
}
