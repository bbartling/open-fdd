import { catalogByCategory, NODE_CATEGORIES } from "./nodeCatalog";
import type { NodeCatalogEntry } from "./types";

type Props = {
  onAdd: (entry: NodeCatalogEntry) => void;
};

export default function WiresheetPalette({ onAdd }: Props) {
  const grouped = catalogByCategory();

  return (
    <aside className="wiresheet-palette" aria-label="Node palette">
      <h3 className="wiresheet-panel-title">Nodes</h3>
      <p className="muted wiresheet-panel-hint">Click to place on canvas</p>
      {NODE_CATEGORIES.map((cat) => {
        const items = grouped.get(cat) ?? [];
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
