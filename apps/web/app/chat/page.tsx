"use client";

import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  CitationResponse,
  ContextType,
  MessageResponse,
  createConversation,
  getMe,
  sendMessage,
  submitFeedback,
} from "@/lib/api";

const CONTEXT_LABELS: Record<ContextType, string> = {
  government_ministries: "משרדי ממשלה",
  defense_system: "מערכת הביטחון",
  health_system: "מערכת הבריאות",
};

interface DisplayMessage {
  id: string;
  role: string;
  content: string;
  sources: CitationResponse[];
}

interface FeedbackState {
  rating: "positive" | "negative";
  comment: string;
  submitted: boolean;
  showComment: boolean;
}

function safeErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) return "__redirect_login__";
    if (err.status === 422) {
      const d = err.detail as { error?: string } | string;
      if (typeof d === "object" && d?.error === "privacy_guard_blocked") {
        return "ההודעה נחסמה: נמצאו פרטים מזהים אישיים. הסר מידע אישי ונסה שנית.";
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

export default function ChatPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState("");
  const [context, setContext] = useState<ContextType>("government_ministries");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, FeedbackState>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  function handleAuthError() {
    if (typeof window !== "undefined") {
      localStorage.removeItem("chathr_token");
    }
    router.push("/login");
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
      .then((me) => setUserEmail(me.email))
      .catch((err) => {
        const msg = safeErrorMessage(err);
        if (msg === "__redirect_login__") handleAuthError();
        else setError("לא ניתן לטעון פרטי משתמש.");
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
    try {
      const conv = await createConversation(token, context);
      setConversationId(conv.id);
    } catch (err) {
      const msg = safeErrorMessage(err);
      if (msg === "__redirect_login__") handleAuthError();
      else setError("לא ניתן ליצור שיחה חדשה. אנא נסה שוב.");
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
          },
        ];
      });
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

  if (!token) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {/* Header */}
      <header
        style={{
          background: "#1e3a5f",
          color: "#fff",
          padding: "0.75rem 1.5rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: "bold", fontSize: "1.2rem" }}>ChatHR</span>
        {userEmail && (
          <span style={{ fontSize: "0.88rem", opacity: 0.85 }}>{userEmail}</span>
        )}
        <button
          onClick={logout}
          style={{
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.45)",
            color: "#fff",
            padding: "0.25rem 0.75rem",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "0.9rem",
          }}
        >
          יציאה
        </button>
      </header>

      {/* Toolbar */}
      <div
        style={{
          background: "#f0f4f8",
          padding: "0.6rem 1.5rem",
          display: "flex",
          alignItems: "center",
          gap: "1rem",
          flexShrink: 0,
          borderBottom: "1px solid #dde3ed",
        }}
      >
        <label style={{ fontWeight: "bold", fontSize: "0.9rem" }}>הקשר:</label>
        <select
          value={context}
          onChange={(e) => setContext(e.target.value as ContextType)}
          disabled={!!conversationId}
          style={{
            padding: "0.3rem 0.6rem",
            borderRadius: "4px",
            border: "1px solid #ccc",
            fontSize: "0.9rem",
            background: conversationId ? "#e5e7eb" : "#fff",
          }}
        >
          {(Object.entries(CONTEXT_LABELS) as [ContextType, string][]).map(
            ([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ),
          )}
        </select>

        <button
          onClick={handleNewConversation}
          style={{
            padding: "0.35rem 1rem",
            borderRadius: "4px",
            border: "none",
            background: "#2563eb",
            color: "#fff",
            cursor: "pointer",
            fontWeight: "bold",
            fontSize: "0.9rem",
          }}
        >
          שיחה חדשה
        </button>

        {conversationId && (
          <span style={{ fontSize: "0.78rem", color: "#6b7280" }}>
            שיחה פעילה · {CONTEXT_LABELS[context]}
          </span>
        )}
      </div>

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
              בחר הקשר ולחץ <strong>שיחה חדשה</strong> כדי להתחיל.
            </p>
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
          const isAssistantWithFeedback =
            !isUser && !msg.id.startsWith("u-");

          return (
            <div
              key={i}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: isUser ? "flex-start" : "flex-end",
              }}
            >
              {/* Role label */}
              <span
                style={{
                  fontSize: "0.75rem",
                  color: "#6b7280",
                  marginBottom: "0.2rem",
                }}
              >
                {isUser ? "אתה" : "ChatHR"}
              </span>

              {/* Bubble */}
              <div
                style={{
                  maxWidth: "72%",
                  padding: "0.7rem 1rem",
                  borderRadius: "12px",
                  lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                  background: isUser ? "#dbeafe" : "#f0fdf4",
                  border: isUser
                    ? "1px solid #93c5fd"
                    : "1px solid #86efac",
                }}
              >
                {msg.content}
              </div>

              {/* Sources (assistant only) */}
              {!isUser && msg.sources.length > 0 && (
                <div
                  style={{
                    marginTop: "0.5rem",
                    alignSelf: "flex-end",
                    maxWidth: "72%",
                  }}
                >
                  <span
                    style={{
                      fontSize: "0.78rem",
                      color: "#374151",
                      fontWeight: "bold",
                    }}
                  >
                    מקורות:
                  </span>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.3rem",
                      marginTop: "0.25rem",
                    }}
                  >
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
                        {src.source_title && (
                          <span> — {src.source_title}</span>
                        )}
                        {src.section_title && (
                          <span style={{ color: "#6b7280" }}>
                            {" "}
                            ({src.section_title})
                          </span>
                        )}
                        {src.page_number != null && (
                          <span style={{ color: "#6b7280" }}>
                            , עמ׳ {src.page_number}
                          </span>
                        )}
                        {src.source_url && (
                          <a
                            href={src.source_url}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                              marginRight: "0.5rem",
                              color: "#2563eb",
                              fontSize: "0.8rem",
                            }}
                          >
                            קישור
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Feedback (assistant only) */}
              {isAssistantWithFeedback && (
                <div
                  style={{
                    marginTop: "0.35rem",
                    alignSelf: "flex-end",
                  }}
                >
                  {fb?.submitted ? (
                    <span
                      style={{ fontSize: "0.8rem", color: "#16a34a" }}
                    >
                      ✓ תודה על המשוב!
                    </span>
                  ) : fb?.showComment ? (
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "0.4rem",
                        maxWidth: "320px",
                      }}
                    >
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
                      <div
                        style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}
                      >
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
                        style={{
                          border: "none",
                          background: "transparent",
                          fontSize: "1.1rem",
                          cursor: "pointer",
                          padding: "0.1rem 0.3rem",
                        }}
                      >
                        👍
                      </button>
                      <button
                        onClick={() => startFeedback(msg.id, "negative")}
                        title="תגובה שלילית"
                        style={{
                          border: "none",
                          background: "transparent",
                          fontSize: "1.1rem",
                          cursor: "pointer",
                          padding: "0.1rem 0.3rem",
                        }}
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
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
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
              background:
                !conversationId || !input.trim() || sending
                  ? "#93c5fd"
                  : "#2563eb",
              color: "#fff",
              cursor:
                !conversationId || !input.trim() || sending
                  ? "not-allowed"
                  : "pointer",
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
  );
}
