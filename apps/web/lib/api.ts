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

export interface ConversationDetailResponse {
  id: string;
  context_type: string;
  title: string | null;
  created_at: string;
  messages: MessageResponse[];
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

export interface ChunkViewResponse {
  chunk_id: string;
  source_document_id: string;
  knowledge_source_id: string;
  knowledge_source_name: string;
  authority_level: number;
  source_title: string | null;
  document_type: string | null;
  section_title: string | null;
  page_number: number | null;
  chunk_index: number;
  excerpt: string;
  // FAQ-specific fields (only present when document_type === 'faq')
  faq_id?: string | null;
  faq_question?: string | null;
  faq_answer_excerpt?: string | null;
  faq_topic?: string | null;
  faq_applicable_population?: string | null;
  faq_official_source_links?: string[] | null;
  faq_updated_at?: string | null;
}

// ── Admin: Feedback ───────────────────────────────────────────────────────────

export interface FeedbackItem {
  id: string;
  message_id: string;
  conversation_id: string | null;
  rating: string;
  comment: string | null;
  created_at: string;
}

export interface FeedbackListResponse {
  items: FeedbackItem[];
  total: number;
}

// ── Admin: Audit Logs ─────────────────────────────────────────────────────────

export interface AuditLogItem {
  id: string;
  actor_user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogItem[];
  total: number;
}

// ── Admin: FAQ ────────────────────────────────────────────────────────────────

export interface FaqItemResponse {
  id: string;
  question: string;
  answer: string;
  topic: string | null;
  context_type: string | null;
  applicable_population: string | null;
  official_source_links: string[];
  status: string;
  approved_by_user_id: string | null;
  content_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface FaqCreate {
  question: string;
  answer: string;
  topic?: string;
  context_type?: ContextType;
  applicable_population?: string;
  official_source_links?: string[];
}

export interface FaqUpdate {
  question?: string;
  answer?: string;
  topic?: string;
  context_type?: ContextType;
  applicable_population?: string;
  official_source_links?: string[];
}

// ── Admin: Knowledge Sources ──────────────────────────────────────────────────

export interface KnowledgeSourceResponse {
  id: string;
  name: string;
  source_type: string;
  url: string | null;
  authority_level: number;
  is_active: boolean;
  context_type: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface KnowledgeSourceCreate {
  name: string;
  source_type: string;
  url?: string;
  authority_level: number;
  is_active?: boolean;
  context_type?: ContextType;
}

// ── Admin: Index Versions ─────────────────────────────────────────────────────

export interface IndexVersionResponse {
  id: string;
  version_label: string;
  status: string;
  embedding_model: string;
  created_by_user_id: string | null;
  activated_by_user_id: string | null;
  created_at: string | null;
  activated_at: string | null;
  metadata_json: Record<string, unknown> | null;
}

// ── Admin: Users ──────────────────────────────────────────────────────────────

export interface AdminUserResponse {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  roles: string[];
  created_at: string | null;
}

export interface CreateUserRequest {
  email: string;
  display_name?: string;
  password: string;
  roles?: string[];
}

// ── Error ─────────────────────────────────────────────────────────────────────

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

function jsonHeaders(token: string): Record<string, string> {
  return { ...authHeaders(token), "Content-Type": "application/json" };
}

// ── Auth ──────────────────────────────────────────────────────────────────────

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

// ── Chat ──────────────────────────────────────────────────────────────────────

export async function createConversation(
  token: string,
  context_type: ContextType,
  title?: string,
): Promise<ConversationResponse> {
  return apiFetch<ConversationResponse>("/chat/conversations", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ context_type, title }),
  });
}

export async function listConversations(
  token: string,
): Promise<ConversationResponse[]> {
  return apiFetch<ConversationResponse[]>("/chat/conversations", {
    headers: authHeaders(token),
  });
}

export async function getConversation(
  token: string,
  conversationId: string,
): Promise<ConversationDetailResponse> {
  return apiFetch<ConversationDetailResponse>(
    `/chat/conversations/${conversationId}`,
    { headers: authHeaders(token) },
  );
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
      headers: jsonHeaders(token),
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
      headers: jsonHeaders(token),
      body: JSON.stringify({ rating, comment }),
    },
  );
}

export async function getChunk(
  token: string,
  chunkId: string,
): Promise<ChunkViewResponse> {
  return apiFetch<ChunkViewResponse>(`/knowledge/chunks/${chunkId}`, {
    headers: authHeaders(token),
  });
}

// ── Admin: Feedback ───────────────────────────────────────────────────────────

