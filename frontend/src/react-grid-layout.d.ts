declare module "react-grid-layout" {
  import type { ComponentType, ReactNode } from "react";

  export interface LayoutItem {
    i: string;
    x: number;
    y: number;
    w: number;
    h: number;
  }

  export type Layout = LayoutItem[];

  export interface GridLayoutProps {
    className?: string;
    layout: Layout;
    onLayoutChange?: (layout: Layout) => void;
    cols?: number;
    rowHeight?: number;
    width?: number;
    draggableHandle?: string;
    isDraggable?: boolean;
    isResizable?: boolean;
    compactType?: "vertical" | "horizontal" | null;
    preventCollision?: boolean;
    children?: ReactNode;
  }

  const GridLayout: ComponentType<GridLayoutProps>;
  export { GridLayout };
}
