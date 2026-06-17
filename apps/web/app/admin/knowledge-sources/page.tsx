"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  KnowledgeSourceResponse,
  createKnowledgeSource,
  getMe,
  listKnowledgeSources,
  updateKnowledgeSource,
} from "@/lib/api";

const ALL_CONTEXTS: { value: string; label: string }[] = [
  { value: "general", label: "כלל (כללי)" },
  { value: "government_ministries", label: "משרדי ממשלה" },
  { value: "defense_system", label: "מערכת הביטחון" },
  { value: "health_system", label: "מערכת הבריאות" },
];

const CONTEXT_LABELS: Record<string, string> = Object.fromEntries(
  ALL_CONTEXTS.map((c) => [c.value, c.label])
);

const AUTHORITY_LABELS: Record<number, string> = {
  1: "1 - תקשי\"ר / הסכמי שכר",
  2: "2 - הנחיות נציב / חוזרים מחייבים",
  3: "3 - מדיניות / הנחיות יישום",
  4: "4 - FAQ מאושר",
  5: "5 - מסמכי הסבר כלליים",
};

interface EditForm {
  name: string;
  source_type: string;
  url: string;
  authority_level: number;
  is_active: boolean;
  contexts: string[];
}

const EMPTY_FORM: EditForm = {
  name: "",
  source_type: "file",
  url: "",
  authority_level: 3,
  is_active: true,
  contexts: [],
};

