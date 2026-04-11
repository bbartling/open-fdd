import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import type { EnergyCalculation, Equipment } from "@/types/api";
import { Box, ChevronDown, ChevronRight, Layers, MoreVertical, Zap, ZapOff } from "lucide-react";

type CalcLeaf = { type: "calc"; calc: EnergyCalculation };
type FolderNode = {
  type: "folder";
  id: string;
  name: string;
  equipment_type: string | null;
  children: CalcLeaf[];
};

function buildFolders(equipment: Equipment[], calcs: EnergyCalculation[]): FolderNode[] {
  const byEq = new Map<string, EnergyCalculation[]>();
  const siteLevel: EnergyCalculation[] = [];
  for (const c of calcs) {
    if (c.equipment_id) {
      const list = byEq.get(c.equipment_id) ?? [];
      list.push(c);
      byEq.set(c.equipment_id, list);
    } else {
      siteLevel.push(c);
    }
  }
  const sortCalcs = (a: EnergyCalculation, b: EnergyCalculation) =>
    a.external_id.localeCompare(b.external_id);

  const folders: FolderNode[] = [
    {
      type: "folder",
      id: "__site_level__",
      name: "Site-level",
      equipment_type: null,
      children: [...siteLevel].sort(sortCalcs).map((calc) => ({ type: "calc" as const, calc })),
    },
  ];
  for (const eq of [...equipment].sort((a, b) => a.name.localeCompare(b.name))) {
    const children = (byEq.get(eq.id) ?? []).sort(sortCalcs).map((calc) => ({
      type: "calc" as const,
      calc,
    }));
    folders.push({
      type: "folder",
      id: eq.id,
      name: eq.name,
      equipment_type: eq.equipment_type,
      children,
    });
  }
  return folders;
}

export const ENERGY_CALC_CONTEXT_TEST_IDS = {
  ENABLE: "energy-calc-context-enable",
  DISABLE: "energy-calc-context-disable",
  DELETE: "energy-calc-context-delete",
} as const;

type MenuState = { x: number; y: number; calc: EnergyCalculation } | null;

export interface EnergyCalcsTreeProps {
  equipment: Equipment[];
  calculations: EnergyCalculation[];
  onDeleteCalc: (id: string, name: string) => void;
  onSetEnabled: (id: string, enabled: boolean) => void;
}

