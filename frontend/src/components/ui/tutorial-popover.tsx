import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

export interface TutorialPopoverProps {
  children: React.ReactNode;
  title: string;
  meaning: string;
  status: string;
  className?: string;
  side?: "top" | "bottom" | "left" | "right";
}

const HIDE_DELAY_MS = 150;

export function TutorialPopover({
  children,
  title,
  meaning,
  status,
  className,
  side = "bottom",
}: TutorialPopoverProps) {
  const [open, setOpen] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const scheduleHide = () => {
    hideTimerRef.current = setTimeout(() => setOpen(false), HIDE_DELAY_MS);
  };
  const cancelHide = () => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = undefined;
  };

  useEffect(() => () => cancelHide(), []);

  const positionClass =
    side === "top"
      ? "bottom-full left-1/2 -translate-x-1/2 mb-2"
      : side === "bottom"
        ? "top-full left-1/2 -translate-x-1/2 mt-2"
        : side === "left"
          ? "right-full top-1/2 -translate-y-1/2 mr-2"
          : "left-full top-1/2 -translate-y-1/2 ml-2";

  return (
    <div
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => {
        cancelHide();
        setOpen(true);
      }}
      onMouseLeave={() => scheduleHide()}
    >
      {children}
      {open && (
        <div
          onMouseEnter={cancelHide}
          onMouseLeave={scheduleHide}
          className={cn(
            "absolute z-50 w-72 rounded-lg border border-border bg-card p-3 text-foreground shadow-lg",
            positionClass,
          )}
          role="tooltip"
        >
          <p className="font-medium text-foreground">{title}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            <span className="font-medium">Meaning:</span> {meaning}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            <span className="font-medium">Status:</span> {status}
          </p>
        </div>
      )}
    </div>
  );
}
