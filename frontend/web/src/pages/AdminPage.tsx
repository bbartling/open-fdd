import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { Button, ConfirmModal, InlineAlert } from "../components/widgets";
import { getAuthMe, type AuthMe } from "../api/authApi";
import {
  deleteAdminTenant,
  deleteAdminUser,
  listAdminTenants,
  listAdminUsers,
  setAdminUserDisabled,
  upsertAdminTenant,
  upsertAdminUser,
  type AdminTenant,
  type AdminUser,
} from "../api/adminApi";

/**
 * Hub-admin control plane (Wave O8). Quiet tables — no agent tip chrome.
 * Visible only when /api/auth/me reports hub_admin.
 */
export function AdminPage() {
  const [me, setMe] = useState<AuthMe | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [uName, setUName] = useState("");
  const [uRole, setURole] = useState("operator");
  const [uTenants, setUTenants] = useState("");
  const [uPass, setUPass] = useState("");
  const [uPassEnv, setUPassEnv] = useState("");

  const [tId, setTId] = useState("");
  const [tName, setTName] = useState("");
  const [tBuildings, setTBuildings] = useState("");

  const [deleteUser, setDeleteUser] = useState<string | null>(null);
  const [deleteTenant, setDeleteTenant] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const profile = await getAuthMe();
      setMe(profile);
      if (!profile.hub_admin) {
        setUsers([]);
        setTenants([]);
        return;
      }
      const [u, t] = await Promise.all([listAdminUsers(), listAdminTenants()]);
      setUsers(u);
      setTenants(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onSaveUser = async () => {
    setError(null);
    setBusy(true);
    try {
      const tenant_ids = uTenants
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await upsertAdminUser({
        username: uName.trim(),
        role: uRole,
        tenant_ids,
        password: uPass.trim() || undefined,
        password_env: uPassEnv.trim() || undefined,
        disabled: false,
      });
      setUName("");
      setUPass("");
      setUPassEnv("");
      setUTenants("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onSaveTenant = async () => {
    setError(null);
    setBusy(true);
    try {
      const building_ids = tBuildings
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await upsertAdminTenant({
        id: tId.trim(),
        name: tName.trim() || tId.trim(),
        building_ids,
      });
      setTId("");
      setTName("");
      setTBuildings("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!loading && me && !me.hub_admin) {
    return (
      <AppShell title="Admin" activeSectionId="admin">
        <InlineAlert id="admin-denied" variant="warning" testId="admin-denied">
          Hub admin only.
        </InlineAlert>
      </AppShell>
    );
  }

  return (
    <AppShell title="Admin" activeSectionId="admin">
      {error ? (
        <InlineAlert id="admin-error" variant="danger" testId="admin-error">
          {error}
        </InlineAlert>
      ) : null}
      {loading ? <p>Loading…</p> : null}

      <section style={{ marginTop: "1.5rem" }}>
        <h2>Users</h2>
        <table className="data-table" data-testid="admin-users-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Tenants</th>
              <th>Password</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.username}>
                <td>{u.username}</td>
                <td>{u.role}</td>
                <td>{u.tenant_ids.join(", ")}</td>
                <td>
                  {u.password_env
                    ? `env:${u.password_env}`
                    : u.has_inline_password
                      ? "set"
                      : "—"}
                </td>
                <td>{u.disabled ? "disabled" : "active"}</td>
                <td>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                    <Button
                      id={`admin-user-toggle-${u.username}`}
                      label={u.disabled ? "Enable" : "Disable"}
                      variant="secondary"
                      density="compact"
                      disabled={busy}
                      onClick={() => {
                        setBusy(true);
                        void setAdminUserDisabled(u.username, !u.disabled)
                          .then(refresh)
                          .catch((e) => setError(String(e)))
                          .finally(() => setBusy(false));
                      }}
                      testId={`admin-user-toggle-${u.username}`}
                    />
                    <Button
                      id={`admin-user-delete-${u.username}`}
                      label="Delete"
                      variant="danger"
                      density="compact"
                      disabled={busy}
                      onClick={() => setDeleteUser(u.username)}
                      testId={`admin-user-delete-${u.username}`}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ display: "grid", gap: "0.5rem", maxWidth: 480, marginTop: "1rem" }}>
          <input
            placeholder="username"
            value={uName}
            onChange={(e) => setUName(e.target.value)}
            data-testid="admin-user-username"
          />
          <select value={uRole} onChange={(e) => setURole(e.target.value)}>
            <option value="operator">operator</option>
            <option value="viewer">viewer</option>
          </select>
          <input
            placeholder="tenant ids (comma-separated)"
            value={uTenants}
            onChange={(e) => setUTenants(e.target.value)}
            data-testid="admin-user-tenants"
          />
          <input
            placeholder="password (lab) or leave blank"
            type="password"
            value={uPass}
            onChange={(e) => setUPass(e.target.value)}
          />
          <input
            placeholder="password_env (Railway secret name)"
            value={uPassEnv}
            onChange={(e) => setUPassEnv(e.target.value)}
          />
          <Button
            id="admin-user-save"
            label="Save user"
            disabled={busy || !uName.trim()}
            onClick={() => void onSaveUser()}
            testId="admin-user-save"
          />
        </div>
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Tenants</h2>
        <table className="data-table" data-testid="admin-tenants-table">
          <thead>
            <tr>
              <th>Id</th>
              <th>Name</th>
              <th>Buildings</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tenants.map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.name}</td>
                <td>{(t.building_ids ?? []).join(", ")}</td>
                <td>
                  <Button
                    id={`admin-tenant-delete-${t.id}`}
                    label="Delete"
                    variant="danger"
                    density="compact"
                    disabled={busy}
                    onClick={() => setDeleteTenant(t.id)}
                    testId={`admin-tenant-delete-${t.id}`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ display: "grid", gap: "0.5rem", maxWidth: 480, marginTop: "1rem" }}>
          <input
            placeholder="tenant id"
            value={tId}
            onChange={(e) => setTId(e.target.value)}
            data-testid="admin-tenant-id"
          />
          <input
            placeholder="display name"
            value={tName}
            onChange={(e) => setTName(e.target.value)}
          />
          <input
            placeholder="building ids (comma-separated)"
            value={tBuildings}
            onChange={(e) => setTBuildings(e.target.value)}
            data-testid="admin-tenant-buildings"
          />
          <Button
            id="admin-tenant-save"
            label="Save tenant"
            disabled={busy || !tId.trim()}
            onClick={() => void onSaveTenant()}
            testId="admin-tenant-save"
          />
        </div>
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Site data</h2>
        <p>
          Purge package/historian sites from <a href="/sites">Sites</a>.
        </p>
      </section>

      <ConfirmModal
        id="admin-delete-user"
        open={deleteUser != null}
        title="Delete user"
        message={deleteUser ? `Remove ${deleteUser}?` : ""}
        confirmLabel="Delete"
        onCancel={() => setDeleteUser(null)}
        onConfirm={() => {
          const name = deleteUser;
          setDeleteUser(null);
          if (!name) return;
          setBusy(true);
          void deleteAdminUser(name)
            .then(refresh)
            .catch((e) => setError(String(e)))
            .finally(() => setBusy(false));
        }}
        testId="admin-delete-user-modal"
      />

      <ConfirmModal
        id="admin-delete-tenant"
        open={deleteTenant != null}
        title="Delete tenant"
        message={deleteTenant ? `Remove tenant ${deleteTenant}?` : ""}
        confirmLabel="Delete"
        onCancel={() => setDeleteTenant(null)}
        onConfirm={() => {
          const id = deleteTenant;
          setDeleteTenant(null);
          if (!id) return;
          setBusy(true);
          void deleteAdminTenant(id)
            .then(refresh)
            .catch((e) => setError(String(e)))
            .finally(() => setBusy(false));
        }}
        testId="admin-delete-tenant-modal"
      />
    </AppShell>
  );
}