export function EnergyCalcsTree({
  equipment,
  calculations,
  onDeleteCalc,
  onSetEnabled,
}: EnergyCalcsTreeProps) {
  const folders = useMemo(
    () => buildFolders(equipment, calculations),
    [equipment, calculations],
  );

  const [openIds, setOpenIds] = useState<Set<string>>(() => {
    const s = new Set<string>();
    folders.forEach((f) => s.add(f.id));
    return s;
  });
  const [menu, setMenu] = useState<MenuState>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

  useEffect(() => {
    if (!menu) return;
    requestAnimationFrame(() => {
      menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    });
  }, [menu]);

  const onMenuKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const root = menuRef.current;
    if (!root) return;
    const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>("button")).filter(
      (b) => !b.disabled,
    );
    if (buttons.length === 0) return;
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (e.shiftKey) {
      if (i <= 0) {
        e.preventDefault();
        buttons[buttons.length - 1]?.focus();
      }
    } else if (i === buttons.length - 1 || i === -1) {
      e.preventDefault();
      buttons[0]?.focus();
    }
  }, []);

  const toggle = useCallback((id: string) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleCalcContextMenu = useCallback((e: React.MouseEvent, calc: EnergyCalculation) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, calc });
  }, []);

  const openCalcMenuAt = useCallback((calc: EnergyCalculation, clientX: number, clientY: number) => {
    setMenu({ x: clientX, y: clientY, calc });
  }, []);

  if (calculations.length === 0 && equipment.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No equipment for this site yet. Add equipment on Data Model BRICK, then attach calculations to devices or leave
        them under Site-level.
      </p>
    );
  }

  if (calculations.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No energy calculations yet. Use the form below or import JSON from your LLM workflow.
      </p>
    );
  }

  return (
    <div className="relative rounded-lg border border-border/60">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40 hover:bg-muted/40">
            <TableHead className="w-[28px]" aria-hidden />
            <TableHead className="min-w-[200px]">Name / id</TableHead>
            <TableHead className="min-w-[160px]">Calc type</TableHead>
            <TableHead className="w-[90px]">State</TableHead>
            <TableHead className="w-10 p-2 text-center">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {folders.map((folder) => {
            const open = openIds.has(folder.id);
            const Icon = folder.id === "__site_level__" ? Layers : Box;
            return (
              <FolderBlock
                key={folder.id}
                folder={folder}
                depth={0}
                open={open}
                onToggle={toggle}
                Icon={Icon}
                onCalcContextMenu={handleCalcContextMenu}
                onOpenCalcMenu={openCalcMenuAt}
                menuCalcId={menu?.calc.id ?? null}
              />
            );
          })}
        </TableBody>
      </Table>
      {menu && (
        <>
          <div
            className="fixed inset-0 z-40"
            aria-hidden
            onClick={() => setMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu(null);
            }}
          />
          <div
            ref={menuRef}
            className="fixed z-50 min-w-[180px] rounded-lg border border-border/60 bg-card py-1 shadow-lg"
            style={{ left: menu.x, top: menu.y }}
            role="menu"
            aria-label="Energy calculation actions"
            onKeyDown={onMenuKeyDown}
          >
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-40"
              data-testid={ENERGY_CALC_CONTEXT_TEST_IDS.ENABLE}
              disabled={menu.calc.enabled}
              onClick={() => {
                onSetEnabled(menu.calc.id, true);
                setMenu(null);
              }}
            >
              <Zap className="h-4 w-4 text-primary" />
              Enable
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-40"
              data-testid={ENERGY_CALC_CONTEXT_TEST_IDS.DISABLE}
              disabled={!menu.calc.enabled}
              onClick={() => {
                onSetEnabled(menu.calc.id, false);
                setMenu(null);
              }}
            >
              <ZapOff className="h-4 w-4 text-muted-foreground" />
              Disable
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10"
              data-testid={ENERGY_CALC_CONTEXT_TEST_IDS.DELETE}
              onClick={() => {
                onDeleteCalc(menu.calc.id, menu.calc.name);
                setMenu(null);
              }}
            >
              Delete calculation
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function FolderBlock({
  folder,
  depth,
  open,
  onToggle,
  Icon,
  onCalcContextMenu,
  onOpenCalcMenu,
  menuCalcId,
}: {
  folder: FolderNode;
  depth: number;
  open: boolean;
  onToggle: (id: string) => void;
  Icon: typeof Box;
  onCalcContextMenu: (e: React.MouseEvent, calc: EnergyCalculation) => void;
  onOpenCalcMenu: (calc: EnergyCalculation, clientX: number, clientY: number) => void;
  menuCalcId: string | null;
}) {
  const indent = depth * 18;
  const count = folder.children.length;

  return (
    <>
      <TableRow
        className="cursor-pointer border-border/40 bg-muted/20 hover:bg-muted/40"
        onClick={() => onToggle(folder.id)}
      >
        <TableCell className="w-[28px] py-1.5" style={{ paddingLeft: 12 + indent }}>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded p-0.5 hover:bg-muted"
            aria-expanded={open}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(folder.id);
            }}
          >
            {open ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
        </TableCell>
        <TableCell className="py-1.5" style={{ paddingLeft: indent }}>
          <span className="inline-flex items-center gap-2 font-medium">
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
            {folder.name}
            {folder.equipment_type && (
              <span className="rounded border border-border/60 bg-background px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
                {folder.equipment_type}
              </span>
            )}
            <span className="text-muted-foreground text-xs tabular-nums">({count})</span>
          </span>
        </TableCell>
        <TableCell colSpan={3} />
      </TableRow>
      {open &&
        folder.children.map(({ calc }) => (
          <TableRow
            key={calc.id}
            className="border-border/40"
            onContextMenu={(e) => onCalcContextMenu(e, calc)}
          >
            <TableCell className="w-[28px]" style={{ paddingLeft: 12 + indent + 18 }} />
            <TableCell className="font-mono text-xs" style={{ paddingLeft: indent + 18 }}>
              <span className="text-foreground">{calc.external_id}</span>
              <span className="ml-2 text-muted-foreground">{calc.name}</span>
            </TableCell>
            <TableCell className="text-muted-foreground text-xs">{calc.calc_type}</TableCell>
            <TableCell>
              {calc.enabled ? (
                <span className="inline-flex items-center gap-1 text-xs text-primary" title="Enabled">
                  <Zap className="h-4 w-4" />
                  on
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title="Disabled">
                  <ZapOff className="h-4 w-4" />
                  off
                </span>
              )}
            </TableCell>
            <TableCell className="w-10 p-1 text-center">
              <button
                type="button"
                className="inline-flex rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={`Actions for ${calc.name}`}
                aria-haspopup="menu"
                aria-expanded={menuCalcId === calc.id}
                onClick={(e) => {
                  e.stopPropagation();
                  const r = e.currentTarget.getBoundingClientRect();
                  onOpenCalcMenu(calc, r.left, Math.min(r.bottom + 4, window.innerHeight - 120));
                }}
              >
                <MoreVertical className="h-4 w-4" aria-hidden />
              </button>
            </TableCell>
          </TableRow>
        ))}
    </>
  );
}
