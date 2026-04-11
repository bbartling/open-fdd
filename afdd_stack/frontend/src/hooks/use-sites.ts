import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Site, Equipment, Point } from "@/types/api";

export function useSites() {
  return useQuery<Site[]>({
    queryKey: ["sites"],
    queryFn: () => apiFetch<Site[]>("/sites"),
  });
}

export function useSite(siteId: string | undefined) {
  return useQuery<Site>({
    queryKey: ["sites", siteId],
    queryFn: () => apiFetch<Site>(`/sites/${siteId}`),
    enabled: !!siteId,
  });
}

export function useEquipment(siteId: string | undefined) {
  return useQuery<Equipment[]>({
    queryKey: ["equipment", siteId],
    queryFn: () => apiFetch<Equipment[]>(`/equipment?site_id=${siteId}`),
    enabled: !!siteId,
  });
}

export function useAllEquipment() {
  return useQuery<Equipment[]>({
    queryKey: ["equipment"],
    queryFn: () => apiFetch<Equipment[]>("/equipment"),
  });
}

export function usePoints(siteId: string | undefined) {
  return useQuery<Point[]>({
    queryKey: ["points", siteId],
    queryFn: () => apiFetch<Point[]>(`/points?site_id=${siteId}`),
    enabled: !!siteId,
  });
}

export function useAllPoints() {
  return useQuery<Point[]>({
    queryKey: ["points"],
    queryFn: () => apiFetch<Point[]>("/points"),
  });
}
