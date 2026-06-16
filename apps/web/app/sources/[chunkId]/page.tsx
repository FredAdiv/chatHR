"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ApiError, ChunkViewResponse, getChunk } from "@/lib/api";

const AUTHORITY_LABELS: Record<number, string> = {
  1: "גבוהה ביותר",
  2: "גבוהה",
  3: "בינונית",
  4: "נמוכה",
  5: "נמוכה ביותר",
};

const DOC_TYPE_LABELS: Record<string, string> = {
  takshir: 'תקשי"ר',
  pdf: "PDF",
  docx: "Word",
  html: "HTML",
  xlsx: "Excel",
  faq: "שאלות ותשובות (FAQ)",
};

export default function SourceViewerPage() {
  const params = useParams();
  const router = useRouter();
  const chunkId = params?.chunkId as string | undefined;

  const [chunk, setChunk] = useState<ChunkViewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("chathr_token");
    if (!token) {
      router.push("/login");
      return;
    }
    if (!chunkId) {
      setError("מזהה מקור חסר.");
      setLoading(false);
      return;
    }
    getChunk(token, chunkId)
      .then((data) => {
        setChunk(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          localStorage.removeItem("chathr_token");
          router.push("/login");
          return;
        }
        setError(
          err instanceof ApiError && err.status === 404
            ? "המקור המבוקש לא נמצא."
            : "שגיאה בטעינת המקור. אנא נסה שנית."
        );
        setLoading(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chunkId]);

  return (
    <div style={{ minHeight: "100vh", background: "#f9fafb", padding: "2rem 1.5rem" }}>
      <div style={{ maxWidth: "720px", margin: "0 auto" }}>
        {/* Back button */}
        <button
          onClick={() => router.back()}
          style={{
            background: "transparent",
            border: "none",
            color: "#2563eb",
            cursor: "pointer",
            fontSize: "0.9rem",
            padding: "0 0 1rem 0",
            display: "flex",
            alignItems: "center",
            gap: "0.3rem",
          }}
        >
          ← חזרה
        </button>

        <h1 style={{ fontSize: "1.3rem", fontWeight: "bold", color: "#1e3a5f", marginBottom: "1.5rem" }}>
          מקור מצוטט
        </h1>

        {loading && (
          <div style={{ color: "#6b7280", fontSize: "0.95rem" }}>טוען מקור...</div>
        )}

        {error && (
          <div
            style={{
              background: "#fef2f2",
              border: "1px solid #fca5a5",
              borderRadius: "6px",
              padding: "0.75rem 1rem",
              color: "#b91c1c",
              fontSize: "0.9rem",
            }}
          >
            {error}
          </div>
        )}

        {chunk && (
          <div
            style={{
              background: "#fff",
              border: "1px solid #d1d5db",
              borderRadius: "8px",
              padding: "1.5rem",
              display: "flex",
              flexDirection: "column",
              gap: "1rem",
            }}
          >
            {/* Metadata table */}
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.9rem" }}>
              <tbody>
                <MetaRow label="מסמך" value={chunk.source_title || chunk.knowledge_source_name} />
                <MetaRow label="מקור" value={chunk.knowledge_source_name} />
                {chunk.document_type && (
                  <MetaRow
                    label="סוג מקור"
                    value={DOC_TYPE_LABELS[chunk.document_type] ?? chunk.document_type}
                  />
                )}
                <MetaRow
                  label="רמת סמכות"
                  value={`${chunk.authority_level} — ${AUTHORITY_LABELS[chunk.authority_level] ?? ""}`}
                />
                {chunk.section_title && (
                  <MetaRow label="סעיף / פסקה" value={chunk.section_title} />
                )}
                {chunk.page_number != null && (
                  <MetaRow label="עמוד" value={String(chunk.page_number)} />
                )}
              </tbody>
            </table>

            {/* FAQ additional fields */}
            {chunk.document_type === "faq" && (
              <>
                <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "0.25rem 0" }} />
                <div>
                  <div style={{ fontSize: "0.8rem", fontWeight: "bold", color: "#374151", marginBottom: "0.4rem" }}>
                    שאלה:
                  </div>
                  <div style={{ fontSize: "0.92rem", color: "#1e293b", direction: "rtl", marginBottom: "0.75rem" }}>
                    {chunk.faq_question}
                  </div>
                  {chunk.faq_applicable_population && (
                    <div style={{ fontSize: "0.82rem", color: "#6b7280", marginBottom: "0.4rem" }}>
                      <strong>אוכלוסיה רלוונטית:</strong> {chunk.faq_applicable_population}
                    </div>
                  )}
                  {chunk.faq_official_source_links && chunk.faq_official_source_links.length > 0 && (
                    <div style={{ fontSize: "0.82rem", marginBottom: "0.4rem" }}>
                      <strong style={{ color: "#374151" }}>מקורות רשמיים:</strong>{" "}
                      {chunk.faq_official_source_links.map((link, i) => (
                        <span key={i}>
                          {i > 0 && ", "}
                          <a href={link} target="_blank" rel="noopener noreferrer" style={{ color: "#2563eb" }}>
                            {link}
                          </a>
                        </span>
                      ))}
                    </div>
                  )}
                  {chunk.faq_updated_at && (
                    <div style={{ fontSize: "0.78rem", color: "#9ca3af" }}>
                      עודכן: {new Date(chunk.faq_updated_at).toLocaleDateString("he-IL")}
                    </div>
                  )}
                </div>
              </>
            )}

            {/* Divider */}
            <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "0.25rem 0" }} />

            {/* Excerpt */}
            <div>
              <div
                style={{
                  fontSize: "0.8rem",
                  fontWeight: "bold",
                  color: "#374151",
                  marginBottom: "0.5rem",
                }}
              >
                קטע מצוטט:
              </div>
              <div
                style={{
                  background: "#f0f9ff",
                  border: "1px solid #bae6fd",
                  borderRadius: "6px",
                  padding: "0.75rem 1rem",
                  fontSize: "0.92rem",
                  lineHeight: 1.7,
                  whiteSpace: "pre-wrap",
                  color: "#1e293b",
                  direction: "rtl",
                }}
              >
                {chunk.excerpt}
              </div>
            </div>

            {/* Disclaimer */}
            <p style={{ fontSize: "0.78rem", color: "#9ca3af", margin: 0 }}>
              {chunk.document_type === "faq"
                ? "תשובה זו מבוססת על FAQ מאושר. אינה מחליפה את הוראות התקשי\"ר או הסכמי שכר."
                : "קטע זה נלקח ממסמך רשמי שאונדקס במערכת. התוכן מוצג כפי שנשמר במערכת."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <tr>
      <td
        style={{
          padding: "0.3rem 1rem 0.3rem 0",
          fontWeight: "bold",
          color: "#374151",
          whiteSpace: "nowrap",
          verticalAlign: "top",
          width: "130px",
        }}
      >
        {label}:
      </td>
      <td style={{ padding: "0.3rem 0", color: "#1f2937" }}>{value}</td>
    </tr>
  );
}
