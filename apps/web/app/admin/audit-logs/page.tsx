"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, AuditLogItem, getMe, listAuditLogs } from "@/lib/api";

function formatDate(iso: string): string {
  try { return new Date(iso).toLocaleString("he-IL", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

export default function AuditLogsPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState("");
  const [actionInput, setActionInput] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  function handleAuthError() {
    localStorage.removeItem("chathr_token");
    router.push("/login");
  }

  async function load(t: string, af: string, off: number) {
    setLoading(true);
    setError(null);
    try {
      const data = await listAuditLogs(t, { action: af || undefined, offset: off, limit });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("לא ניתן לטעון לוג ביקורת.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = localStorage.getItem("chathr_token");
    if (!t) { router.push("/login"); return; }
    setToken(t);
    getMe(t).catch(() => handleAuthError());
    load(t, "", 0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFilter() {
    setActionFilter(actionInput);
    setOffset(0);
    if (token) load(token, actionInput, 0);
  }

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.6rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>לוג ביקורת</span>
        <button onClick={() => router.push("/chat")} style={{ background: "transparent", border: "1px solid rgba(255,255,255,0.4)", color: "#fff", padding: "0.2rem 0.6rem", borderRadius: "4px", cursor: "pointer", fontSize: "0.82rem" }}>
          צ׳אט
        </button>
      </header>

      <div style={{ padding: "1rem 1.5rem", flex: 1, overflow: "auto" }}>
        {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "0.6rem 1rem", color: "#b91c1c", marginBottom: "1rem" }}>{error}</div>}

        {/* Filter */}
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", alignItems: "center" }}>
          <input
            value={actionInput}
            onChange={(e) => setActionInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && applyFilter()}
            placeholder="סנן לפי פעולה..."
            style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc", width: "220px" }}
          />
          <button onClick={applyFilter} style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "none", background: "#2563eb", color: "#fff", cursor: "pointer" }}>
            סנן
          </button>
          {actionFilter && (
            <button onClick={() => { setActionInput(""); setActionFilter(""); setOffset(0); if (token) load(token, "", 0); }}
              style={{ padding: "0.3rem 0.6rem", borderRadius: "4px", border: "1px solid #ccc", background: "#fff", cursor: "pointer" }}>
              נקה
            </button>
          )}
          <span style={{ color: "#6b7280", fontSize: "0.82rem" }}>סה"כ: {total}</span>
        </div>

        {loading ? <div style={{ color: "#6b7280" }}>טוען...</div> : items.length === 0 ? (
          <div style={{ color: "#9ca3af" }}>אין רשומות.</div>
        ) : (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ background: "#f0f4f8", borderBottom: "2px solid #dde3ed" }}>
                  <th style={th}>תאריך</th>
                  <th style={th}>פעולה</th>
                  <th style={th}>שחקן</th>
                  <th style={th}>יעד</th>
                  <th style={th}>מטאדטה</th>
                </tr>
              </thead>
              <tbody>
                {items.map((log) => (
                  <tr key={log.id} style={{ borderBottom: "1px solid #eef0f3" }}>
                    <td style={td}>{formatDate(log.created_at)}</td>
                    <td style={td}>
                      <code style={{ background: "#f3f4f6", padding: "0.1rem 0.3rem", borderRadius: "3px", fontSize: "0.82rem" }}>{log.action}</code>
                    </td>
                    <td style={td}>
                      <span style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "#6b7280" }}>
                        {log.actor_user_id ? log.actor_user_id.slice(0, 8) + "..." : "—"}
                      </span>
                    </td>
                    <td style={td}>
                      {log.target_type && <span style={{ color: "#374151" }}>{log.target_type}</span>}
                      {log.target_id && <span style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "#6b7280" }}> · {log.target_id.slice(0, 8)}</span>}
                    </td>
                    <td style={{ ...td, maxWidth: "260px" }}>
                      {log.metadata_json ? (
                        <pre style={{ margin: 0, fontSize: "0.75rem", color: "#6b7280", whiteSpace: "pre-wrap", fontFamily: "monospace" }}>
                          {JSON.stringify(log.metadata_json, null, 1).slice(0, 200)}
                        </pre>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", justifyContent: "center" }}>
              <button disabled={offset === 0}
                onClick={() => { const off = Math.max(0, offset - limit); setOffset(off); if (token) load(token, actionFilter, off); }}
                style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", cursor: offset === 0 ? "not-allowed" : "pointer", background: "#fff" }}>
                ← קודם
              </button>
              <span style={{ lineHeight: "2rem", color: "#6b7280", fontSize: "0.85rem" }}>
                {offset + 1}–{Math.min(offset + items.length, total)} מתוך {total}
              </span>
              <button disabled={offset + items.length >= total}
                onClick={() => { const off = offset + limit; setOffset(off); if (token) load(token, actionFilter, off); }}
                style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", cursor: offset + items.length >= total ? "not-allowed" : "pointer", background: "#fff" }}>
                הבא →
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const th: React.CSSProperties = { padding: "0.5rem 0.75rem", textAlign: "right", fontWeight: "bold", fontSize: "0.85rem" };
const td: React.CSSProperties = { padding: "0.5rem 0.75rem", verticalAlign: "top" };
