import { useCallback, useEffect, useState } from "react";
import {
  getHistorianPoints,
  purgeHistorian,
  type HistorianPoint,
  type PurgeTarget,
} from "../api/historianApi";
import { useDatasetWriteAllowed } from "../hooks/useDatasetWriteAllowed";
import { DeviceTree } from "./DeviceTree";
import { Button, ConfirmModal, InlineAlert } from "./widgets";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function targetLabel(target: PurgeTarget): string {
  return target.kind === "equipment"
    ? `equipment ${target.equipmentId}`
    : `series ${target.openfddKey}`;
}

/**
 * Read-only device tree for one site plus the only write here: purge the
 * historian samples and `point_map` rows of one equipment or one series.
 * The building model is never edited from this page.
 */
export function HistorianDataSection({ siteId }: { siteId: string }) {
  const writeAllowed = useDatasetWriteAllowed();
  const [points, setPoints] = useState<HistorianPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<PurgeTarget | null>(null);
  const [purging, setPurging] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const res = await getHistorianPoints(siteId, signal);
        if (!signal?.aborted) {
          setPoints(res.points ?? []);
          setError(null);
        }
      } catch (err) {
        if (!signal?.aborted) {
          setPoints(null);
          setError(formatErr(err));
        }
      }
    },
    [siteId],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  async function onConfirm() {
    if (!pending) return;
    setPurging(true);
    setError(null);
    setNotice(null);
    try {
      const out = await purgeHistorian(siteId, pending);
      const report = out.purge;
      setNotice(
        `Purged ${targetLabel(pending)}: ${report?.samples_deleted ?? 0} samples and ` +
          `${report?.point_map_deleted ?? 0} series removed. The building model is unchanged.`,
      );
      setPending(null);
      await load();
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setPurging(false);
    }
  }

  return (
    <section className="jobs-section" data-testid="jobs-historian-section">
      <h3>Historian data · {siteId}</h3>
      <p>
        Read-only device tree. The building model comes from the portal inventory or the CSV
        package; AI agents change it through REST or openfdd-mcp. Series marked orphaned are no
        longer in the model and keep their samples until purged.
      </p>
      {notice ? (
        <InlineAlert
          id="jobs-purge-notice"
          variant="success"
          onDismiss={() => setNotice(null)}
          testId="jobs-purge-notice"
        >
          {notice}
        </InlineAlert>
      ) : null}
      {error ? (
        <InlineAlert id="jobs-purge-error" variant="danger" testId="jobs-purge-error">
          {error}
        </InlineAlert>
      ) : null}
      {points ? (
        <DeviceTree
          points={points}
          testId="jobs-tree"
          equipmentActions={
            writeAllowed
              ? (eq) =>
                  eq.equipmentId ? (
                    <Button
                      id={`jobs-purge-equipment-${eq.equipmentId}`}
                      label="Purge historian data"
                      variant="danger"
                      density="compact"
                      onClick={() =>
                        setPending({ kind: "equipment", equipmentId: eq.equipmentId })
                      }
                      testId={`jobs-purge-equipment-${eq.equipmentId}`}
                    />
                  ) : null
              : undefined
          }
          pointActions={
            writeAllowed
              ? (point) => (
                  <Button
                    id={`jobs-purge-point-${point.openfdd_key}`}
                    label="Purge historian data"
                    variant="danger"
                    density="compact"
                    onClick={() => setPending({ kind: "point", openfddKey: point.openfdd_key })}
                    testId={`jobs-purge-point-${point.openfdd_key}`}
                  />
                )
              : undefined
          }
        />
      ) : null}
      <ConfirmModal
        id="jobs-purge-modal"
        open={pending != null}
        title="Purge historian data"
        message={
          pending
            ? `Delete every historian sample and series row for ${targetLabel(pending)} at ${siteId}? ` +
              "The building model is not changed. This cannot be undone."
            : ""
        }
        confirmLabel="Purge"
        loading={purging}
        onConfirm={() => void onConfirm()}
        onCancel={() => setPending(null)}
        testId="jobs-purge-modal"
      />
    </section>
  );
}
