"use client";

import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AnswerBlock,
  ApiError,
  CitationResponse,
  ContextType,
  ConversationResponse,
  MessageResponse,
  createConversation,
  getConversation,
  getMe,
  listConversations,
  sendMessage,
  submitFeedback,
} from "@/lib/api";

const CONTEXT_LABELS: Record<ContextType, string> = {
  government_ministries: "משרדי ממשלה",
  defense_system: "מערכת הביטחון",
  health_system: "מערכת הבריאות",
};

const ALL_ROLES = [
  "chat_user",
  "faq_manager",
  "user_admin",
  "feedback_reviewer",
  "knowledge_admin",
  "system_admin",
];

interface DisplayMessage {
  id: string;
  role: string;
  content: string;
  sources: CitationResponse[];
  answer_blocks?: AnswerBlock[];
  has_sufficient_sources?: boolean;
}

interface FeedbackState {
  rating: "positive" | "negative";
  comment: string;
  submitted: boolean;
  showComment: boolean;
}

function _unwrapDetail(raw: unknown): Record<string, unknown> | string | null {
  if (typeof raw === "string") return raw;
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    if ("detail" in r) return r.detail as Record<string, unknown> | string;
    return r;
  }
  return null;
}

function safeErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) return "__redirect_login__";
    if (err.status === 422) {
      const d = _unwrapDetail(err.detail);
      if (typeof d === "object" && d !== null) {
        if (d.error === "privacy_guard_blocked") {
          return 'אין להזין פרטים אישיים או מזהים של עובדים. נא לנסח את השאלה באופן כללי, ללא מספר זהות, שם מלא, כתובת דוא"ל, טלפון, כתובת, פרטי בריאות או פרטי משמעת.';
        }
        if (d.error === "guardrail_blocked" && d.public_message) {
          return String(d.public_message);
        }
      }
      return "הבקשה אינה תקינה. אנא נסה שנית.";
    }
    if (err.status === 503) {
      return "אין מידע זמין כרגע. אנא נסה מאוחר יותר.";
    }
    if (err.status === 404) {
      return "המשאב המבוקש לא נמצא.";
    }
  }
  return "שגיאה בחיבור לשרת. אנא נסה שנית.";
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("he-IL", {
      day: "numeric",
      month: "short",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

export default function ChatPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [token, setToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState("");
  const [userRoles, setUserRoles] = useState<string[]>([]);
  const [context, setContext] = useState<ContextType>("government_ministries");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, FeedbackState>>({});
  const [conversations, setConversations] = useState<ConversationResponse[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingConv, setLoadingConv] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  function handleAuthError() {
    if (typeof window !== "undefined") {
      localStorage.removeItem("chathr_token");
    }
    router.push("/login");
  }

  async function loadConversationList(t: string) {
    setLoadingHistory(true);
    try {
      const list = await listConversations(t);
      setConversations(list);
    } catch (err) {
      const msg = safeErrorMessage(err);
      if (msg === "__redirect_login__") handleAuthError();
    } finally {
      setLoadingHistory(false);
    }
  }

  useEffect(() => {
    if (typeof window === "undefined") return;
    const t = localStorage.getItem("chathr_token");
    if (!t) {
      router.push("/login");
      return;
    }
    setToken(t);
    getMe(t)
      .then((me) => { setUserEmail(me.email); setUserRoles(me.roles); })
      .catch((err) => {
        const msg = safeErrorMessage(err);
        if (msg === "__redirect_login__") handleAuthError();
        else setError("לא ניתן לטעון פרטי משתמש.");
      });
    loadConversationList(t).then(() => {
      const convIdFromUrl = searchParams.get("conversationId");
      if (convIdFromUrl) {
        setConversationId(convIdFromUrl);
        setLoadingConv(true);
        getConversation(t, convIdFromUrl)
          .then((detail) => {
            setContext(detail.context_type as ContextType);
            setMessages(detail.messages.map((m) => ({
              id: m.id,
              role: m.role,
              content: m.content,
              sources: [],
            })));
          })
          .catch((err) => {
            const msg = safeErrorMessage(err);
            if (msg === "__redirect_login__") handleAuthError();
            else setError("לא ניתן לטעון שיחה. אנא נסה שוב.");
          })
          .finally(() => setLoadingConv(false));
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  function logout() {
    if (typeof window !== "undefined") {
      localStorage.removeItem("chathr_token");
    }
    router.push("/login");
  }

  async function handleNewConversation() {
    if (!token) return;
    setError(null);
    setMessages([]);
    setFeedback({});
    setConversationId(null);
    try {
      const conv = await createConversation(token, context);
      setConversationId(conv.id);
      setConversations((prev) => [conv, ...prev]);
    } catch (err) {
      const msg = safeErrorMessage(err);
      if (msg === "__redirect_login__") handleAuthError();
      else setError("לא ניתן ליצור שיחה חדשה. אנא נסה שוב.");
    }
  }

  async function handleOpenConversation(conv: ConversationResponse) {
    if (!token) return;
    setError(null);
    setConversationId(conv.id);
    setContext(conv.context_type as ContextType);
    setMessages([]);
    setFeedback({});
    setLoadingConv(true);
    try {
      const detail = await getConversation(token, conv.id);
      const displayMsgs: DisplayMessage[] = detail.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        sources: [],
      }));
      setMessages(displayMsgs);
    } catch (err) {
      const msg = safeErrorMessage(err);
      if (msg === "__redirect_login__") handleAuthError();
      else setError("לא ניתן לטעון שיחה. אנא נסה שוב.");
    } finally {
      setLoadingConv(false);
    }
  }

  async function handleSend(e?: FormEvent) {
    e?.preventDefault();
    if (!token || !conversationId || !input.trim() || sending) return;

    const content = input.trim();
    setInput("");
    setSending(true);
    setError(null);

    const tempId = `temp-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: tempId, role: "user", content, sources: [] },
    ]);

    try {
      const data = await sendMessage(token, conversationId, content);
      setMessages((prev) => {
        const withoutTemp = prev.filter((m) => m.id !== tempId);
        return [
          ...withoutTemp,
          { id: `u-${data.message.id}`, role: "user", content, sources: [] },
          {
            id: data.message.id,
            role: "assistant",
            content: data.message.content,
            sources: data.sources,
            answer_blocks: data.answer_blocks ?? [],
            has_sufficient_sources: data.has_sufficient_sources,
          },
        ];
      });
      // Refresh conversation list to update timestamps
      loadConversationList(token);
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      const msg = safeErrorMessage(err);
      if (msg === "__redirect_login__") handleAuthError();
      else setError(msg);
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function startFeedback(msgId: string, rating: "positive" | "negative") {
    setFeedback((prev) => ({
      ...prev,
      [msgId]: { rating, comment: "", submitted: false, showComment: true },
    }));
  }

  async function submitFeedbackForMessage(msgId: string) {
    if (!token) return;
    const fb = feedback[msgId];
    if (!fb) return;
    try {
      await submitFeedback(token, msgId, fb.rating, fb.comment || undefined);
      setFeedback((prev) => ({
        ...prev,
        [msgId]: { ...fb, submitted: true, showComment: false },
      }));
    } catch {
      setError("לא ניתן לשמור משוב. אנא נסה שנית.");
    }
  }

  const hasRole = (role: string) => userRoles.includes(role);
  const isKnowledgeAdmin = hasRole("knowledge_admin") || hasRole("system_admin");
  const isFaqManager = hasRole("faq_manager") || hasRole("system_admin");
  const isUserAdmin = hasRole("user_admin") || hasRole("system_admin");
  const isFeedbackReviewer = hasRole("feedback_reviewer") || hasRole("system_admin");
  const isSystemAdmin = hasRole("system_admin");

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {/* Header */}
      <header
        style={{
          background: "#1e3a5f",
          color: "#fff",
          padding: "0.6rem 1rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
          gap: "0.5rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            title={sidebarOpen ? "סגור סרגל צד" : "פתח סרגל צד"}
            style={{
              background: "transparent",
              border: "none",
              color: "#fff",
              fontSize: "1.2rem",
              cursor: "pointer",
              padding: "0.1rem 0.3rem",
            }}
          >
            ☰
          </button>
          <span style={{ fontWeight: "bold", fontSize: "1.1rem" }}>ChatHR</span>
        </div>

        {/* Role-based nav links */}
        <nav style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {isKnowledgeAdmin && (
            <button onClick={() => router.push("/admin/knowledge/upload")} style={navBtnStyle}>
              טעינת מסמך
            </button>
          )}
          {isKnowledgeAdmin && (
            <button onClick={() => router.push("/admin/knowledge-sources")} style={navBtnStyle}>
              מקורות ידע
            </button>
          )}
          {isKnowledgeAdmin && (
            <button onClick={() => router.push("/admin/index-versions")} style={navBtnStyle}>
              גרסאות אינדקס
            </button>
          )}
          {isFaqManager && (
            <button onClick={() => router.push("/admin/faq")} style={navBtnStyle}>
              ניהול FAQ
            </button>
          )}
          {isFeedbackReviewer && (
            <button onClick={() => router.push("/admin/feedback")} style={navBtnStyle}>
              משוב
            </button>
          )}
          {isUserAdmin && (
            <button onClick={() => router.push("/admin/users")} style={navBtnStyle}>
              משתמשים
            </button>
          )}
          {isSystemAdmin && (
            <button onClick={() => router.push("/admin/audit-logs")} style={navBtnStyle}>
              לוג ביקורת
            </button>
          )}
        </nav>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {userEmail && (
            <span style={{ fontSize: "0.82rem", opacity: 0.85 }}>{userEmail}</span>
          )}
          <button
            onClick={logout}
            style={{
              background: "transparent",
              border: "1px solid rgba(255,255,255,0.45)",
              color: "#fff",
              padding: "0.25rem 0.7rem",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.88rem",
            }}
          >
            יציאה
          </button>
        </div>
      </header>

      {/* Body row */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Sidebar: conversation history */}
        {sidebarOpen && (
          <aside
            style={{
              width: "220px",
              minWidth: "180px",
              background: "#f8fafc",
              borderLeft: "1px solid #dde3ed",
              display: "flex",
              flexDirection: "column",
              flexShrink: 0,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "0.6rem 0.75rem",
                borderBottom: "1px solid #dde3ed",
                fontWeight: "bold",
                fontSize: "0.85rem",
                color: "#374151",
              }}
            >
              שיחות
            </div>

            {/* Context + New conversation */}
            <div style={{ padding: "0.5rem 0.6rem", borderBottom: "1px solid #eef0f3" }}>
              <select
                value={context}
                onChange={(e) => setContext(e.target.value as ContextType)}
                disabled={!!conversationId}
                style={{
                  width: "100%",
                  padding: "0.25rem 0.4rem",
                  borderRadius: "4px",
                  border: "1px solid #ccc",
                  fontSize: "0.8rem",
                  marginBottom: "0.4rem",
                  background: conversationId ? "#e5e7eb" : "#fff",
                }}
              >
                {(Object.entries(CONTEXT_LABELS) as [ContextType, string][]).map(
                  ([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ),
                )}
              </select>
              <button
                onClick={handleNewConversation}
                style={{
                  width: "100%",
                  padding: "0.3rem",
                  borderRadius: "4px",
                  border: "none",
                  background: "#2563eb",
                  color: "#fff",
                  cursor: "pointer",
                  fontWeight: "bold",
                  fontSize: "0.82rem",
                }}
              >
                + שיחה חדשה
              </button>
            </div>

            {/* Conversation list */}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {loadingHistory ? (
                <div style={{ padding: "0.75rem", color: "#6b7280", fontSize: "0.8rem" }}>
                  טוען...
                </div>
              ) : conversations.length === 0 ? (
                <div style={{ padding: "0.75rem", color: "#9ca3af", fontSize: "0.8rem" }}>
                  אין שיחות קודמות
                </div>
              ) : (
                conversations.map((conv) => {
                  const isActive = conv.id === conversationId;
                  return (
                    <button
                      key={conv.id}
                      onClick={() => handleOpenConversation(conv)}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "right",
                        padding: "0.5rem 0.75rem",
                        border: "none",
                        borderBottom: "1px solid #eef0f3",
                        background: isActive ? "#dbeafe" : "transparent",
                        cursor: "pointer",
                        fontSize: "0.8rem",
                        lineHeight: 1.4,
                      }}
                    >
                      <div
                        style={{
                          fontWeight: isActive ? "bold" : "normal",
                          color: "#1e3a5f",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {conv.title || "שיחה חדשה"}
                      </div>
                      <div style={{ color: "#9ca3af", fontSize: "0.7rem", display: "flex", justifyContent: "space-between" }}>
                        <span>{CONTEXT_LABELS[conv.context_type as ContextType] ?? conv.context_type}</span>
                        <span>{formatDate(conv.created_at)}</span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </aside>
        )}

        {/* Main chat area */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Messages area */}
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "1rem 1.5rem",
              display: "flex",
              flexDirection: "column",
              gap: "1rem",
            }}
          >
            {!conversationId && (
              <div
                style={{
                  textAlign: "center",
                  color: "#6b7280",
                  marginTop: "4rem",
                }}
              >
                <p style={{ fontSize: "1.05rem" }}>
                  בחר הקשר ולחץ <strong>+ שיחה חדשה</strong> בסרגל הצד, או פתח שיחה קיימת.
                </p>
              </div>
            )}

            {loadingConv && (
              <div style={{ textAlign: "center", color: "#6b7280", marginTop: "2rem" }}>
                טוען שיחה...
              </div>
            )}

            {error && (
              <div
                style={{
                  background: "#fef2f2",
                  border: "1px solid #fca5a5",
                  borderRadius: "6px",
                  padding: "0.65rem 1rem",
                  color: "#b91c1c",
                  fontSize: "0.9rem",
                }}
              >
                {error}
              </div>
            )}

            {messages.map((msg, i) => {
              const isUser = msg.role === "user";
              const fb = feedback[msg.id];
              const isAssistantWithFeedback = !isUser && !msg.id.startsWith("u-");

              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: isUser ? "flex-start" : "flex-end",
                  }}
                >
                  <span style={{ fontSize: "0.75rem", color: "#6b7280", marginBottom: "0.2rem" }}>
                    {isUser ? "אתה" : "ChatHR"}
                  </span>

                  <div
                    style={{
                      maxWidth: "72%",
                      padding: "0.7rem 1rem",
                      borderRadius: "12px",
                      lineHeight: 1.6,
                      background: isUser ? "#dbeafe" : "#f0fdf4",
                      border: isUser ? "1px solid #93c5fd" : "1px solid #86efac",
                    }}
                  >
                    {!isUser && msg.answer_blocks && msg.answer_blocks.length > 0 ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                        {msg.answer_blocks.map((block) => {
                          const blockCitations = msg.sources.filter((s) =>
                            block.citation_ids.includes(s.chunk_id)
                          );
                          return (
                            <div key={block.block_id}>
                              <span style={{ whiteSpace: "pre-wrap" }}>{block.text}</span>
                              {blockCitations.length > 0 && msg.has_sufficient_sources !== false && (
                                <span style={{ display: "inline-flex", gap: "0.3rem", flexWrap: "wrap", marginRight: "0.4rem" }}>
                                  {blockCitations.map((s) => (
                                    <button
                                      key={s.chunk_id}
                                      onClick={() => {
                                        const params = new URLSearchParams();
                                        if (conversationId) params.set("conversationId", conversationId);
                                        params.set("messageId", msg.id);
                                        router.push(`/sources/${s.chunk_id}?${params.toString()}`);
                                      }}
                                      title={s.source_title ?? s.knowledge_source_name}
                                      style={{
                                        background: "#dbeafe",
                                        border: "1px solid #93c5fd",
                                        borderRadius: "4px",
                                        color: "#1d4ed8",
                                        fontSize: "0.72rem",
                                        cursor: "pointer",
                                        padding: "0.05rem 0.35rem",
                                        textDecoration: "none",
                                        lineHeight: 1.4,
                                      }}
                                    >
                                      {s.knowledge_source_name}
                                    </button>
                                  ))}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <span style={{ whiteSpace: "pre-wrap" }}>{msg.content}</span>
                    )}
                  </div>

                  {/* Sources — hidden when answer is a no-source refusal */}
                  {!isUser && msg.sources.length > 0 && msg.has_sufficient_sources !== false && (
                    <div style={{ marginTop: "0.5rem", alignSelf: "flex-end", maxWidth: "72%" }}>
                      <span style={{ fontSize: "0.78rem", color: "#374151", fontWeight: "bold" }}>
                        מקורות:
                      </span>
                      <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", marginTop: "0.25rem" }}>
                        {msg.sources.map((src, si) => (
                          <div
                            key={si}
                            style={{
                              background: "#fff",
                              border: "1px solid #d1d5db",
                              borderRadius: "6px",
                              padding: "0.4rem 0.75rem",
                              fontSize: "0.83rem",
                            }}
                          >
                            <strong>{src.knowledge_source_name}</strong>
                            {src.source_title && <span> — {src.source_title}</span>}
                            {src.section_title && (
                              <span style={{ color: "#6b7280" }}> ({src.section_title})</span>
                            )}
                            {src.page_number != null && (
                              <span style={{ color: "#6b7280" }}>, עמ׳ {src.page_number}</span>
                            )}
                            {src.chunk_id && (
                              <button
                                onClick={() => {
                                const params = new URLSearchParams();
                                if (conversationId) params.set("conversationId", conversationId);
                                params.set("messageId", msg.id);
                                router.push(`/sources/${src.chunk_id}?${params.toString()}`);
                              }}
                                style={{
                                  marginRight: "0.5rem",
                                  background: "transparent",
                                  border: "none",
                                  color: "#2563eb",
                                  fontSize: "0.8rem",
                                  cursor: "pointer",
                                  padding: 0,
                                  textDecoration: "underline",
                                }}
                              >
                                צפה במקור
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Feedback */}
                  {isAssistantWithFeedback && (
                    <div style={{ marginTop: "0.35rem", alignSelf: "flex-end" }}>
                      {fb?.submitted ? (
                        <span style={{ fontSize: "0.8rem", color: "#16a34a" }}>✓ תודה על המשוב!</span>
                      ) : fb?.showComment ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", maxWidth: "320px" }}>
                          <textarea
                            value={fb.comment}
                            onChange={(e) =>
                              setFeedback((prev) => ({
                                ...prev,
                                [msg.id]: { ...fb, comment: e.target.value },
                              }))
                            }
                            placeholder="הערה אופציונלית"
                            rows={2}
                            style={{
                              padding: "0.4rem",
                              borderRadius: "4px",
                              border: "1px solid #ccc",
                              resize: "vertical",
                              fontSize: "0.88rem",
                            }}
                          />
                          <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
                            <button
                              onClick={() =>
                                setFeedback((prev) => {
                                  const { [msg.id]: _, ...rest } = prev;
                                  return rest;
                                })
                              }
                              style={{
                                padding: "0.25rem 0.6rem",
                                borderRadius: "4px",
                                border: "1px solid #ccc",
                                background: "#fff",
                                cursor: "pointer",
                                fontSize: "0.85rem",
                              }}
                            >
                              ביטול
                            </button>
                            <button
                              onClick={() => submitFeedbackForMessage(msg.id)}
                              style={{
                                padding: "0.25rem 0.75rem",
                                borderRadius: "4px",
                                border: "none",
                                background: "#16a34a",
                                color: "#fff",
                                cursor: "pointer",
                                fontSize: "0.85rem",
                              }}
                            >
                              שלח
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ display: "flex", gap: "0.4rem" }}>
                          <button
                            onClick={() => startFeedback(msg.id, "positive")}
                            title="תגובה חיובית"
                            style={{ border: "none", background: "transparent", fontSize: "1.1rem", cursor: "pointer", padding: "0.1rem 0.3rem" }}
                          >
                            👍
                          </button>
                          <button
                            onClick={() => startFeedback(msg.id, "negative")}
                            title="תגובה שלילית"
                            style={{ border: "none", background: "transparent", fontSize: "1.1rem", cursor: "pointer", padding: "0.1rem 0.3rem" }}
                          >
                            👎
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {sending && (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div
                  style={{
                    padding: "0.6rem 1rem",
                    background: "#f0fdf4",
                    border: "1px solid #86efac",
                    borderRadius: "12px",
                    color: "#6b7280",
                    fontSize: "0.9rem",
                  }}
                >
                  ⏳ מעבד...
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input area */}
          <div
            style={{
              background: "#f0f4f8",
              padding: "0.75rem 1.5rem",
              borderTop: "1px solid #dde3ed",
              flexShrink: 0,
            }}
          >
            <p
              style={{
                fontSize: "0.75rem",
                color: "#6b7280",
                margin: "0 0 0.4rem 0",
                lineHeight: 1.4,
              }}
            >
              נא לא להזין פרטים מזהים, טקסט פוגעני או שאלות שאינן בתחום משאבי אנוש בשירות המדינה.
              המענה מבוסס רק על מקורות רשמיים שאונדקסו במערכת.
            </p>
            <form
              onSubmit={handleSend}
              style={{ display: "flex", gap: "0.75rem", alignItems: "flex-end" }}
            >
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  conversationId
                    ? "הקלד שאלה... (Enter לשליחה, Shift+Enter לשורה חדשה)"
                    : "צור שיחה חדשה כדי להתחיל"
                }
                disabled={!conversationId || sending}
                rows={2}
                style={{
                  flex: 1,
                  padding: "0.5rem 0.75rem",
                  borderRadius: "6px",
                  border: "1px solid #ccc",
                  resize: "none",
                  fontSize: "1rem",
                  lineHeight: 1.5,
                  background: !conversationId ? "#e5e7eb" : "#fff",
                }}
              />
              <button
                type="submit"
                disabled={!conversationId || !input.trim() || sending}
                style={{
                  padding: "0.5rem 1.25rem",
                  borderRadius: "6px",
                  border: "none",
                  background: !conversationId || !input.trim() || sending ? "#93c5fd" : "#2563eb",
                  color: "#fff",
                  cursor: !conversationId || !input.trim() || sending ? "not-allowed" : "pointer",
                  fontWeight: "bold",
                  fontSize: "1rem",
                  height: "fit-content",
                }}
              >
                שלח
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

const navBtnStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid rgba(255,255,255,0.35)",
  color: "#fff",
  padding: "0.2rem 0.6rem",
  borderRadius: "4px",
  cursor: "pointer",
  fontSize: "0.8rem",
  whiteSpace: "nowrap",
};
