import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { ApiClientError } from "../api/client";
import {
  archiveJob,
  createJob,
  deleteJob,
  duplicateJob,
  getJob,
  isJobRevisionConflict,
  listJobs,
  patchJob,
  restoreJob,
  type JobMeta,
  type JobRevisionConflictError,
} from "../api/jobsApi";
import { useSessionQuery } from "../session";
import {
  Button,
  ConfirmModal,
  DataTable,
  InlineAlert,
  Select,
  Toggle,
} from "../components/widgets";

type JobRow = {
  job_id: string;
  job_name: string;
  status: string;
  archived: string;
  updated_at: string;
};

function toTableRow(job: JobMeta): JobRow {
  return {
    job_id: job.job_id,
    job_name: job.job_name,
    status: job.status,
    archived: job.archived ? "yes" : "no",
    updated_at: job.updated_at,
  };
}

function formatApiError(err: unknown): string {
  if (err instanceof ApiClientError) {
    return `${err.code}: ${err.message} (request_id=${err.requestId})`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return String(err);
}

export function JobsPage() {
  const { query, setQuery } = useSessionQuery();
  const selectedJobId = query.jobId ?? "";

  const [includeArchived, setIncludeArchived] = useState(true);
  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [selectedJob, setSelectedJob] = useState<JobMeta | null>(null);

  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [revisionConflict, setRevisionConflict] = useState<JobRevisionConflictError | null>(
    null,
  );
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");

  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");

  const [archiveModalOpen, setArchiveModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [duplicateModalOpen, setDuplicateModalOpen] = useState(false);
  const [duplicateName, setDuplicateName] = useState("");

  const refreshList = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const rows = await listJobs({ includeArchived });
      setJobs(rows);
    } catch (err) {
      setListError(formatApiError(err));
    } finally {
      setListLoading(false);
    }
  }, [includeArchived]);

  const loadSelectedJob = useCallback(async (jobId: string) => {
    if (!jobId) {
      setSelectedJob(null);
      setEditName("");
      setEditDescription("");
      setRevisionConflict(null);
      return;
    }
    setDetailLoading(true);
    setDetailError(null);
    setRevisionConflict(null);
    try {
      const job = await getJob(jobId);
      setSelectedJob(job);
      setEditName(job.job_name);
      setEditDescription(job.description ?? "");
      setDuplicateName(`${job.job_name} (copy)`);
    } catch (err) {
      setSelectedJob(null);
      setDetailError(formatApiError(err));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    void loadSelectedJob(selectedJobId);
  }, [selectedJobId, loadSelectedJob]);

  const jobOptions = [
    { value: "", label: "— select job —" },
    ...jobs.map((j) => ({
      value: j.job_id,
      label: `${j.job_name} (${j.job_id})${j.archived ? " [archived]" : ""}`,
    })),
  ];

  async function handleCreate() {
    const name = createName.trim();
    if (!name) {
      setActionError("Job name is required.");
      return;
    }
    setActionLoading(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const job = await createJob({
        jobName: name,
        description: createDescription.trim() || undefined,
      });
      setCreateName("");
      setCreateDescription("");
      await refreshList();
      setQuery({ jobId: job.job_id }, true);
      setActionNotice(`Created job ${job.job_name}.`);
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleSavePatch() {
    if (!selectedJob) return;
    const name = editName.trim();
    if (!name) {
      setActionError("Job name is required.");
      return;
    }
    setActionLoading(true);
    setActionError(null);
    setActionNotice(null);
    setRevisionConflict(null);
    try {
      const updated = await patchJob(selectedJob.job_id, {
        jobName: name,
        description: editDescription,
        expectedMetaRevision: selectedJob.meta_revision,
      });
      setSelectedJob(updated);
      setEditName(updated.job_name);
      setEditDescription(updated.description ?? "");
      await refreshList();
      setActionNotice("Job updated.");
    } catch (err) {
      if (isJobRevisionConflict(err)) {
        setRevisionConflict(err);
      } else {
        setActionError(formatApiError(err));
      }
    } finally {
      setActionLoading(false);
    }
  }

  async function handleReloadAfterConflict() {
    if (!selectedJobId) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await loadSelectedJob(selectedJobId);
      await refreshList();
      setActionNotice("Reloaded current job revision from server.");
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleArchiveConfirm() {
    if (!selectedJob) return;
    setActionLoading(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const updated = await archiveJob(selectedJob.job_id);
      setSelectedJob(updated);
      await refreshList();
      setArchiveModalOpen(false);
      setActionNotice(`Archived ${updated.job_name}.`);
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleDeleteConfirm() {
    if (!selectedJob) return;
    const id = selectedJob.job_id;
    const name = selectedJob.job_name;
    setActionLoading(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await deleteJob(id);
      setSelectedJob(null);
      setQuery({ jobId: undefined }, true);
      await refreshList();
      setDeleteModalOpen(false);
      setActionNotice(`Permanently deleted ${name}.`);
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRestore() {
    if (!selectedJob) return;
    setActionLoading(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const updated = await restoreJob(selectedJob.job_id);
      setSelectedJob(updated);
      await refreshList();
      setActionNotice(`Restored ${updated.job_name}.`);
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleDuplicateConfirm() {
    if (!selectedJob) return;
    setActionLoading(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const copy = await duplicateJob(
        selectedJob.job_id,
        duplicateName.trim() || undefined,
      );
      await refreshList();
      setDuplicateModalOpen(false);
      setDuplicateName("");
      setQuery({ jobId: copy.job_id }, true);
      setActionNotice(`Duplicated as ${copy.job_name}.`);
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setActionLoading(false);
    }
  }

  const tableColumns = [
    { key: "job_name" as const, header: "Name" },
    { key: "job_id" as const, header: "Job ID" },
    { key: "status" as const, header: "Status" },
    { key: "archived" as const, header: "Archived" },
    { key: "updated_at" as const, header: "Updated" },
  ];

  return (
    <AppShell
      title="Jobs"
      caption="Create, select, and manage engineering jobs. Selection is URL-backed (?job=)."
    >
      <div className="page-placeholder" data-testid="jobs-page">
        <h2>Jobs</h2>
        <p>Presentation-only UI — durable job state lives in central Rust.</p>

        {actionNotice ? (
          <InlineAlert
            id="jobs-notice"
            variant="success"
            title="Success"
            onDismiss={() => setActionNotice(null)}
            testId="jobs-notice"
          >
            {actionNotice}
          </InlineAlert>
        ) : null}

        {listError ? (
          <InlineAlert id="jobs-list-error" variant="danger" testId="jobs-list-error">
            {listError}
          </InlineAlert>
        ) : null}

        {actionError ? (
          <InlineAlert
            id="jobs-action-error"
            variant="danger"
            onDismiss={() => setActionError(null)}
            testId="jobs-action-error"
          >
            {actionError}
          </InlineAlert>
        ) : null}

        {revisionConflict ? (
          <InlineAlert id="jobs-revision-conflict" variant="warning" testId="jobs-revision-conflict">
            Revision conflict: expected{" "}
            <code>{revisionConflict.expectedRevision}</code>, server has{" "}
            <code>{revisionConflict.currentRevision}</code>. Reload the current revision before
            saving again.
            <div style={{ marginTop: "0.75rem" }}>
              <Button
                id="jobs-reload-revision"
                label="Reload current revision"
                variant="secondary"
                loading={actionLoading}
                onClick={() => void handleReloadAfterConflict()}
                testId="jobs-reload-revision"
              />
            </div>
          </InlineAlert>
        ) : null}

        <Toggle
          id="jobs-include-archived"
          label="Include archived jobs"
          checked={includeArchived}
          onChange={setIncludeArchived}
          testId="jobs-include-archived"
        />

        <section className="jobs-section" data-testid="jobs-create-section">
          <h3>Create job</h3>
          <div className="widget widget--compact">
            <label className="widget__label" htmlFor="jobs-create-name">
              Name
            </label>
            <input
              id="jobs-create-name"
              className="widget__input"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              data-testid="jobs-create-name"
            />
          </div>
          <div className="widget widget--compact">
            <label className="widget__label" htmlFor="jobs-create-description">
              Description (optional)
            </label>
            <textarea
              id="jobs-create-description"
              className="widget__input"
              rows={2}
              value={createDescription}
              onChange={(e) => setCreateDescription(e.target.value)}
              data-testid="jobs-create-description"
            />
          </div>
          <Button
            id="jobs-create"
            label="Create job"
            loading={actionLoading}
            onClick={() => void handleCreate()}
            testId="jobs-create"
          />
        </section>

        <DataTable
          id="jobs-list"
          label="Job list"
          description="All jobs for this workspace"
          columns={tableColumns}
          rows={jobs.map(toTableRow)}
          loading={listLoading}
          testId="jobs-list-table"
        />

        <Select
          id="jobs-session-select"
          label="Selected job"
          description="Maps job id → URL ?job="
          value={selectedJobId}
          options={jobOptions}
          onChange={(value) => setQuery({ jobId: value }, true)}
          loading={listLoading}
          testId="jobs-session-select"
        />

        {selectedJobId ? (
          <section className="jobs-section" data-testid="jobs-detail-section">
            <h3>Job details</h3>
            {detailLoading ? <p className="loading">Loading job…</p> : null}
            {detailError ? (
              <InlineAlert id="jobs-detail-error" variant="danger" testId="jobs-detail-error">
                {detailError}
              </InlineAlert>
            ) : null}
            {selectedJob ? (
              <>
                <p data-testid="jobs-meta-revision">
                  <strong>meta_revision:</strong>{" "}
                  <code>{selectedJob.meta_revision}</code>
                </p>
                <p data-testid="jobs-selected-id">
                  Job ID: <code>{selectedJob.job_id}</code>
                </p>
                <p>
                  Status: <span data-testid="jobs-status">{selectedJob.status}</span>
                  {selectedJob.archived ? " (archived)" : null}
                </p>
                <div className="widget widget--compact">
                  <label className="widget__label" htmlFor="jobs-edit-name">
                    Name
                  </label>
                  <input
                    id="jobs-edit-name"
                    className="widget__input"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    data-testid="jobs-edit-name"
                  />
                </div>
                <div className="widget widget--compact">
                  <label className="widget__label" htmlFor="jobs-edit-description">
                    Description
                  </label>
                  <textarea
                    id="jobs-edit-description"
                    className="widget__input"
                    rows={3}
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    data-testid="jobs-edit-description"
                  />
                </div>
                <div className="widget widget--compact">
                  <label className="widget__label" htmlFor="jobs-duplicate-name">
                    Duplicate as (optional)
                  </label>
                  <input
                    id="jobs-duplicate-name"
                    className="widget__input"
                    value={duplicateName}
                    onChange={(e) => setDuplicateName(e.target.value)}
                    placeholder={`${selectedJob.job_name} (copy)`}
                    data-testid="jobs-duplicate-name"
                  />
                </div>
                <div className="jobs-actions">
                  <Button
                    id="jobs-save"
                    label="Save changes"
                    loading={actionLoading}
                    onClick={() => void handleSavePatch()}
                    testId="jobs-save"
                  />
                  {selectedJob.archived ? (
                    <Button
                      id="jobs-restore"
                      label="Restore"
                      variant="secondary"
                      loading={actionLoading}
                      onClick={() => void handleRestore()}
                      testId="jobs-restore"
                    />
                  ) : (
                    <Button
                      id="jobs-archive"
                      label="Archive"
                      variant="danger"
                      loading={actionLoading}
                      onClick={() => setArchiveModalOpen(true)}
                      testId="jobs-archive"
                    />
                  )}
                  <Button
                    id="jobs-duplicate"
                    label="Duplicate"
                    variant="secondary"
                    loading={actionLoading}
                    onClick={() => {
                      if (!duplicateName.trim()) {
                        setDuplicateName(`${selectedJob.job_name} (copy)`);
                      }
                      setDuplicateModalOpen(true);
                    }}
                    testId="jobs-duplicate"
                  />
                  <Button
                    id="jobs-delete"
                    label="Delete"
                    variant="danger"
                    loading={actionLoading}
                    onClick={() => setDeleteModalOpen(true)}
                    testId="jobs-delete"
                  />
                </div>
              </>
            ) : null}
          </section>
        ) : null}

        <ConfirmModal
          id="jobs-archive-modal"
          open={archiveModalOpen}
          title="Archive job"
          message={
            selectedJob
              ? `Archive "${selectedJob.job_name}"? You can restore it later.`
              : "Archive this job?"
          }
          confirmLabel="Archive"
          loading={actionLoading}
          onConfirm={() => void handleArchiveConfirm()}
          onCancel={() => setArchiveModalOpen(false)}
          testId="jobs-archive-modal"
        />

        <ConfirmModal
          id="jobs-delete-modal"
          open={deleteModalOpen}
          title="Delete job permanently"
          message={
            selectedJob
              ? `Permanently delete "${selectedJob.job_name}" and its workspace files? This cannot be undone. Prefer Archive if you may need it later.`
              : "Permanently delete this job?"
          }
          confirmLabel="Delete permanently"
          loading={actionLoading}
          onConfirm={() => void handleDeleteConfirm()}
          onCancel={() => setDeleteModalOpen(false)}
          testId="jobs-delete-modal"
        />

        <ConfirmModal
          id="jobs-duplicate-modal"
          open={duplicateModalOpen}
          title="Duplicate job"
          message={
            duplicateName.trim()
              ? `Create a copy named "${duplicateName.trim()}"?`
              : "Create a copy of this job workspace?"
          }
          confirmLabel="Duplicate"
          loading={actionLoading}
          onConfirm={() => void handleDuplicateConfirm()}
          onCancel={() => setDuplicateModalOpen(false)}
          testId="jobs-duplicate-modal"
        />
      </div>
    </AppShell>
  );
}
