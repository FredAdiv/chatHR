"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, MeResponse, getMe } from "@/lib/api";

interface Section {
  title: string;
  description: string;
  href: string;
  roles: string[];
  color: string;
}

const SECTIONS: Section[] = [
  {
    title: "מקורות ידע",
    description: "ניהול מקורות מידע רשמיים, רמות סמכות, הקשרים",
    href: "/admin/knowledge-sources",
    roles: ["knowledge_admin", "system_admin"],
    color: "#1e40af",
  },
  {
    title: "גרסאות אינדקס",
    description: "ניהול גרסאות אינדקס — הפעלה, ארכוב, שחזור",
    href: "/admin/index-versions",
    roles: ["knowledge_admin", "system_admin"],
    color: "#1e40af",
  },
  {
    title: "טעינת מסמך",
    description: "העלאה ידנית של מסמכים רשמיים למאגר הידע",
    href: "/admin/knowledge/upload",
    roles: ["knowledge_admin", "system_admin"],
    color: "#1e40af",
  },
  {
    title: "ניהול FAQ",
    description: "יצירה, עריכה, אישור וארכוב פריטי FAQ",
    href: "/admin/faq",
    roles: ["faq_manager", "system_admin"],
    color: "#065f46",
  },
  {
    title: "משוב משתמשים",
    description: "סקירת דירוגים והערות — ללא זיהוי משתמשים ברירת מחדל",
    href: "/admin/feedback",
    roles: ["feedback_reviewer", "system_admin"],
    color: "#92400e",
  },
  {
    title: "ניהול משתמשים",
    description: "יצירת משתמשים, שינוי תפקידים, ניטרול",
    href: "/admin/users",
    roles: ["user_admin", "system_admin"],
    color: "#581c87",
  },
  {
    title: "לוג ביקורת",
    description: "מעקב אחר פעולות מנהל במערכת",
    href: "/admin/audit-logs",
    roles: ["system_admin"],
    color: "#374151",
  },
];

const ROLE_LABELS: Record<string, string> = {
  chat_user: "משתמש צ׳אט",
  faq_manager: "מנהל FAQ",
  user_admin: "מנהל משתמשים",
  feedback_reviewer: "סוקר משוב",
  knowledge_admin: "מנהל ידע",
  system_admin: "מנהל מערכת",
};

function hasAccess(userRoles: string[], sectionRoles: string[]): boolean {
  return sectionRoles.some((r) => userRoles.includes(r));
}

export default function AdminDashboard() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = localStorage.getItem("chathr_token");
    if (!t) { router.push("/login"); return; }
    getMe(t)
      .then(setMe)
      .catch((e) => {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          localStorage.removeItem("chathr_token");
          router.push("/login");
        } else {
          setError("לא ניתן לטעון פרטי משתמש.");
        }
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!me) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "#6b7280" }}>
        {error || "טוען..."}
      </div>
    );
  }

  const visibleSections = SECTIONS.filter((s) => hasAccess(me.roles, s.roles));

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh", background: "#f8fafc" }}>
      <header style={{ background: "#1e3a5f", color: "#fff", padding: "0.6rem 1.5rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: "bold", fontSize: "1.15rem" }}>לוח בקרה — ChatHR Admin</span>
        <button
          onClick={() => router.push("/chat")}
          style={{ background: "transparent", border: "1px solid rgba(255,255,255,0.4)", color: "#fff", padding: "0.2rem 0.7rem", borderRadius: "4px", cursor: "pointer", fontSize: "0.82rem" }}
        >
          לצ׳אט
        </button>
      </header>

      <div style={{ padding: "1.5rem", flex: 1 }}>
        <div style={{ marginBottom: "1.5rem" }}>
          <div style={{ fontSize: "0.9rem", color: "#6b7280" }}>
            {me.display_name || me.email}
            {" · "}
            {me.roles.map((r) => ROLE_LABELS[r] || r).join(", ")}
          </div>
        </div>

        {visibleSections.length === 0 ? (
          <div style={{ color: "#9ca3af", marginTop: "2rem" }}>
            אין לך הרשאות ניהול. פנה למנהל המערכת.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "1rem" }}>
            {visibleSections.map((section) => (
              <button
                key={section.href}
                onClick={() => router.push(section.href)}
                style={{
                  background: "#fff",
                  border: `2px solid ${section.color}20`,
                  borderRadius: "10px",
                  padding: "1.25rem 1.25rem",
                  cursor: "pointer",
                  textAlign: "right",
                  boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
                  transition: "box-shadow 0.15s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.12)")}
                onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.06)")}
              >
                <div style={{ fontWeight: "bold", fontSize: "1rem", color: section.color, marginBottom: "0.4rem" }}>
                  {section.title}
                </div>
                <div style={{ fontSize: "0.83rem", color: "#6b7280", lineHeight: 1.5 }}>
                  {section.description}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
