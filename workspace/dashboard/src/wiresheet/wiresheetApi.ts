import { apiFetch } from "../lib/api";
import type { WiresheetGraph } from "./types";

type GraphResponse = WiresheetGraph & {
  ok?: boolean;
  graph?: WiresheetGraph;
  error?: string;
};

/** GET /api/fdd-wires/graphs/{id} — unwraps `{ graph }` or legacy flat body. */
export function parseWiresheetGraphResponse(body: GraphResponse): WiresheetGraph {
  if (body.graph && typeof body.graph === "object") {
    return body.graph;
  }
  if (body.ok === false && body.error) {
    throw new Error(body.error);
  }
  return body;
}

export async function fetchWiresheetGraph(
  graphId: string,
  siteId: string,
): Promise<WiresheetGraph> {
  const qs = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
  const body = await apiFetch<GraphResponse>(
    `/api/fdd-wires/graphs/${encodeURIComponent(graphId)}${qs}`,
  );
  return parseWiresheetGraphResponse(body);
}
