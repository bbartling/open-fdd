import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { FaultList } from "./FaultList";
import type {
  Site,
  Equipment,
  Point,
  FaultState,
  FaultDefinition,
} from "@/types/api";

interface SiteCardProps {
  site: Site;
  equipment: Equipment[];
  points: Point[];
  faults: FaultState[];
  definitions: FaultDefinition[];
  onSelect: (siteId: string) => void;
}

export function SiteCard({
  site,
  equipment,
  points,
  faults,
  definitions,
  onSelect,
}: SiteCardProps) {
  const hasFaults = faults.length > 0;

  return (
    <button
      type="button"
      onClick={() => onSelect(site.id)}
      className="group block h-full w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-2xl"
    >
      <Card className="h-full transition-shadow duration-200 group-hover:shadow-md group-hover:shadow-black/[0.06]">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle className="truncate">{site.name}</CardTitle>
              {site.description && (
                <CardDescription className="mt-1 truncate">
                  {site.description}
                </CardDescription>
              )}
            </div>
            <span
              className={`mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
                hasFaults ? "bg-destructive" : "bg-success"
              }`}
              aria-label={hasFaults ? "Has active faults" : "No faults"}
            />
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex gap-5 text-sm">
            <span className="text-muted-foreground">
              <span className="font-medium tabular-nums text-foreground">
                {equipment.length}
              </span>{" "}
              equip
            </span>
            <span className="text-muted-foreground">
              <span className="font-medium tabular-nums text-foreground">
                {points.length}
              </span>{" "}
              points
            </span>
            <span className="text-muted-foreground">
              <span className={`font-medium tabular-nums ${hasFaults ? "text-destructive" : "text-success"}`}>
                {faults.length}
              </span>{" "}
              fault{faults.length !== 1 ? "s" : ""}
            </span>
          </div>

          <FaultList
            faults={faults}
            definitions={definitions}
            equipment={equipment}
          />
        </CardContent>
      </Card>
    </button>
  );
}
