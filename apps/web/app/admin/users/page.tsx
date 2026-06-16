"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AdminUserResponse,
  ApiError,
  CreateUserRequest,
  createUser,
  deactivateUser,
  getMe,
  listUsers,
  updateUserRoles,
} from "@/lib/api";

const ALL_ROLES = [
  "chat_user",
  "faq_manager",
  "user_admin",
  "feedback_reviewer",
  "knowledge_admin",
  "system_admin",
];

const ROLE_LABELS: Record<string, string> = {
  chat_user: "משתמש צ׳אט",
  faq_manager: "מנהל FAQ",
  user_admin: "מנהל משתמשים",
  feedback_reviewer: "סוקר משוב",
  knowledge_admin: "מנהל ידע",
  system_admin: "מנהל מערכת",
};

export default function UsersAdminPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [users, setUsers] = useState<AdminUserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editRoles, setEditRoles] = useState<string[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newUser, setNewUser] = useState<CreateUserRequest>({ email: "", password: "", display_name: "", roles: ["chat_user"] });
  const [saving, setSaving] = useState(false);

  function handleAuthError() {
    localStorage.removeItem("chathr_token");
    router.push("/login");
  }

  async function load(t: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await listUsers(t);
      setUsers(data);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("לא ניתן לטעון משתמשים.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = localStorage.getItem("chathr_token");
    if (!t) { router.push("/login"); return; }
    setToken(t);
    getMe(t).catch(() => handleAuthError());
    load(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSaveRoles() {
    if (!token || !editingId) return;
    setSaving(true);
    setError(null);
    try {
      await updateUserRoles(token, editingId, editRoles);
      setEditingId(null);
      await load(token);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("שגיאה בשמירת תפקידים.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeactivate(userId: string, email: string) {
    if (!token) return;
    if (!confirm(`לנטרל את המשתמש ${email}?`)) return;
    try {
      await deactivateUser(token, userId);
      await load(token);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("שגיאה בניטרול משתמש.");
    }
  }

  async function handleCreateUser() {
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      await createUser(token, newUser);
      setShowCreate(false);
      setNewUser({ email: "", password: "", display_name: "", roles: ["chat_user"] });
      await load(token);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("שגיאה ביצירת משתמש.");
    } finally {
      setSaving(false);
    }
  }

  function toggleNewRole(role: string) {
    setNewUser((u) => ({
      ...u,
      roles: u.roles?.includes(role)
        ? u.roles.filter((r) => r !== role)
        : [...(u.roles || []), role],
    }));
  }

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.6rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>ניהול משתמשים</span>
        <button onClick={() => router.push("/chat")} style={navBtn}>צ׳אט</button>
      </header>

      <div style={{ padding: "1rem 1.5rem", flex: 1, overflow: "auto" }}>
        {error && (
          <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "0.6rem 1rem", color: "#b91c1c", marginBottom: "1rem" }}>
            {error}
          </div>
        )}

        <div style={{ marginBottom: "1rem" }}>
          <button
            onClick={() => setShowCreate((v) => !v)}
            style={{ padding: "0.35rem 1rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer", fontWeight: "bold" }}
          >
            {showCreate ? "ביטול" : "+ משתמש חדש"}
          </button>
        </div>

        {showCreate && (
          <div style={{ background: "#f8fafc", border: "1px solid #dde3ed", borderRadius: "8px", padding: "1rem", marginBottom: "1.5rem" }}>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>משתמש חדש</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <input placeholder="אימייל *" value={newUser.email}
                onChange={(e) => setNewUser((u) => ({ ...u, email: e.target.value }))}
                style={{ padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc" }} />
              <input placeholder="שם תצוגה" value={newUser.display_name || ""}
                onChange={(e) => setNewUser((u) => ({ ...u, display_name: e.target.value }))}
                style={{ padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc" }} />
              <input placeholder="סיסמה *" type="password" value={newUser.password}
                onChange={(e) => setNewUser((u) => ({ ...u, password: e.target.value }))}
                style={{ padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc" }} />
              <div>
                <label style={{ fontSize: "0.85rem", fontWeight: "bold" }}>תפקידים:</label>
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.3rem" }}>
                  {ALL_ROLES.map((role) => (
                    <label key={role} style={{ display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "0.85rem", cursor: "pointer" }}>
                      <input type="checkbox" checked={newUser.roles?.includes(role)}
                        onChange={() => toggleNewRole(role)} />
                      {ROLE_LABELS[role] || role}
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", justifyContent: "flex-end" }}>
              <button onClick={() => setShowCreate(false)} style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", background: "#fff", cursor: "pointer" }}>
                ביטול
              </button>
              <button onClick={handleCreateUser} disabled={saving || !newUser.email.trim() || !newUser.password.trim()}
                style={{ padding: "0.3rem 1rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer", fontWeight: "bold" }}>
                {saving ? "יוצר..." : "צור משתמש"}
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div style={{ color: "#6b7280" }}>טוען...</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
            <thead>
              <tr style={{ background: "#f0f4f8", borderBottom: "2px solid #dde3ed" }}>
                <th style={th}>אימייל</th>
                <th style={th}>שם</th>
                <th style={th}>תפקידים</th>
                <th style={th}>סטטוס</th>
                <th style={th}>פעולות</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} style={{ borderBottom: "1px solid #eef0f3" }}>
                  <td style={td}>{user.email}</td>
                  <td style={td}>{user.display_name || "—"}</td>
                  <td style={td}>
                    {editingId === user.id ? (
                      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                        {ALL_ROLES.map((role) => (
                          <label key={role} style={{ display: "flex", alignItems: "center", gap: "0.2rem", fontSize: "0.82rem", cursor: "pointer" }}>
                            <input type="checkbox" checked={editRoles.includes(role)}
                              onChange={(e) =>
                                setEditRoles((prev) =>
                                  e.target.checked ? [...prev, role] : prev.filter((r) => r !== role)
                                )
                              }
                            />
                            {ROLE_LABELS[role] || role}
                          </label>
                        ))}
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                        {user.roles.map((r) => (
                          <span key={r} style={{ padding: "0.15rem 0.4rem", background: "#dbeafe", color: "#1e40af", borderRadius: "4px", fontSize: "0.78rem" }}>
                            {ROLE_LABELS[r] || r}
                          </span>
                        ))}
                        {user.roles.length === 0 && <span style={{ color: "#9ca3af" }}>ללא תפקיד</span>}
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    <span style={{ color: user.is_active ? "#166534" : "#9ca3af", fontWeight: "bold" }}>
                      {user.is_active ? "פעיל" : "מנוטרל"}
                    </span>
                  </td>
                  <td style={td}>
                    {editingId === user.id ? (
                      <div style={{ display: "flex", gap: "0.35rem" }}>
                        <button onClick={handleSaveRoles} disabled={saving}
                          style={{ padding: "0.2rem 0.6rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer", fontSize: "0.82rem" }}>
                          {saving ? "..." : "שמור"}
                        </button>
                        <button onClick={() => setEditingId(null)}
                          style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc", background: "#fff", cursor: "pointer", fontSize: "0.82rem" }}>
                          ביטול
                        </button>
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: "0.35rem" }}>
                        <button
                          onClick={() => { setEditingId(user.id); setEditRoles([...user.roles]); }}
                          style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", border: "1px solid #374151", background: "#fff", color: "#374151", cursor: "pointer", fontSize: "0.82rem" }}>
                          תפקידים
                        </button>
                        {user.is_active && (
                          <button onClick={() => handleDeactivate(user.id, user.email)}
                            style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", border: "1px solid #dc2626", background: "#fff", color: "#dc2626", cursor: "pointer", fontSize: "0.82rem" }}>
                            נטרל
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const th: React.CSSProperties = { padding: "0.5rem 0.75rem", textAlign: "right", fontWeight: "bold", fontSize: "0.85rem" };
const td: React.CSSProperties = { padding: "0.5rem 0.75rem", verticalAlign: "top" };
const navBtn: React.CSSProperties = { background: "transparent", border: "1px solid rgba(255,255,255,0.4)", color: "#fff", padding: "0.2rem 0.6rem", borderRadius: "4px", cursor: "pointer", fontSize: "0.82rem" };