export async function listAdminFeedback(
  token: string,
  params?: { rating?: string; offset?: number; limit?: number },
): Promise<FeedbackListResponse> {
  const qs = new URLSearchParams();
  if (params?.rating) qs.set("rating", params.rating);
  if (params?.offset != null) qs.set("offset", String(params.offset));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const q = qs.toString() ? `?${qs}` : "";
  return apiFetch<FeedbackListResponse>(`/admin/feedback${q}`, {
    headers: authHeaders(token),
  });
}

// ── Admin: Audit Logs ─────────────────────────────────────────────────────────

export async function listAuditLogs(
  token: string,
  params?: { action?: string; actor_user_id?: string; offset?: number; limit?: number },
): Promise<AuditLogListResponse> {
  const qs = new URLSearchParams();
  if (params?.action) qs.set("action", params.action);
  if (params?.actor_user_id) qs.set("actor_user_id", params.actor_user_id);
  if (params?.offset != null) qs.set("offset", String(params.offset));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const q = qs.toString() ? `?${qs}` : "";
  return apiFetch<AuditLogListResponse>(`/admin/audit-logs${q}`, {
    headers: authHeaders(token),
  });
}

// ── Admin: FAQ ────────────────────────────────────────────────────────────────

export async function listFaq(
  token: string,
  params?: { status?: string; context_type?: string },
): Promise<FaqItemResponse[]> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.context_type) qs.set("context_type", params.context_type);
  const q = qs.toString() ? `?${qs}` : "";
  return apiFetch<FaqItemResponse[]>(`/admin/faq${q}`, {
    headers: authHeaders(token),
  });
}

export async function createFaq(
  token: string,
  data: FaqCreate,
): Promise<FaqItemResponse> {
  return apiFetch<FaqItemResponse>("/admin/faq", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(data),
  });
}

export async function updateFaq(
  token: string,
  faqId: string,
  data: FaqUpdate,
): Promise<FaqItemResponse> {
  return apiFetch<FaqItemResponse>(`/admin/faq/${faqId}`, {
    method: "PUT",
    headers: jsonHeaders(token),
    body: JSON.stringify(data),
  });
}

export async function approveFaq(
  token: string,
  faqId: string,
): Promise<FaqItemResponse> {
  return apiFetch<FaqItemResponse>(`/admin/faq/${faqId}/approve`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

export async function archiveFaq(
  token: string,
  faqId: string,
): Promise<FaqItemResponse> {
  return apiFetch<FaqItemResponse>(`/admin/faq/${faqId}/archive`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

// ── Admin: Knowledge Sources ──────────────────────────────────────────────────

export async function listKnowledgeSources(
  token: string,
): Promise<KnowledgeSourceResponse[]> {
  return apiFetch<KnowledgeSourceResponse[]>("/admin/knowledge-sources", {
    headers: authHeaders(token),
  });
}

export async function createKnowledgeSource(
  token: string,
  data: KnowledgeSourceCreate,
): Promise<KnowledgeSourceResponse> {
  return apiFetch<KnowledgeSourceResponse>("/admin/knowledge-sources", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(data),
  });
}

export async function updateKnowledgeSource(
  token: string,
  sourceId: string,
  data: Partial<KnowledgeSourceCreate>,
): Promise<KnowledgeSourceResponse> {
  return apiFetch<KnowledgeSourceResponse>(`/admin/knowledge-sources/${sourceId}`, {
    method: "PUT",
    headers: jsonHeaders(token),
    body: JSON.stringify(data),
  });
}

// ── Admin: Index Versions ─────────────────────────────────────────────────────

export async function listIndexVersions(
  token: string,
  statusFilter?: string,
): Promise<IndexVersionResponse[]> {
  const q = statusFilter ? `?status=${statusFilter}` : "";
  return apiFetch<IndexVersionResponse[]>(`/admin/index-versions${q}`, {
    headers: authHeaders(token),
  });
}

// ── Admin: Users ──────────────────────────────────────────────────────────────

export async function listUsers(
  token: string,
): Promise<AdminUserResponse[]> {
  return apiFetch<AdminUserResponse[]>("/admin/users", {
    headers: authHeaders(token),
  });
}

export async function createUser(
  token: string,
  data: CreateUserRequest,
): Promise<AdminUserResponse> {
  return apiFetch<AdminUserResponse>("/admin/users", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(data),
  });
}

export async function updateUserRoles(
  token: string,
  userId: string,
  roles: string[],
): Promise<AdminUserResponse> {
  return apiFetch<AdminUserResponse>(`/admin/users/${userId}`, {
    method: "PUT",
    headers: jsonHeaders(token),
    body: JSON.stringify({ roles }),
  });
}

export async function deactivateUser(
  token: string,
  userId: string,
): Promise<AdminUserResponse> {
  return apiFetch<AdminUserResponse>(`/admin/users/${userId}`, {
    method: "PATCH",
    headers: authHeaders(token),
  });
}