export default function KnowledgeSourcesPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [sources, setSources] = useState<KnowledgeSourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<EditForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  function handleAuthError() {
    localStorage.removeItem("chathr_token");
    router.push("/login");
  }

  async function load(t: string) {
    setLoading(true);
    try {
      setSources(await listKnowledgeSources(t));
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("לא ניתן לטעון מקורות ידע.");
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

  function startEdit(src: KnowledgeSourceResponse) {
    setEditingId(src.id);
    setShowCreate(false);
    setForm({
      name: src.name,
      source_type: src.source_type,
      url: src.url || "",
      authority_level: src.authority_level,
      is_active: src.is_active,
      contexts: src.contexts || [],
    });
  }

  function toggleContext(value: string) {
    setForm((f) => ({
      ...f,
      contexts: f.contexts.includes(value)
        ? f.contexts.filter((c) => c !== value)
        : [...f.contexts, value],
    }));
  }

  async function handleSave() {
    if (!token) return;
    setSaving(true);
    setError(null);
    const payload = {
      name: form.name,
      source_type: form.source_type,
      url: form.url || undefined,
      authority_level: form.authority_level,
      is_active: form.is_active,
      contexts: form.contexts,
    };
    try {
      if (showCreate) {
        await createKnowledgeSource(token, payload);
      } else if (editingId) {
        await updateKnowledgeSource(token, editingId, payload);
      }
      setEditingId(null);
      setShowCreate(false);
      setForm(EMPTY_FORM);
      await load(token);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("שגיאה בשמירה.");
    } finally {
      setSaving(false);
    }
  }

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.6rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>מקורות ידע</span>
        <nav style={{ display: "flex", gap: "0.5rem" }}>
          <button onClick={() => router.push("/admin")} style={navBtn}>לוח בקרה</button>
          <button onClick={() => router.push("/admin/index-versions")} style={navBtn}>גרסאות אינדקס</button>
          <button onClick={() => router.push("/admin/knowledge/upload")} style={navBtn}>טעינת מסמך</button>
          <button onClick={() => router.push("/chat")} style={navBtn}>צ׳אט</button>
        </nav>
      </header>

      <div style={{ padding: "1rem 1.5rem", flex: 1, overflow: "auto" }}>
        {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "0.6rem 1rem", color: "#b91c1c", marginBottom: "1rem" }}>{error}</div>}

        <div style={{ marginBottom: "1rem" }}>
          <button
            onClick={() => { setShowCreate(true); setEditingId(null); setForm(EMPTY_FORM); }}
            style={{ padding: "0.35rem 1rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer", fontWeight: "bold" }}
          >
            + מקור חדש
          </button>
        </div>

        {(showCreate || editingId) && (
          <div style={{ background: "#f8fafc", border: "1px solid #dde3ed", borderRadius: "8px", padding: "1rem", marginBottom: "1.5rem" }}>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>{showCreate ? "מקור ידע חדש" : "עריכת מקור"}</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <input placeholder="שם *" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                style={{ padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc" }} />
              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: "150px" }}>
                  <label style={{ fontSize: "0.82rem" }}>סוג מקור</label>
                  <input value={form.source_type} onChange={(e) => setForm((f) => ({ ...f, source_type: e.target.value }))}
                    style={{ display: "block", width: "100%", padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc", marginTop: "0.2rem" }} />
                </div>
                <div style={{ flex: 1, minWidth: "150px" }}>
                  <label style={{ fontSize: "0.82rem" }}>רמת סמכות</label>
                  <select value={form.authority_level} onChange={(e) => setForm((f) => ({ ...f, authority_level: Number(e.target.value) }))}
                    style={{ display: "block", width: "100%", padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc", marginTop: "0.2rem" }}>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{AUTHORITY_LABELS[n]}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label style={{ fontSize: "0.82rem", display: "block", marginBottom: "0.3rem" }}>הקשרים (ניתן לבחור מספר)</label>
                <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                  {ALL_CONTEXTS.map((ctx) => (
                    <label key={ctx.value} style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.85rem", cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={form.contexts.includes(ctx.value)}
                        onChange={() => toggleContext(ctx.value)}
                      />
                      {ctx.label}
                    </label>
                  ))}
                </div>
              </div>
              <input placeholder="URL (אופציונלי)" value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                style={{ padding: "0.35rem", borderRadius: "4px", border: "1px solid #ccc", fontFamily: "monospace" }} />
              <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.85rem", cursor: "pointer" }}>
                <input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
                פעיל
              </label>
            </div>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", justifyContent: "flex-end" }}>
              <button onClick={() => { setEditingId(null); setShowCreate(false); setForm(EMPTY_FORM); }}
                style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", background: "#fff", cursor: "pointer" }}>ביטול</button>
              <button onClick={handleSave} disabled={saving || !form.name.trim()}
                style={{ padding: "0.3rem 1rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer", fontWeight: "bold" }}>
                {saving ? "שומר..." : "שמור"}
              </button>
            </div>
          </div>
        )}

        {loading ? <div style={{ color: "#6b7280" }}>טוען...</div> : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
            <thead>
              <tr style={{ background: "#f0f4f8", borderBottom: "2px solid #dde3ed" }}>
                <th style={th}>שם</th>
                <th style={th}>סוג</th>
                <th style={th}>רמת סמכות</th>
                <th style={th}>הקשרים</th>
                <th style={th}>סטטוס</th>
                <th style={th}>פעולות</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((src) => (
                <tr key={src.id} style={{ borderBottom: "1px solid #eef0f3" }}>
                  <td style={td}><strong>{src.name}</strong></td>
                  <td style={td}>{src.source_type}</td>
                  <td style={td}>{AUTHORITY_LABELS[src.authority_level] || src.authority_level}</td>
                  <td style={td}>
                    {src.contexts && src.contexts.length > 0
                      ? src.contexts.map((c) => CONTEXT_LABELS[c] || c).join(", ")
                      : <span style={{ color: "#9ca3af" }}>ללא הגדרה</span>}
                  </td>
                  <td style={td}>
                    <span style={{ color: src.is_active ? "#166534" : "#9ca3af", fontWeight: "bold" }}>{src.is_active ? "פעיל" : "לא פעיל"}</span>
                  </td>
                  <td style={td}>
                    <button onClick={() => startEdit(src)}
                      style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", border: "1px solid #374151", background: "#fff", color: "#374151", cursor: "pointer", fontSize: "0.82rem" }}>
                      עריכה
                    </button>
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
