# Plan: Default Rules, Fix Phantom Definitions, Rules CRUD + Frontend (Hot Reload)

## Goals

1. **Fix phantom "AHU Short Cycling"** — Definitions table and Faults matrix show only what exists in `rules_dir`; remove stale rows when a rule file is gone.
2. **Default rules** — Ship with only `sensor_bounds.yaml` and `sensor_flatline.yaml` in `analyst/rules`; no extra files that create phantom definitions.
3. **Rules CRUD + frontend** — Users can upload, download, and delete rule YAML files via the UI; changes hot-reload (next FDD run picks them up).

---

## 1. Fix phantom definitions (backend)

**Problem:** `fault_definitions` is upserted from YAML on each FDD run but never pruned. If a rule file is removed (or never existed on this server), its row remains and the UI shows e.g. "AHU Short Cycling".

**Change:** In `open_fdd/platform/loop.py`, extend `_sync_fault_definitions_from_rules(rules)` so that after upserting from the current rule list it **prunes** definitions that no longer have a corresponding rule:

- Collect `fault_id` for every rule in `rules` (same logic: `r.get("flag") or f"{r.get('name', 'rule')}_flag"`).
- After the upsert loop, run:  
  `DELETE FROM fault_definitions WHERE fault_id != ALL(%s)` (or equivalent) with the list of current fault_ids.
- No FK from `fault_results` / `fault_state` to `fault_definitions` (they store `fault_id` as text), so deleting definitions is safe; historical results keep their fault_id for display/analytics.

**Result:** Definitions list and Faults matrix only show faults that have a YAML file in `rules_dir`. One-time fix for existing DBs: next FDD run will prune "AHU Short Cycling" (and any other orphan).

---

## 2. Default rules (no code change)

- **Repo:** `analyst/rules` already contains only `sensor_bounds.yaml` and `sensor_flatline.yaml`. Keep it that way; do not add an AHU Short Cycling YAML unless you want that rule.
- **Server:** If the Linux server has extra files in `analyst/rules` that you don’t want, remove them; after the prune logic above and one FDD run, definitions will match the remaining files.
- **New deployments:** Same two files as defaults; anything else is added by users via the new CRUD (or manually).

---

## 3. Backend: Rules CRUD (upload / delete)

**Existing:**

- `GET /rules` — list `.yaml` filenames and `rules_dir` (from config).
- `GET /rules/{filename}` — return file content (plain text). Use for **download**.
- `POST /rules/test-inject`, `DELETE /rules/test-inject/{filename}` — test-only (gated by `OFDD_ALLOW_TEST_RULES`); keep for automation.

**Add (production, no env gate):**

| Method | Endpoint | Purpose |
|--------|----------|--------|
| POST   | `/rules` or `/rules/upload` | Upload a new or replace an existing rule file. |
| DELETE | `/rules/{filename}`         | Delete a rule file from `rules_dir`.         |

**Upload (POST):**

