import { cn } from "@/lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "destructive" | "success" | "warning" | "outline";
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium tracking-wide",
        {
          "bg-primary/10 text-primary": variant === "default",
          "bg-secondary text-secondary-foreground": variant === "secondary",
          "bg-destructive/10 text-destructive": variant === "destructive",
          "bg-success/10 text-success": variant === "success",
          "bg-warning/10 text-warning-foreground": variant === "warning",
          "border border-border/60 text-muted-foreground": variant === "outline",
        },
        className,
      )}
      {...props}
    />
  );
}

export { Badge };
export type { BadgeProps };
