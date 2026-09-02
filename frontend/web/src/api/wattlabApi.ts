import {
  createExport,
  downloadExport,
  type EngineeringExport,
  type ExportProfile,
} from "./exportApi";

/** @deprecated Use EngineeringExport */
export type WattlabDump = EngineeringExport & { dump_id?: string };
export type WattlabDumpProfile = ExportProfile;

function exportPath(jobId: string, suffix = ""): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/exports${suffix}`;
}

export async function createDump(
  jobId: string,
  buildingId: string,
  profile: WattlabDumpProfile = "summary",
): Promise<WattlabDump> {
  const exp = await createExport(jobId, buildingId, profile);
  return { ...exp, dump_id: exp.export_id };
}

export async function downloadDump(
  jobId: string,
  dumpId: string,
  filename: string,
): Promise<void> {
  const exportId = dumpId.startsWith("dump-")
    ? dumpId.replace("dump-", "export-")
    : dumpId;
  return downloadExport(jobId, exportId, filename);
}

// Re-export for callers migrating to export API.
export { createExport, downloadExport, exportPath };
export type { EngineeringExport, ExportProfile };
