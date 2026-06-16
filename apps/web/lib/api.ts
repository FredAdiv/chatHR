const getBase = (): string =>
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type ContextType =
  | "government_ministries"
  | "defense_system"
  | "health_system";

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface MeResponse {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  roles: string[];
}

export interface ConversationResponse {
  id: string;
  context_type: string;
  title: string | null;
  created_at: string;
}

export interface MessageResponse {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface CitationResponse {
  chunk_id: string;
  source_document_id: string;
  knowledge_source_id: string;
  knowledge_source_name: string;
  authority_level: number;
  source_title: string | null;
  source_url: string | null;
  section_title: string | null;
  page_number: number | null;
  document_type: string | null;
}

export interface SendMessageResponse {
  message: MessageResponse;
  sources: CitationResponse[];
  retrieval_count: number;
}

export interface FeedbackResponse {
  id: string;
  message_id: string;
  rating: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${getBase()}${path}`, options);
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export async function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  const body = new URLSearchParams({ username: email, password });
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
}

export async function getMe(token: string): Promise<MeResponse> {
  return apiFetch<MeResponse>("/auth/me", {
    headers: authHeaders(token),
  });
}

export async function createConversation(
  token: string,
  context_type: ContextType,
  title?: string,
): Promise<ConversationResponse> {
  return apiFetch<ConversationResponse>("/chat/conversations", {
    method: "POST",
    headers: {
      ...authHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ context_type, title }),
  });
}

export async function sendMessage(
  token: string,
  conversationId: string,
  content: string,
): Promise<SendMessageResponse> {
  return apiFetch<SendMessageResponse>(
    `/chat/conversations/${conversationId}/messages`,
    {
      method: "POST",
      headers: {
        ...authHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content }),
    },
  );
}

export async function submitFeedback(
  token: string,
  messageId: string,
  rating: "positive" | "negative",
  comment?: string,
): Promise<FeedbackResponse> {
  return apiFetch<FeedbackResponse>(
    `/chat/messages/${messageId}/feedback`,
    {
      method: "POST",
      headers: {
        ...authHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ rating, comment }),
    },
  );
}
