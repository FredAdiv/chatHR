"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, getMe } from "@/lib/api";

const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".html", ".htm", ".txt"];
const MAX_MB = 20;

const TAKSHIR_PRESET = {
  title: 'תקשי"ר',
  document_type: "takshir",
  authority_level: 1,
};

interface UploadResult {
  document_id: string;
  knowledge_source_id: string;
  status: string;
  message: string;
}

interface ProcessResult {
  document_id: string;
  status: string;
  index_version_id: string;
  index_version_label: string;
  chunk_count: number;
  message: string;
}

interface QualityCheck {
  name: string;
  passed: boolean;
  message: string;
}

interface QualityCheckResult {
  index_version_id: string;
  overall_passed: boolean;
  status: string;
  checks: QualityCheck[];
  checked_at: string;
  chunk_count: number;
}

interface ActivationResult {
  index_version_id: string;
  status: string;
  version_label: string;
  activated_at: string;
  previous_active_id: string | null;
  message: string;
}

export default function KnowledgeUploadPage() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [token, setToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [authorityLevel, setAuthorityLevel] = useState<number>(1);
  const [sourceUrl, setSourceUrl] = useState("");
  const [systemContext, setSystemContext] = useState("");
  const [notes, setNotes] = useState("");

  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const [processing, setProcessing] = useState(false);
  const [processResult, setProcessResult] = useState<ProcessResult | null>(null);
  const [processError, setProcessError] = useState<string | null>(null);

  const [qualityChecking, setQualityChecking] = useState(false);
  const [qualityResult, setQualityResult] = useState<QualityCheckResult | null>(null);
  const [qualityError, setQualityError] = useState<string | null>(null);

  const [activating, setActivating] = useState(false);
  const [activationResult, setActivationResult] = useState<ActivationResult | null>(null);
  const [activationError, setActivationError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const t = localStorage.getItem("chathr_token");
    if (!t) { router.push("/login"); return; }
    setToken(t);
    getMe(t)
      .then((me) => {
        const hasRole = me.roles.includes("knowledge_admin") || me.roles.includes("system_admin");
        if (!hasRole) {
          setGlobalError("אין לך הרשאה לגשת לדף זה. נדרשת הרשאת knowledge_admin או system_admin.");
          return;
        }
        setUserEmail(me.email);
      })
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          localStorage.removeItem("chathr_token");
          router.push("/login");
        } else {
          setGlobalError("לא ניתן לטעון פרטי משתמש.");
        }
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyTakshirPreset() {
    setTitle(TAKSHIR_PRESET.title);
    setDocumentType(TAKSHIR_PRESET.document_type);
    setAuthorityLevel(TAKSHIR_PRESET.authority_level);
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setErrors([]);
    setResult(null);
  }

  function validate(): string[] {
    const errs: string[] = [];
    if (!file) { errs.push("יש לבחור קובץ."); }
    if (!title.trim()) { errs.push("שדה 'כותרת' הוא חובה."); }
    if (!documentType.trim()) { errs.push("שדה 'סוג מסמך' הוא חובה."); }
    if (authorityLevel < 1 || authorityLevel > 5) { errs.push("רמת הסמכות חייבת להיות בין 1 ל-5."); }
    if (file) {
      const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        errs.push(`סיומת הקובץ '${ext}' אינה נתמכת. סיומות נתמכות: ${ALLOWED_EXTENSIONS.join(", ")}.`);
      }
      if (file.size === 0) { errs.push("הקובץ שנבחר ריק."); }
      if (file.size > MAX_MB * 1024 * 1024) { errs.push(`הקובץ גדול מ-${MAX_MB} MB.`); }
    }
    return errs;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setResult(null);
    setGlobalError(null);

    const validationErrors = validate();
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setErrors([]);

    if (!token || !file) return;
    setUploading(true);

    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
      const form = new FormData();
      form.append("file", file);
      form.append("title", title.trim());
      form.append("document_type", documentType.trim());
      form.append("authority_level", String(authorityLevel));
      if (sourceUrl.trim()) form.append("source_url", sourceUrl.trim());
      if (systemContext.trim()) form.append("system_context", systemContext.trim());
      if (notes.trim()) form.append("notes", notes.trim());

      const res = await fetch(`${base}/admin/knowledge/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });

      if (!res.ok) {
        let detail: { error?: string; message?: string } | string = res.statusText;
        try { detail = await res.json(); } catch { /* use statusText */ }
        if (res.status === 401 || res.status === 403) {
          const msg = typeof detail === "object" ? detail?.message ?? "אין הרשאה." : "אין הרשאה.";
          setErrors([msg]);
        } else if (res.status === 422 && typeof detail === "object" && detail?.message) {
          setErrors([detail.message]);
        } else {
          setErrors(["שגיאה בהעלאה. אנא נסה שנית."]);
        }
        return;
      }

      const data: UploadResult = await res.json();
      setResult(data);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch {
      setErrors(["שגיאת רשת. אנא בדוק את החיבור ונסה שנית."]);
    } finally {
      setUploading(false);
    }
  }

  async function handleProcess(documentId: string) {
    if (!token) return;
    setProcessing(true);
    setProcessResult(null);
    setProcessError(null);
    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
      const res = await fetch(`${base}/admin/knowledge/documents/${documentId}/process`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        let detail: { error?: string; message?: string } | string = res.statusText;
        try { detail = await res.json(); } catch { /* use statusText */ }
        const msg = typeof detail === "object" ? detail?.message ?? "שגיאה בעיבוד." : "שגיאה בעיבוד.";
        setProcessError(msg);
        return;
      }
      const data: ProcessResult = await res.json();
      setProcessResult(data);
    } catch {
      setProcessError("שגיאת רשת. אנא בדוק את החיבור ונסה שנית.");
    } finally {
      setProcessing(false);
    }
  }

  async function handleQualityCheck(indexVersionId: string) {
    if (!token) return;
    setQualityChecking(true);
    setQualityResult(null);
    setQualityError(null);
    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
      const res = await fetch(`${base}/admin/knowledge/index-versions/${indexVersionId}/quality-check`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        let detail: { error?: string; message?: string } | string = res.statusText;
        try { detail = await res.json(); } catch { /* use statusText */ }
        const msg = typeof detail === "object" ? detail?.message ?? "שגיאה בבדיקות איכות." : "שגיאה בבדיקות איכות.";
        setQualityError(msg);
        return;
      }
      const data: QualityCheckResult = await res.json();
      setQualityResult(data);
    } catch {
      setQualityError("שגיאת רשת. אנא בדוק את החיבור ונסה שנית.");
    } finally {
      setQualityChecking(false);
    }
  }

  async function handleActivate(indexVersionId: string) {
    if (!token) return;
    setActivating(true);
    setActivationResult(null);
    setActivationError(null);
    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
      const res = await fetch(`${base}/admin/knowledge/index-versions/${indexVersionId}/activate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        let detail: { error?: string; message?: string } | string = res.statusText;
        try { detail = await res.json(); } catch { /* use statusText */ }
        const msg = typeof detail === "object" ? detail?.message ?? "שגיאה בהפעלת האינדקס." : "שגיאה בהפעלת האינדקס.";
        setActivationError(msg);
        return;
      }
      const data: ActivationResult = await res.json();
      setActivationResult(data);
    } catch {
      setActivationError("שגיאת רשת. אנא בדוק את החיבור ונסה שנית.");
    } finally {
      setActivating(false);
    }
  }

  function logout() {
    if (typeof window !== "undefined") localStorage.removeItem("chathr_token");
    router.push("/login");
  }

  const labelStyle: React.CSSProperties = {
    display: "block",
    fontWeight: "bold",
    marginBottom: "0.25rem",
    fontSize: "0.93rem",
  };
  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "0.45rem 0.7rem",
    boxSizing: "border-box",
    fontSize: "0.95rem",
    borderRadius: "4px",
    border: "1px solid #ccc",
  };

  if (globalError) {
    return (
      <main style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "#f0f4f8" }}>
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "8px", padding: "2rem", maxWidth: "480px", textAlign: "center", color: "#b91c1c" }}>
          {globalError}
        </div>
      </main>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "#f0f4f8" }}>
      {/* Header */}
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.75rem 1.5rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>ChatHR — העלאת מסמך</span>
        {userEmail && <span style={{ fontSize: "0.85rem", opacity: 0.85 }}>{userEmail}</span>}
        <button onClick={logout} style={{ background: "transparent", border: "1px solid rgba(255,255,255,0.45)", color: "#fff", padding: "0.25rem 0.75rem", borderRadius: "4px", cursor: "pointer" }}>
          יציאה
        </button>
      </header>

      <main style={{ maxWidth: "640px", margin: "2rem auto", padding: "0 1rem" }}>
        {/* Privacy warning */}
        <div style={{ background: "#fffbeb", border: "1px solid #f59e0b", borderRadius: "6px", padding: "0.75rem 1rem", marginBottom: "1.5rem", fontSize: "0.9rem", color: "#92400e" }}>
          <strong>אזהרת פרטיות:</strong> אל תעלה מסמכים המכילים פרטים מזהים אישיים של עובדים (שם, ת.ז., פרטי קשר וכד&apos;). המסמך ייכנס לבסיס הידע הארגוני.
        </div>

        {/* Form */}
        <div style={{ background: "#fff", borderRadius: "8px", boxShadow: "0 2px 10px rgba(0,0,0,0.08)", padding: "1.75rem" }}>
          <h1 style={{ marginTop: 0, marginBottom: "1.25rem", fontSize: "1.3rem", color: "#1e3a5f" }}>העלאה ידנית לבסיס הידע</h1>

          {/* Takshir preset */}
          <div style={{ marginBottom: "1.25rem" }}>
            <button
              type="button"
              onClick={applyTakshirPreset}
              style={{ padding: "0.4rem 1rem", borderRadius: "4px", border: "1px solid #2563eb", background: "#eff6ff", color: "#1d4ed8", cursor: "pointer", fontWeight: "bold", fontSize: "0.9rem" }}
            >
              טען פריסט — תקשי&quot;ר
            </button>
            <span style={{ marginRight: "0.6rem", fontSize: "0.82rem", color: "#6b7280" }}>ממלא כותרת, סוג מסמך ורמת סמכות עבור תקשי&quot;ר</span>
          </div>

          <form onSubmit={handleSubmit} noValidate>
            {/* File */}
            <div style={{ marginBottom: "1rem" }}>
              <label htmlFor="file" style={labelStyle}>קובץ <span style={{ color: "#dc2626" }}>*</span></label>
              <input
                id="file"
                type="file"
                ref={fileRef}
                onChange={handleFileChange}
                accept={ALLOWED_EXTENSIONS.join(",")}
                style={{ ...inputStyle, padding: "0.3rem 0" }}
              />
              <span style={{ fontSize: "0.78rem", color: "#6b7280" }}>סיומות נתמכות: {ALLOWED_EXTENSIONS.join(", ")} · עד {MAX_MB} MB</span>
            </div>

            {/* Title */}
            <div style={{ marginBottom: "1rem" }}>
              <label htmlFor="title" style={labelStyle}>כותרת <span style={{ color: "#dc2626" }}>*</span></label>
              <input
                id="title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                style={inputStyle}
                placeholder='לדוגמה: תקשי"ר, חוזר מנכ"ל'
              />
            </div>

            {/* Document type */}
            <div style={{ marginBottom: "1rem" }}>
              <label htmlFor="document_type" style={labelStyle}>סוג מסמך <span style={{ color: "#dc2626" }}>*</span></label>
              <input
                id="document_type"
                type="text"
                value={documentType}
                onChange={(e) => setDocumentType(e.target.value)}
                style={inputStyle}
                placeholder="לדוגמה: takshir, policy, circular"
              />
            </div>

            {/* Authority level */}
            <div style={{ marginBottom: "1rem" }}>
              <label htmlFor="authority_level" style={labelStyle}>רמת סמכות (1-5, נמוך = גבוה יותר) <span style={{ color: "#dc2626" }}>*</span></label>
              <input
                id="authority_level"
                type="number"
                min={1}
                max={5}
                value={authorityLevel}
                onChange={(e) => setAuthorityLevel(Number(e.target.value))}
                style={{ ...inputStyle, width: "80px" }}
              />
            </div>

            {/* Source URL (optional) */}
            <div style={{ marginBottom: "1rem" }}>
              <label htmlFor="source_url" style={labelStyle}>קישור מקור (אופציונלי)</label>
              <input
                id="source_url"
                type="url"
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                style={inputStyle}
                placeholder="https://www.gov.il/he/..."
              />
              <span style={{ fontSize: "0.78rem", color: "#6b7280" }}>לציטוט בלבד — אינו מורד</span>
            </div>

            {/* System context (optional) */}
            <div style={{ marginBottom: "1rem" }}>
              <label htmlFor="system_context" style={labelStyle}>הקשר מערכת (אופציונלי)</label>
              <input
                id="system_context"
                type="text"
                value={systemContext}
                onChange={(e) => setSystemContext(e.target.value)}
                style={inputStyle}
                placeholder="לדוגמה: government_ministries"
              />
            </div>

            {/* Notes (optional) */}
            <div style={{ marginBottom: "1.5rem" }}>
              <label htmlFor="notes" style={labelStyle}>הערות (אופציונלי)</label>
              <textarea
                id="notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                style={{ ...inputStyle, resize: "vertical" }}
                rows={3}
                placeholder="הערות אדמין פנימיות"
              />
            </div>

            {/* Validation errors */}
            {errors.length > 0 && (
              <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "0.65rem 1rem", marginBottom: "1rem", color: "#b91c1c", fontSize: "0.9rem" }}>
                {errors.map((e, i) => <div key={i}>{e}</div>)}
              </div>
            )}

            {/* Upload Success + Process button */}
            {result && (
              <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "6px", padding: "0.75rem 1rem", marginBottom: "1rem", color: "#166534", fontSize: "0.9rem" }}>
                <div style={{ fontWeight: "bold", marginBottom: "0.3rem" }}>המסמך הועלה בהצלחה</div>
                <div>{result.message}</div>
                <div style={{ marginTop: "0.4rem", fontSize: "0.82rem", color: "#374151" }}>
                  <span>מזהה מסמך: {result.document_id}</span><br />
                  <span>מצב: {processResult ? processResult.status : result.status}</span>
                  {processResult && (
                    <>
                      <br /><span>גרסת אינדקס: {processResult.index_version_label}</span>
                      <br /><span>קטעים: {processResult.chunk_count}</span>
                    </>
                  )}
                </div>

                {!processResult && (
                  <div style={{ marginTop: "0.75rem" }}>
                    <div style={{ fontSize: "0.82rem", color: "#374151", marginBottom: "0.4rem" }}>
                      השלב הבא: עיבוד המסמך לאינדקס טיוטה (ניתוח, פיצול לקטעים, הטמעה).
                      <br /><strong>אינדקס הטיוטה לא יפורסם למשתמשים אוטומטית.</strong>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleProcess(result.document_id)}
                      disabled={processing}
                      style={{
                        padding: "0.4rem 1rem",
                        borderRadius: "4px",
                        border: "none",
                        background: processing ? "#86efac" : "#16a34a",
                        color: "#fff",
                        cursor: processing ? "not-allowed" : "pointer",
                        fontWeight: "bold",
                        fontSize: "0.9rem",
                      }}
                    >
                      {processing ? "מעבד..." : "עבד מסמך לאינדקס טיוטה"}
                    </button>
                    {processError && (
                      <div style={{ marginTop: "0.4rem", color: "#b91c1c", fontSize: "0.85rem" }}>{processError}</div>
                    )}
                  </div>
                )}

                {processResult && !qualityResult && !activationResult && (
                  <div style={{ marginTop: "0.6rem" }}>
                    <div style={{ padding: "0.5rem 0.75rem", background: "#dcfce7", borderRadius: "4px", fontSize: "0.85rem", color: "#14532d", marginBottom: "0.5rem" }}>
                      <strong>עיבוד הושלם</strong> — {processResult.chunk_count} קטעים, אינדקס טיוטה נוצר.
                    </div>
                    <div style={{ fontSize: "0.82rem", color: "#374151", marginBottom: "0.4rem" }}>
                      השלב הבא: הרץ בדיקות איכות לפני פרסום האינדקס.
                    </div>
                    <button
                      type="button"
                      onClick={() => handleQualityCheck(processResult.index_version_id)}
                      disabled={qualityChecking}
                      style={{
                        padding: "0.4rem 1rem",
                        borderRadius: "4px",
                        border: "none",
                        background: qualityChecking ? "#a5b4fc" : "#4f46e5",
                        color: "#fff",
                        cursor: qualityChecking ? "not-allowed" : "pointer",
                        fontWeight: "bold",
                        fontSize: "0.9rem",
                      }}
                    >
                      {qualityChecking ? "בודק..." : "הרץ בדיקות איכות"}
                    </button>
                    {qualityError && (
                      <div style={{ marginTop: "0.4rem", color: "#b91c1c", fontSize: "0.85rem" }}>{qualityError}</div>
                    )}
                  </div>
                )}

                {qualityResult && !activationResult && (
                  <div style={{ marginTop: "0.6rem" }}>
                    <div style={{
                      padding: "0.5rem 0.75rem",
                      background: qualityResult.overall_passed ? "#dcfce7" : "#fef2f2",
                      border: `1px solid ${qualityResult.overall_passed ? "#86efac" : "#fca5a5"}`,
                      borderRadius: "4px",
                      fontSize: "0.85rem",
                      color: qualityResult.overall_passed ? "#14532d" : "#b91c1c",
                      marginBottom: "0.5rem",
                    }}>
                      <strong>{qualityResult.overall_passed ? "בדיקות איכות עברו ✓" : "בדיקות איכות נכשלו ✗"}</strong>
                      <ul style={{ margin: "0.3rem 0 0", paddingRight: "1.2rem", fontSize: "0.8rem" }}>
                        {qualityResult.checks.map((c) => (
                          <li key={c.name} style={{ color: c.passed ? "#166534" : "#b91c1c" }}>
                            {c.passed ? "✓" : "✗"} {c.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                    {qualityResult.overall_passed && (
                      <div>
                        <div style={{ background: "#fffbeb", border: "1px solid #f59e0b", borderRadius: "4px", padding: "0.4rem 0.75rem", fontSize: "0.82rem", color: "#92400e", marginBottom: "0.4rem" }}>
                          <strong>אזהרה:</strong> פרסום האינדקס יהפוך אותו למקור הפעיל לתשובות הצ׳אט. יש לוודא שהתוכן מאושר.
                        </div>
                        <button
                          type="button"
                          onClick={() => handleActivate(qualityResult.index_version_id)}
                          disabled={activating}
                          style={{
                            padding: "0.4rem 1rem",
                            borderRadius: "4px",
                            border: "none",
                            background: activating ? "#fca5a5" : "#dc2626",
                            color: "#fff",
                            cursor: activating ? "not-allowed" : "pointer",
                            fontWeight: "bold",
                            fontSize: "0.9rem",
                          }}
                        >
                          {activating ? "מפעיל..." : "פרסם אינדקס פעיל"}
                        </button>
                        {activationError && (
                          <div style={{ marginTop: "0.4rem", color: "#b91c1c", fontSize: "0.85rem" }}>{activationError}</div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {activationResult && (
                  <div style={{ marginTop: "0.6rem", padding: "0.5rem 0.75rem", background: "#dcfce7", border: "1px solid #86efac", borderRadius: "4px", fontSize: "0.85rem", color: "#14532d" }}>
                    <strong>האינדקס פורסם בהצלחה</strong> — {activationResult.message}
                  </div>
                )}
              </div>
            )}

            <button
              type="submit"
              disabled={uploading}
              style={{
                width: "100%",
                padding: "0.65rem",
                fontSize: "1rem",
                borderRadius: "4px",
                border: "none",
                background: uploading ? "#93c5fd" : "#2563eb",
                color: "#fff",
                cursor: uploading ? "not-allowed" : "pointer",
                fontWeight: "bold",
              }}
            >
              {uploading ? "מעלה..." : "העלה מסמך"}
            </button>
          </form>
        </div>

        <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.8rem", color: "#9ca3af" }}>
          נגיש רק למשתמשים עם הרשאת <code>knowledge_admin</code> או <code>system_admin</code>
        </p>
      </main>
    </div>
  );
}
