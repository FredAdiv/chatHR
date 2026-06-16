"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  FaqItemResponse,
  approveFaq,
  archiveFaq,
  createFaq,
  getMe,
  listFaq,
  updateFaq,
} from "@/lib/api";

const CONTEXT_LABELS: Record<string, string> = {
  government_ministries: "משרדי ממשלה",
  defense_system: "מערכת הביטחון",
  health_system: "מערכת הבריאות",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "טיוטה",
  approved: "מאושר",
  archived: "בארכיון",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "#92400e",
  approved: "#166534",
  archived: "#6b7280",
};

function AdminNav({ router }: { router: ReturnType<typeof useRouter> }) {
  return (
    <nav style={{ display: "flex", gap: "0.5rem" }}>
      <button onClick={() => router.push("/chat")} style={navBtn}>צ׳אט</button>
    </nav>
  );
}

const navBtn: React.CSSProperties = {
  background: "transparent",
  border: "1px solid rgba(255,255,255,0.4)",
  color: "#fff",
  padding: "0.2rem 0.6rem",
  borderRadius: "4px",
  cursor: "pointer",
  fontSize: "0.82rem",
};

interface EditForm {
  question: string;
  answer: string;
  topic: string;
  context_type: string;
  applicable_population: string;
  official_source_links: string;
}

const EMPTY_FORM: EditForm = {
  question: "",
  answer: "",
  topic: "",
  context_type: "",
  applicable_population: "",
  official_source_links: "",
};

