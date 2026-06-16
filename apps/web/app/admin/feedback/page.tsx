"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, FeedbackItem, getMe, listAdminFeedback } from "@/lib/api";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("he-IL", { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

export default function FeedbackAdminPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ratingFilter, setRatingFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  function handleAuthError() {
    localStorage.removeItem("chathr_token");
    router.push("/login");
  }

  async function load(t: string, rf: string, off: number) {
    setLoading(true);
    setError(null);
    try {
      const data = await listAdminFeedback(t, { rating: rf || undefined, offset: off, limit });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) handleAuthError();
      else setError("לא ניתן לטעון משוב.");
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

  function applyFilter(rf: string) {
    setRatingFilter(rf);
    setOffset(0);
    if (token) load(token, rf, 0);
  }

  const positiveCount = items.filter((i) => i.rating === "positive").length;
  const negativeCount = items.filter((i) => i.rating === "negative").length;

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.6rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>לוח בקרת משוב</span>
        <button onClick={() => router.push("/chat")} style={{ background: "transparent", border: "1px solid rgba(255,255,255,0.4)", color: "#fff", padding: "0.2rem 0.6rem", borderRadius: "4px", cursor: "pointer", fontSize: "0.82rem" }}>
          צ׳אט
        </button>
      </header>

      <div style={{ padding: "1rem 1.5rem", flex: 1, overflow: "auto" }}>
        {error && (
          <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "0.6rem 1rem", color: "#b91c1c", marginBottom: "1rem" }}>
            {error}
          </div>
        )}

        {/* Summary cards */}
        <div style={{ display: "flex", gap: "1rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
          <div style={card}>
            <div style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#166534" }}>{items.filter((i) => i.rating === "positive").length}</div>
            <div style={{ fontSize: "0.85rem", color: "#6b7280" }}>חיובי (בעמוד זה)</div>
          </div>
          <div style={card}>
            <div style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#dc2626" }}>{items.filter((i) => i.rating === "negative").length}</div>
            <div style={{ fontSize: "0.85rem", color: "#6b7280" }}>שלילי (בעמוד זה)</div>
          </div>
          <div style={card}>
            <div style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#1e3a5f" }}>{total}</div>
            <div style={{ fontSize: "0.85rem", color: "#6b7280" }}>סה"כ רשומות</div>
          </div>
        </div>

        {/* Filters */}
        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", alignItems: "center" }}>
          <select value={ratingFilter} onChange={(e) => applyFilter(e.target.value)}
            style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", border: "1px solid #ccc" }}>
            <option value="">כל הדירוגים</option>
            <option value="positive">חיובי 👍</option>
            <option value="negative">שלילי 👎</option>
          </select>
        </div>

        {loading ? (
          <div style={{ color: "#6b7280" }}>טוען...</div>
        ) : items.length === 0 ? (
          <div style={{ color: "#9ca3af" }}>אין פריטים.</div>
        ) : (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
              <thead>
                <tr style={{ background: "#f0f4f8", borderBottom: "2px solid #dde3ed" }}>
                  <th style={th}>תאריך</th>
                  <th style={th}>דירוג</th>
                  <th style={th}>הערה</th>
                  <th style={th}>שיחה</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} style={{ borderBottom: "1px solid #eef0f3" }}>
                    <td style={td}>{formatDate(item.created_at)}</td>
                    <td style={td}>
                      <span style={{ fontSize: "1.2rem" }}>{item.rating === "positive" ? "👍" : "👎"}</span>
                    </td>
                    <td style={{ ...td, maxWidth: "400px" }}>
                      {item.comment ? (
                        <span style={{ color: "#374151" }}>{item.comment}</span>
                      ) : (
                        <span style={{ color: "#9ca3af" }}>ללא הערה</span>
                      )}
                    </td>
                    <td style={td}>
                      {item.conversation_id ? (
                        <span style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "#6b7280" }}>
                          {item.conversation_id.slice(0, 8)}...
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", justifyContent: "center" }}>
              <button
                disabled={offset === 0}
                onClick={() => { const off = Math.max(0, offset - limit); setOffset(off); if (token) load(token, ratingFilter, off); }}
                style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", cursor: offset === 0 ? "not-allowed" : "pointer", background: "#fff" }}
              >
                ← קודם
              </button>
              <span style={{ lineHeight: "2rem", color: "#6b7280", fontSize: "0.85rem" }}>
                {offset + 1}–{Math.min(offset + items.length, total)} מתוך {total}
              </span>
              <button
                disabled={offset + items.length >= total}
                onClick={() => { const off = offset + limit; setOffset(off); if (token) load(token, ratingFilter, off); }}
                style={{ padding: "0.3rem 0.75rem", borderRadius: "4px", border: "1px solid #ccc", cursor: offset + items.length >= total ? "not-allowed" : "pointer", background: "#fff" }}
              >
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
const card: React.CSSProperties = { background: "#f8fafc", border: "1px solid #dde3ed", borderRadius: "8px", padding: "0.75rem 1.25rem", minWidth: "120px" };
