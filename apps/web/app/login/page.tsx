"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem("chathr_token")) {
      router.replace("/chat");
    }
  }, [router]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await login(email, password);
      localStorage.setItem("chathr_token", data.access_token);
      router.push("/chat");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("שם משתמש או סיסמה שגויים.");
      } else {
        setError("שגיאה בהתחברות. אנא נסה שוב.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        background: "#f0f4f8",
      }}
    >
      <div
        style={{
          background: "#fff",
          padding: "2rem",
          borderRadius: "8px",
          boxShadow: "0 2px 12px rgba(0,0,0,0.1)",
          width: "100%",
          maxWidth: "380px",
        }}
      >
        <h1
          style={{
            marginTop: 0,
            marginBottom: "1.5rem",
            textAlign: "center",
            color: "#1e3a5f",
          }}
        >
          ChatHR — כניסה
        </h1>

        {error && (
          <div
            style={{
              background: "#fef2f2",
              border: "1px solid #fca5a5",
              borderRadius: "6px",
              padding: "0.6rem 1rem",
              color: "#b91c1c",
              marginBottom: "1rem",
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div style={{ marginBottom: "1rem" }}>
            <label
              htmlFor="email"
              style={{ display: "block", marginBottom: "0.3rem", fontWeight: "bold" }}
            >
              כתובת דוא&quot;ל
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                boxSizing: "border-box",
                fontSize: "1rem",
                borderRadius: "4px",
                border: "1px solid #ccc",
              }}
            />
          </div>

          <div style={{ marginBottom: "1.5rem" }}>
            <label
              htmlFor="password"
              style={{ display: "block", marginBottom: "0.3rem", fontWeight: "bold" }}
            >
              סיסמה
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                boxSizing: "border-box",
                fontSize: "1rem",
                borderRadius: "4px",
                border: "1px solid #ccc",
              }}
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "0.65rem",
              fontSize: "1rem",
              borderRadius: "4px",
              border: "none",
              background: loading ? "#93c5fd" : "#2563eb",
              color: "#fff",
              cursor: loading ? "not-allowed" : "pointer",
              fontWeight: "bold",
            }}
          >
            {loading ? "מתחבר..." : "כניסה"}
          </button>
        </form>
      </div>
    </main>
  );
}