export default function FaqAdminPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [items, setItems] = useState<FaqItemResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<EditForm>(EMPTY_FORM);
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);

  function handleAuthError() {
    localStorage.removeItem("chathr_token");
    router.push("/login");
  }

  async function load(t: string, sf: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await listFaq(t, sf ? { status: sf } : {});
      setItems(data);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("לא ניתן לטעון פריטי FAQ.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = localStorage.getItem("chathr_token");
    if (!t) { router.push("/login"); return; }
    setToken(t);
    getMe(t).catch(() => handleAuthError());
    load(t, "");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startEdit(item: FaqItemResponse) {
    setEditingId(item.id);
    setShowCreate(false);
    setForm({
      question: item.question,
      answer: item.answer,
      topic: item.topic || "",
      context_type: item.context_type || "",
      applicable_population: item.applicable_population || "",
      official_source_links: (item.official_source_links || []).join("\n"),
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setShowCreate(false);
    setForm(EMPTY_FORM);
  }

  async function handleSave() {
    if (!token) return;
    setSaving(true);
    setError(null);
    const links = form.official_source_links
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    const payload = {
      question: form.question,
      answer: form.answer,
      topic: form.topic || undefined,
      context_type: (form.context_type as "government_ministries" | "defense_system" | "health_system") || undefined,
      applicable_population: form.applicable_population || undefined,
      official_source_links: links,
    };
    try {
      if (showCreate) {
        await createFaq(token, payload);
      } else if (editingId) {
        await updateFaq(token, editingId, payload);
      }
      cancelEdit();
      await load(token, statusFilter);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("שגיאה בשמירה.");
    } finally {
      setSaving(false);
    }
  }

  async function handleApprove(id: string) {
    if (!token) return;
    try {
      await approveFaq(token, id);
      await load(token, statusFilter);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("שגיאה באישור.");
    }
  }

  async function handleArchive(id: string) {
    if (!token) return;
    if (!confirm("לארכב פריט זה?")) return;
    try {
      await archiveFaq(token, id);
      await load(token, statusFilter);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("שגיאה בארכוב.");
    }
  }

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.6rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>ניהול FAQ</span>
        <AdminNav router={router} />
      </header>

      <div style={{ padding: "1rem 1.5rem", flex: 1, overflow: "auto" }}>
        {error && (
          <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "0.6rem 1rem", color: "#b91c1c", marginBottom: "1rem" }}>
            {error}
          </div>
        )}

        {/* Toolbar */}
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap" }}>
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); if (token) load(token, e.target.value); }}
            style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}
          >
            <option value="">כל הסטטוסים</option>
            <option value="draft">טיוטה</option>
            <option value="approved">מאושר</option>
            <option value="archived">בארכיון</option>
          </select>
          <button
            onClick={() => { setShowCreate(true); setEditingId(null); setForm(EMPTY_FORM); }}
            style={{ padding: "0.35rem 1rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer", fontWeight: "bold" }}
          >
            + פריט חדש
          </button>
        </div>

        {/* Create/Edit form */}
        {(showCreate || editingId) && (
          <div style={{ background: "#f8fafc", border: "1px solid #dde3ed", borderRadius: "8px", padding: "1rem", marginBottom: "1.5rem" }}>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>{showCreate ? "פריט FAQ חדש" : "עריכת פריט"}</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <label style={{ fontSize: "0.85rem", fontWeight: "bold" }}>שאלה *</label>
              <textarea rows={2} value={form.question} onChange={(e) => setForm((f) => ({ ...f, question: e.target.value }))}
                style={{ padding: "0.4rem", borderRadius: "4px", border: "1px solid #ccc", resize: "vertical" }} />

              <label style={{ fontSize: "0.85rem", fontWeight: "bold" }}>תשובה *</label>
              <textarea rows={4} value={form.answer} onChange={(e) => setForm((f) => ({ ...f, answer: e.target.value }))}
                style={{ padding: "0.4rem", borderRadius: "4px", border: "1px solid #ccc", resize: "vertical" }} />

              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: "180px" }}>
                  <label style={{ fontSize: "0.85rem", fontWeight: "bold" }}>נושא</label>
                  <input value={form.topic} onChange={(e) => setForm((f) => ({ ...f, topic: e.target.value }))}
                    style={{ display: "block", width: "100%", padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc", marginTop: "0.2rem" }} />
                </div>
                <div style={{ flex: 1, minWidth: "180px" }}>
                  <label style={{ fontSize: "0.85rem", fontWeight: "bold" }}>הקשר</label>
                  <select value={form.context_type} onChange={(e) => setForm((f) => ({ ...f, context_type: e.target.value }))}
                    style={{ display: "block", width: "100%", padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc", marginTop: "0.2rem" }}>
                    <option value="">כללי</option>
                    <option value="government_ministries">משרדי ממשלה</option>
                    <option value="defense_system">מערכת הביטחון</option>
                    <option value="health_system">מערכת הבריאות</option>
                  </select>
                </div>
              </div>

              <label style={{ fontSize: "0.85rem", fontWeight: "bold" }}>קישורי מקורות רשמיים (שורה לכל קישור)</label>
              <textarea rows={2} value={form.official_source_links}
                onChange={(e) => setForm((f) => ({ ...f, official_source_links: e.target.value }))}
                placeholder="https://..."
                style={{ padding: "0.4rem", borderRadius: "4px", border: "1px solid #ccc", resize: "vertical", fontFamily: "monospace", fontSize: "0.85rem" }} />
            </div>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", justifyContent: "flex-end" }}>
              <button onClick={cancelEdit} style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", background: "#fff", cursor: "pointer" }}>
                ביטול
              </button>
              <button onClick={handleSave} disabled={saving || !form.question.trim() || !form.answer.trim()}
                style={{ padding: "0.3rem 1rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer", fontWeight: "bold" }}>
                {saving ? "שומר..." : "שמור"}
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div style={{ color: "#6b7280" }}>טוען...</div>
        ) : items.length === 0 ? (
          <div style={{ color: "#9ca3af" }}>אין פריטים.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
            <thead>
              <tr style={{ background: "#f0f4f8", borderBottom: "2px solid #dde3ed" }}>
                <th style={th}>שאלה</th>
                <th style={th}>נושא</th>
                <th style={th}>הקשר</th>
                <th style={th}>סטטוס</th>
                <th style={th}>פעולות</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} style={{ borderBottom: "1px solid #eef0f3" }}>
                  <td style={{ ...td, maxWidth: "300px" }}>
                    <div style={{ fontWeight: "bold", marginBottom: "0.2rem" }}>{item.question}</div>
                    <div style={{ color: "#6b7280", fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>{item.answer.slice(0, 120)}{item.answer.length > 120 ? "..." : ""}</div>
                  </td>
                  <td style={td}>{item.topic || "—"}</td>
                  <td style={td}>{item.context_type ? CONTEXT_LABELS[item.context_type] || item.context_type : "כללי"}</td>
                  <td style={td}>
                    <span style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", background: "#f3f4f6", color: STATUS_COLORS[item.status] || "#374151", fontWeight: "bold", fontSize: "0.8rem" }}>
                      {STATUS_LABELS[item.status] || item.status}
                    </span>
                  </td>
                  <td style={td}>
                    <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                      <button onClick={() => startEdit(item)} style={actionBtn("#374151")}>עריכה</button>
                      {item.status === "draft" && (
                        <button onClick={() => handleApprove(item.id)} style={actionBtn("#166534")}>אשר</button>
                      )}
                      {item.status !== "archived" && (
                        <button onClick={() => handleArchive(item.id)} style={actionBtn("#6b7280")}>ארכב</button>
                      )}
                    </div>
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
function actionBtn(color: string): React.CSSProperties {
  return { padding: "0.2rem 0.5rem", borderRadius: "4px", border: `1px solid ${color}`, background: "#fff", color, cursor: "pointer", fontSize: "0.8rem" };
}
