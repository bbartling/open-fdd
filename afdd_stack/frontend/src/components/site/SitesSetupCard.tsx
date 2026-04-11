"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { createSite, deleteSite, type SiteCreate } from "@/lib/crud-api";
import { useSites } from "@/hooks/use-sites";

type SitesSetupCardProps = {
  /** Shown in the card title next to "Sites" (e.g. Step 1). */
  stepLabel?: string;
  className?: string;
};

export function SitesSetupCard({ stepLabel = "Step 1", className }: SitesSetupCardProps) {
  const queryClient = useQueryClient();
  const { data: sites = [] } = useSites();
  const [newSiteName, setNewSiteName] = useState("");
  const [newSiteDescription, setNewSiteDescription] = useState("");

  const createSiteMutation = useMutation({
    mutationFn: (body: SiteCreate) => createSite(body),
    onSuccess: () => {
      setNewSiteName("");
      setNewSiteDescription("");
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });

  const deleteSiteMutation = useMutation({
    mutationFn: (siteId: string) => deleteSite(siteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["faults"] });
    },
  });

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
          <Building2 className="h-5 w-5 shrink-0" />
          <span className="text-base font-medium text-muted-foreground">{stepLabel}</span>
          Sites
        </CardTitle>
        <p className="text-sm font-normal text-muted-foreground">
          Create a site if you don’t have one. Assign points to it when you import from the data model page.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Name</label>
            <input
              type="text"
              value={newSiteName}
              onChange={(e) => setNewSiteName(e.target.value)}
              placeholder="Site name"
              className="h-9 w-48 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              data-testid="new-site-name-input"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Description (optional)</label>
            <input
              type="text"
              value={newSiteDescription}
              onChange={(e) => setNewSiteDescription(e.target.value)}
              placeholder="Optional"
              className="h-9 w-48 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <button
            type="button"
            onClick={() => {
              if (!newSiteName.trim()) return;
              createSiteMutation.mutate({ name: newSiteName.trim(), description: newSiteDescription.trim() || null });
            }}
            disabled={createSiteMutation.isPending || !newSiteName.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            data-testid="add-site-button"
          >
            <Plus className="h-4 w-4" />
            Add site
          </button>
        </div>
        {createSiteMutation.isError && (
          <p className="text-sm text-destructive">{createSiteMutation.error?.message}</p>
        )}
        <div className="overflow-x-auto rounded-lg border border-border/60">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="w-[100px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sites.map((site) => (
                <TableRow key={site.id} data-site-id={site.id}>
                  <TableCell className="font-medium">{site.name}</TableCell>
                  <TableCell className="text-muted-foreground">{site.description ?? "—"}</TableCell>
                  <TableCell>
                    <button
                      type="button"
                      onClick={() => {
                        if (
                          window.confirm(
                            `Delete site "${site.name}"? This removes all equipment, points, timeseries, and faults for this site.`,
                          )
                        ) {
                          deleteSiteMutation.mutate(site.id);
                        }
                      }}
                      disabled={deleteSiteMutation.isPending}
                      className="inline-flex items-center gap-1 rounded border border-border/60 px-2 py-1 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
                    >
                      <Trash2 className="h-3 w-3" />
                      Delete
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {sites.length === 0 && (
          <p className="text-sm text-muted-foreground" data-testid="sites-empty-hint">
            No sites. Add one above before <strong>Add to data model</strong> so new points can be assigned a site.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
