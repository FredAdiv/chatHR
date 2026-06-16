import { HealthStatus } from "./health-status";

export default function HomePage() {
  return (
    <main style={{ padding: "2rem", maxWidth: "800px", margin: "0 auto" }}>
      <h1>ChatHR</h1>
      <p>מערכת צ'אט AI מאובטחת לעובדי HR בשירות המדינה ובמגזר הציבורי בישראל.</p>
      <p style={{ color: "#555" }}>
        A secure AI chat system for HR employees in Israeli government and civil service.
      </p>

      <section
        style={{
          marginTop: "2rem",
          padding: "1rem",
          border: "1px solid #ddd",
          borderRadius: "6px",
          background: "#f9f9f9",
        }}
      >
        <h2 style={{ marginTop: 0 }}>מצב מערכת</h2>
        <HealthStatus />
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>סטטוס MVP</h2>
        <p>זהו שלד ריצה ראשוני. התכונות הבאות טרם מומשו:</p>
        <ul>
          <li>אימות משתמשים</li>
          <li>ממשק צ'אט</li>
          <li>RAG (שאילתת מסמכים)</li>
          <li>ניהול FAQ</li>
        </ul>
      </section>
    </main>
  );
}