- **Body:** Either `multipart/form-data` (file) or JSON `{ "filename": "my_rule.yaml", "content": "..." }`. JSON is easier for “copy/paste YAML” in the UI and matches test-inject.
- **Validation:**
  - `filename`: must end in `.yaml`, no `..`, `/`, `\`.
  - Resolve path under `_rules_dir_resolved()`; ensure path stays inside `rules_dir` (path traversal check).
  - Optional but recommended: parse YAML and check for minimal keys (`name` or `flag`) so invalid rules are rejected.
- **Write:** `path.write_text(content)` (same as test-inject). Create `rules_dir` if missing (optional; currently API returns 503 if not a dir).
- **Response:** 200 + `{ "filename": "...", "path": "..." }` or 201 for create.
- **Auth:** Same as rest of API (Bearer when `OFDD_API_KEY` set).

**Delete (DELETE):**

- **Path:** `DELETE /rules/{filename}` (filename in path; same safety as GET: `.yaml` only, no path traversal).
- **Behavior:** `path.unlink()`. Return 404 if file doesn’t exist.
- **Optional:** After delete, call a small “sync definitions from rules_dir” helper that runs `load_rules_from_dir` + `_sync_fault_definitions_from_rules` so the definitions table (and matrix) update immediately instead of waiting for the next FDD run. If you skip this, the next FDD run will prune the definition anyway.

**Optional helper:** Expose `POST /rules/sync-definitions` that loads all YAML from `rules_dir` and runs `_sync_fault_definitions_from_rules` (no FDD run). Then upload/delete can call it so the UI updates without waiting for the next run. Low priority if FDD runs every few hours.

---

## 4. Frontend: Upload, Download, Delete

**Current (Faults page – FDD rule files section):**

- Lists filenames from `GET /rules`.
- Click filename → fetch `GET /rules/{filename}` and show content in a `<pre>`.
- Shows `rules_dir` from the list response.

**Add:**

1. **Download**
   - Per file: “Download” link that opens `GET /rules/{filename}` (e.g. in a new tab or via `fetch` + blob download). Already supported by existing endpoint.

2. **Upload**
   - “Upload rule” (or “Add rule file”):
     - Option A: File input → read file as text → POST JSON `{ filename: file.name, content }` (normalize filename to `.yaml` if needed).
     - Option B: Textarea “Paste YAML” + filename input → POST same JSON.
   - On success: invalidate `GET /rules` (and definitions query if you add sync), show success toast; optionally refetch rules list and select the new file.

3. **Delete**
   - Per file: “Delete” button (with confirmation: “Remove rule file X? Definition will be removed after next FDD run.”).
   - Call `DELETE /rules/{filename}`; on success invalidate list and definitions, clear selection if the deleted file was selected.

4. **Copy from existing**
   - Optional: “Duplicate” that copies current file content into the upload form with a new name (e.g. `sensor_bounds_copy.yaml`) so users can duplicate and edit.

**UX:** Keep the existing “view content” flow; add Upload above the list and Download/Delete next to each filename. Use existing auth (e.g. `apiFetch` with API key).

---

## 5. Hot reload (no change)

- FDD loop already loads rules from `rules_dir` on **every** run (`load_rules_from_dir(rules_path)` in `run_fdd_loop`). No caching.
- So: user uploads a new YAML → file is on disk in `rules_dir` → next FDD run loads it and runs it; new rule appears in definitions (after sync) and in results. Same for delete: file gone → next run doesn’t load it → prune step removes the definition.
- Optional `POST /rules/sync-definitions` only makes the definitions table (and matrix) update immediately; it doesn’t change hot-reload behavior of the FDD engine.

---

## 6. Implementation order

| Step | Task | Effort |
|------|------|--------|
| 1 | Backend: Prune stale definitions in `_sync_fault_definitions_from_rules` | Small |
| 2 | Backend: `POST /rules` (upload) with filename + content, validation | Small |
| 3 | Backend: `DELETE /rules/{filename}` | Small |
| 4 | Optional: `POST /rules/sync-definitions` and call after upload/delete | Small |
| 5 | Frontend: Download link per file | Small |
| 6 | Frontend: Upload form (file or paste + filename), call POST /rules | Medium |
| 7 | Frontend: Delete button + confirm, call DELETE /rules/{filename} | Small |
| 8 | Tests: API tests for upload/delete; e2e or manual for UI | Small |

**Total:** Backend ~half day; frontend ~half day; testing ~half day. Optional sync-definitions adds a bit more.

---

## 7. Security / validation

- **Path traversal:** Reject `..`, `/`, `\` in filename; resolve path and ensure `path.relative_to(base)` (already done in test-inject).
- **Overwrite:** Upload can overwrite existing files (same as test-inject). Optional: return 409 if file exists and require explicit overwrite flag.
- **YAML validation:** At least parse YAML; optionally require `name` or `flag` and reject if missing so broken rules don’t get into the matrix until the next run fails.

---

## 8. Summary

- **Fix:** Prune `fault_definitions` in sync so only current rule files have rows → phantom “AHU Short Cycling” goes away after one FDD run.
- **Defaults:** Keep `analyst/rules` with only `sensor_bounds.yaml` and `sensor_flatline.yaml`.
- **CRUD:** Add POST (upload) and DELETE for rule files; reuse GET for download; list already exists.
- **Frontend:** Add upload (file or paste), download link, delete with confirm; reuse existing list + view.
- **Hot reload:** Already works; no change. Optional sync-definitions endpoint improves UX by updating definitions immediately after upload/delete.
