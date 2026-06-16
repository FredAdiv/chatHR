"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("chathr_token")
        : null;
    router.replace(token ? "/chat" : "/login");
  }, [router]);

  return null;
}
