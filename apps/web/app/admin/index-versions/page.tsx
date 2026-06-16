"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, IndexVersionResponse, getMe, listIndexVersions } from "@/lib/api";

const STATUS_LABELS: Record<string, string> = {
  building: "בבנייה",
  draft: "טיוטה",
  quality_check_failed: "בדיקת איכות נכשלה",
  ready: "מוכן",
  active: "פעיל",
  archived: "בארכיון",
};

const STATUS_COLORS: Record<string, string> = {
  building: "#92400e",
  draft: "#6b7280",
  quality_check_failed: "#dc2626",
  ready: "#1d4ed8",
  active: "#166534",
  archived: "#9ca3af",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("he-IL", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

export default function IndexVersionsPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [versions, setVersions] = useState<IndexVersionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");

  function handleAuthError() {
    localStorage.removeItem("chathr_token");
    router.push("/login");
  }

  async function load(t: string, sf: string) {
    setLoading(true);
    setError(null);
    try {
      setSources(await listIndexVersions(t, sf || undefined));
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("לא ניתן לטעון גרסאות אינדקס.");
    } finally {
      setLoading(false);
    }
  }

  function setSources(data: IndexVersionResponse[]) {
    setVersions(data.sort((a, b) => {
      const order = { active: 0, ready: 1, building: 2, draft: 3, quality_check_failed: 4, archived: 5 };
      return (order[a.status as keyof typeof order] ?? 9) - (order[b.status as keyof typeof order] ?? 9);
    }));
  }

  useEffect(() => {
    const t = localStorage.getItem("chathr_token");
    if (!t) { router.push("/login"); return; }
    setToken(t);
    getMe(t).catch(() => handleAuthError());
    load(t, "");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.6rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>גרסאות אינדקס</span>
        <nav style={{ display: "flex", gap: "0.5rem" }}>
          <button onClick={() => router.push("/admin/knowledge-sources")} style={navBtn}>מקורות ידע</button>
          <button onClick={() => router.push("/admin/knowledge/upload")} style={navBtn}>טעינת מסמך</button>
          <button onClick={() => router.push("/chat")} style={navBtn}>צ׳אט</button>
        </nav>
      </header>

      <div style={{ padding: "1rem 1.5rem", flex: 1, overflow: "auto" }}>
        {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "0.6rem 1rem", color: "#b91c1c", marginBottom: "1rem" }}>{error}</div>}

        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", alignItems: "center" }}>
          <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); if (token) load(token, e.target.value); }}
            style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}>
            <option value="">כל הסטטוסים</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <button onClick={() => { if (token) load(token, statusFilter); }}
            style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", background: "#fff", cursor: "pointer" }}>
            רענן
          </button>
          <span style={{ fontSize: "0.82rem", color: "#6b7280" }}>
            לניהול מלא של אינדקסים (עיבוד, בדיקה, הפעלה) — השתמש ב<button onClick={() => router.push("/admin/knowledge/upload")} style={{ background: "none", border: "none", color: "#2563eb", cursor: "pointer", textDecoration: "underline", fontSize: "0.82rem" }}>מסך טעינת מסמך</button>
          </span>
        </div>

        {loading ? <div style={{ color: "#6b7280" }}>טוען...</div> : versions.length === 0 ? (
          <div style={{ color: "#9ca3af" }}>אין גרסאות אינדקס.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
            <thead>
              <tr style={{ background: "#f0f4f8", borderBottom: "2px solid #dde3ed" }}>
                <th style={th}>תווית</th>
                <th style={th}>סטטוס</th>
                <th style={th}>מודל embedding</th>
                <th style={th}>נוצר</th>
                <th style={th}>הופעל</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((iv) => (
                <tr key={iv.id} style={{ borderBottom: "1px solid #eef0f3", background: iv.status === "active" ? "#f0fdf4" : "transparent" }}>
                  <td style={td}>
                    <div style={{ fontWeight: iv.status === "active" ? "bold" : "normal" }}>{iv.version_label}</div>
                    <div style={{ fontFamily: "monospace", fontSize: "0.75rem", color: "#9ca3af" }}>{iv.id.slice(0, 8)}...</div>
                  </td>
                  <td style={td}>
                    <span style={{ padding: "0.2rem 0.5rem", borderRadius: "4px", background: "#f3f4f6", color: STATUS_COLORS[iv.status] || "#374151", fontWeight: "bold", fontSize: "0.8rem" }}>
                      {STATUS_LABELS[iv.status] || iv.status}
                    </span>
                  </td>
                  <td style={td}>{iv.embedding_model}</td>
                  <td style={td}>{formatDate(iv.created_at)}</td>
                  <td style={td}>{formatDate(iv.activated_at)}</td>
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
