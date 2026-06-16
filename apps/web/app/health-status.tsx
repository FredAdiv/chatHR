"use client";

import { useEffect, useState } from "react";

type Health = { status: string; service?: string };

export function HealthStatus() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    fetch(`${apiUrl}/health`)
      .then((r) => r.json())
      .then((data: Health) => setHealth(data))
      .catch(() => setHealth({ status: "unreachable" }));
  }, []);

  if (!health) return <p style={{ color: "#888" }}>בודק חיבור ל-API...</p>;

  const color = health.status === "ok" ? "#2a7a2a" : "#c0392b";
  return (
    <p>
      סטטוס API:{" "}
      <strong style={{ color }}>
        {health.status}
        {health.service ? ` — ${health.service}` : ""}
      </strong>
      {health.status === "unreachable" && (
        <span style={{ color: "#888", fontSize: "0.9em" }}>
          {" "}
          (הפעל את השירות עם <code>docker compose up --build</code>)
        </span>
      )}
    </p>
  );
}
