import { useEffect, useState } from "react";

export type ContextMenuItem = {
  id: string;
  label: string;
  disabled?: boolean;
  danger?: boolean;
  onClick?: () => void;
  children?: ContextMenuItem[];
};

type Props = {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
};

function ContextMenuRow({
  item,
  onClose,
}: {
  item: ContextMenuItem;
  onClose: () => void;
}) {
  const [open, setOpen] = useState(false);
  const hasChildren = Boolean(item.children?.length);

  if (hasChildren) {
    return (
      <div
        className="context-menu-submenu"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <button
          type="button"
          role="menuitem"
          className="context-menu-item context-menu-item-parent"
          disabled={item.disabled}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          <span>{item.label}</span>
          <span className="context-menu-chevron" aria-hidden>
            ▸
          </span>
        </button>
        {open ? (
          <div className="context-menu context-menu-flyout" role="menu">
            {item.children!.map((child) => (
              <ContextMenuRow key={child.id} item={child} onClose={onClose} />
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <button
      type="button"
      role="menuitem"
      className={`context-menu-item${item.danger ? " danger" : ""}`}
      disabled={item.disabled}
      onClick={() => {
        item.onClick?.();
        onClose();
      }}
    >
      {item.label}
    </button>
  );
}

export default function ContextMenu({ x, y, items, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <button type="button" className="context-menu-backdrop" aria-label="Close menu" onClick={onClose} />
      <div className="context-menu" style={{ left: x, top: y }} role="menu">
        {items.map((item) => (
          <ContextMenuRow key={item.id} item={item} onClose={onClose} />
        ))}
      </div>
    </>
  );
}
