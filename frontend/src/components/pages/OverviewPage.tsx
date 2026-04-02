import { useSiteContext } from "@/contexts/site-context";
import { SiteCard } from "@/components/dashboard/SiteCard";
import { FddStatusBanner } from "@/components/dashboard/FddStatusBanner";
import { FaultList } from "@/components/dashboard/FaultList";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useSites, useAllEquipment, useAllPoints, useEquipment, usePoints } from "@/hooks/use-sites";
import { useActiveFaults, useFaultDefinitions, useSiteFaults } from "@/hooks/use-faults";
import { useCapabilities } from "@/hooks/use-fdd-status";

const DOCS_SITE = "https://bbartling.github.io/open-fdd";
const DOCS_PDF_ONLINE =
  "https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf";

/** Help links for external agents; Open-FDD does not call LLMs from the UI. */
function ModelContextCard() {
  const { data: capabilities } = useCapabilities();

  const linkCls =
    "text-primary underline-offset-2 hover:underline font-medium break-words";

  return (
    <Card className="mt-6">
      <CardContent className="pt-6 space-y-3">
        <div>
          <h2 className="text-sm font-medium text-muted-foreground">
            External agents &amp; documentation
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Use your own OpenAI-compatible stack with the API. Full HTTP details and agent workflows are in the published docs —
            start here:
          </p>
          <ul className="mt-2 list-disc pl-4 text-xs text-muted-foreground space-y-1">
            <li>
              <a href={DOCS_SITE} className={linkCls} target="_blank" rel="noopener noreferrer">
                Documentation (GitHub Pages)
              </a>{" "}
              — quick start, stack, reference
            </li>
            <li>
              <a href={DOCS_PDF_ONLINE} className={linkCls} target="_blank" rel="noopener noreferrer">
                Documentation PDF
              </a>{" "}
              — offline / print-friendly (in a clone:{" "}
              <code className="rounded bg-muted px-1 text-[11px]">pdf/open-fdd-docs.pdf</code>)
            </li>
            <li>
              <a
                href={`${DOCS_SITE}/modeling/llm_workflow#copy-paste-prompt-template-recommended`}
                className={linkCls}
                target="_blank"
                rel="noopener noreferrer"
              >
                LLM prompt (copy/paste template)
              </a>{" "}
              — same section as{" "}
              <a href={`${DOCS_SITE}/modeling/llm_workflow`} className={linkCls} target="_blank" rel="noopener noreferrer">
                LLM workflow
              </a>{" "}
              (no trailing slash on that path)
            </li>
            <li>
              <a href={`${DOCS_SITE}/openclaw_integration`} className={linkCls} target="_blank" rel="noopener noreferrer">
                Open‑Claw / external agent integration
              </a>{" "}
              — model context, MCP manifest, export/import
            </li>
          </ul>
        </div>
        {capabilities && (
          <p className="text-xs text-muted-foreground">
            API <span className="font-medium">v{capabilities.version}</span> — built-in{" "}
            <code className="rounded bg-muted px-1">ai_available</code> is{" "}
            <span className="font-medium">{String(capabilities.ai_available)}</span>; use external tooling and the links above.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function AllSitesView() {
  const { setSelectedSiteId } = useSiteContext();
  const { data: sites, isLoading: sitesLoading } = useSites();
  const { data: equipment = [] } = useAllEquipment();
  const { data: points = [] } = useAllPoints();
  const { data: faults = [] } = useActiveFaults();
  const { data: definitions = [] } = useFaultDefinitions();

  return (
    <>
      <FddStatusBanner />
      <div className="mt-6">
        {sitesLoading ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-52 rounded-2xl" />
            ))}
          </div>
        ) : !sites || sites.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 text-center">
            <p className="text-lg font-medium text-foreground">
              No sites configured
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Add sites via the API or config UI to get started.
            </p>
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {sites.map((site) => (
              <SiteCard
                key={site.id}
                site={site}
                equipment={equipment.filter((e) => e.site_id === site.id)}
                points={points.filter((p) => p.site_id === site.id)}
                faults={faults.filter((f) => f.site_id === site.id)}
                definitions={definitions}
                onSelect={setSelectedSiteId}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function SiteSummaryView({ siteId }: { siteId: string }) {
  const { selectedSite } = useSiteContext();
  const { data: equipment = [] } = useEquipment(siteId);
  const { data: points = [] } = usePoints(siteId);
  const { data: faults = [] } = useSiteFaults(siteId);
  const { data: definitions = [] } = useFaultDefinitions();

  if (!selectedSite) {
    return (
      <div className="grid gap-5 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
    );
  }

  const faultCount = faults.length;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          {selectedSite.name}
        </h1>
        {selectedSite.description && (
          <p className="mt-1 text-sm text-muted-foreground">
            {selectedSite.description}
          </p>
        )}
        <div className="mt-3">
          {faultCount > 0 ? (
            <Badge variant="destructive">
              {faultCount} active fault{faultCount !== 1 ? "s" : ""}
            </Badge>
          ) : (
            <Badge variant="success">No faults</Badge>
          )}
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Equipment</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {equipment.length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Points</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {points.length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Active Faults</p>
            <p className={`mt-1 text-3xl font-semibold tabular-nums ${faultCount > 0 ? "text-destructive" : "text-success"}`}>
              {faultCount}
            </p>
          </CardContent>
        </Card>
      </div>

      {faults.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">
            Active Faults
          </h2>
          <Card>
            <CardContent className="pt-4">
              <FaultList
                faults={faults}
                definitions={definitions}
                equipment={equipment}
              />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

export function OverviewPage() {
  const { selectedSiteId } = useSiteContext();

  if (selectedSiteId) {
    return (
      <>
        <SiteSummaryView siteId={selectedSiteId} />
        <ModelContextCard />
      </>
    );
  }

  return (
    <>
      <AllSitesView />
      <ModelContextCard />
    </>
  );
}
