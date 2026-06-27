import { catalogByCategory, NODE_CATEGORIES } from "./nodeCatalog";
import type { NodeCatalogEntry } from "./types";

type Props = {
  onAdd: (entry: NodeCatalogEntry) => void;
  categories?: readonly string[];
  /** Hide CSV/transform nodes — FDD rule mapping studio only */
  fddMode?: boolean;
};

export default function WiresheetPalette({ onAdd, categories, fddMode }: Props) {
  const grouped = catalogByCategory();
  const visibleCategories = categories ?? NODE_CATEGORIES;

  return (
    <aside className="wiresheet-palette" aria-label="Node palette">
      <h3 className="wiresheet-panel-title">Nodes</h3>
      <p className="muted wiresheet-panel-hint">Click to place on canvas</p>
      {visibleCategories.map((cat) => {
        const items = (grouped.get(cat) ?? []).filter(
          (e) => !fddMode || (e.type !== "csv_source" && !String(e.type).startsWith("transform_")),
        );
        if (!items.length) return null;
        return (
          <section key={cat} className="wiresheet-palette__section">
            <h4 className="wiresheet-palette__category">{cat}</h4>
            <ul className="wiresheet-palette__list">
              {items.map((entry) => (
                <li key={`${cat}-${entry.label}`}>
                  <button
                    type="button"
                    className="wiresheet-palette__item"
                    onClick={() => onAdd(entry)}
                    title={entry.description}
                  >
                    <span className="wiresheet-palette__dot" style={{ background: entry.accent }} />
                    <span>{entry.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </aside>
  );
}
