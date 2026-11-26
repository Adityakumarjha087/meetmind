import { API_PREFIX, API_URL } from "./config";
import type {
  ActionItem,
  ActionStatus,
  AskResponse,
  Citation,
  IntegrationStatus,
  MeetingDetail,
  MeetingPage,
  MeetingStatus,
  MeetingSummary,
  Member,
  ProgressEvent,
  PublicMeeting,
  Role,
  Segment,
  Speaker,
  TokenResponse,
  UsageReport,
  User,
  Workspace,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;
const listeners = new Set<(token: string | null) => void>();

export function setAccessToken(token: string | null) {
  accessToken = token;
  listeners.forEach((fn) => fn(token));
}

export function getAccessToken() {
  return accessToken;
}

export function onTokenChange(fn: (token: string | null) => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

async function parseError(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = res.statusText || `Request failed (${res.status})`;
  let details: unknown;
  try {
    const body = await res.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details;
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, code, message, details);
}

/** Exchange the httpOnly refresh cookie for a new access token (deduplicated across callers). */
export function refreshSession(): Promise<string | null> {
  refreshing ??= fetch(`${API_URL}${API_PREFIX}/auth/refresh`, { method: "POST", credentials: "include" })
    .then(async (res) => {
      if (!res.ok) {
        setAccessToken(null);
        return null;
      }
      const data = (await res.json()) as TokenResponse;
      setAccessToken(data.access_token);
      return data.access_token;
    })
    .catch(() => null)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  auth?: boolean;
  raw?: boolean;
}

export async function request<T>(path: string, opts: RequestOptions = {}, retry = true): Promise<T> {
  const { body, auth = true, raw = false, headers, ...rest } = opts;
  const h = new Headers(headers);
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    h.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }
  if (auth && accessToken) h.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(`${API_URL}${API_PREFIX}${path}`, { ...rest, headers: h, body: payload, credentials: "include" });
  if (res.status === 401 && auth && retry) {
    const token = await refreshSession();
    if (token) return request<T>(path, opts, false);
  }
  if (!res.ok) throw await parseError(res);
  if (raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  // auth
  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", { method: "POST", body: { email, password }, auth: false }),
  register: (name: string, email: string, password: string) =>
    request<TokenResponse>("/auth/register", { method: "POST", body: { name, email, password }, auth: false }),
  logout: () => request<void>("/auth/logout", { method: "POST", auth: false }),
  me: () => request<User>("/auth/me"),
  googleAuthorize: () => request<{ url: string }>("/auth/google/authorize", { auth: false }),
  googleLink: () => request<{ url: string }>("/auth/google/link"),

  // workspaces
  workspaces: () => request<Workspace[]>("/workspaces"),
  createWorkspace: (name: string) => request<Workspace>("/workspaces", { method: "POST", body: { name } }),
  updateWorkspace: (id: string, body: Partial<{ name: string; slack_webhook_url: string; slack_auto_post: boolean }>) =>
    request<Workspace>(`/workspaces/${id}`, { method: "PATCH", body }),
  members: (ws: string) => request<Member[]>(`/workspaces/${ws}/members`),
  addMember: (ws: string, email: string, role: Role) =>
    request<Member>(`/workspaces/${ws}/members`, { method: "POST", body: { email, role } }),
  updateMember: (ws: string, userId: string, role: Role) =>
    request<Member>(`/workspaces/${ws}/members/${userId}`, { method: "PATCH", body: { role } }),
  removeMember: (ws: string, userId: string) =>
    request<void>(`/workspaces/${ws}/members/${userId}`, { method: "DELETE" }),
  usage: (ws: string, days = 30) => request<UsageReport>(`/workspaces/${ws}/usage?days=${days}`),
  integrations: (ws: string) => request<IntegrationStatus>(`/workspaces/${ws}/integrations`),
  importCalendar: (ws: string, daysAhead = 14) =>
    request<{ imported: number; meetings: MeetingSummary[] }>(
      `/workspaces/${ws}/integrations/google-calendar/import`,
      { method: "POST", body: { days_ahead: daysAhead } },
    ),

  // meetings
  meetings: (ws: string, params: { q?: string; status?: MeetingStatus; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return request<MeetingPage>(`/workspaces/${ws}/meetings${qs.size ? `?${qs}` : ""}`);
  },
  uploadMeeting: (ws: string, form: FormData) =>
    request<MeetingDetail>(`/workspaces/${ws}/meetings`, { method: "POST", body: form }),
  attachAudio: (id: string, form: FormData) =>
    request<MeetingDetail>(`/meetings/${id}/audio`, { method: "POST", body: form }),
  meeting: (id: string) => request<MeetingDetail>(`/meetings/${id}`),
  updateMeeting: (id: string, title: string) => request<MeetingDetail>(`/meetings/${id}`, { method: "PATCH", body: { title } }),
  deleteMeeting: (id: string) => request<void>(`/meetings/${id}`, { method: "DELETE" }),
  reprocess: (id: string) => request<ProgressEvent>(`/meetings/${id}/reprocess`, { method: "POST" }),
  progress: (id: string) => request<ProgressEvent>(`/meetings/${id}/progress`),
  transcript: (id: string) => request<Segment[]>(`/meetings/${id}/transcript`),
  renameSpeaker: (id: string, speakerId: string, displayName: string) =>
    request<Speaker>(`/meetings/${id}/speakers/${speakerId}`, { method: "PATCH", body: { display_name: displayName } }),
  share: (id: string) => request<{ share_token: string; share_url: string }>(`/meetings/${id}/share`, { method: "POST" }),
  unshare: (id: string) => request<void>(`/meetings/${id}/share`, { method: "DELETE" }),
  postToSlack: (id: string) => request<{ posted: boolean }>(`/meetings/${id}/slack`, { method: "POST" }),
  exportMeeting: (id: string, format: "md" | "pdf") =>
    request<Response>(`/meetings/${id}/export?format=${format}`, { raw: true }),
  publicMeeting: (token: string) => request<PublicMeeting>(`/share/${enc(token)}`, { auth: false }),

  // action items
  actionItems: (ws: string, params: { status?: ActionStatus; meeting_id?: string; assignee?: string } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v && qs.set(k, v));
    return request<ActionItem[]>(`/workspaces/${ws}/action-items${qs.size ? `?${qs}` : ""}`);
  },
  createActionItem: (ws: string, body: Partial<ActionItem> & { title: string }) =>
    request<ActionItem>(`/workspaces/${ws}/action-items`, { method: "POST", body }),
  updateActionItem: (id: string, body: Partial<Omit<ActionItem, "id">>) =>
    request<ActionItem>(`/action-items/${id}`, { method: "PATCH", body }),
  deleteActionItem: (id: string) => request<void>(`/action-items/${id}`, { method: "DELETE" }),

  // RAG
  ask: (ws: string, question: string, meetingId?: string) =>
    request<AskResponse>(`/workspaces/${ws}/ask`, { method: "POST", body: { question, meeting_id: meetingId } }),
  search: (ws: string, q: string) => request<Citation[]>(`/workspaces/${ws}/search?q=${enc(q)}`),
};

export async function downloadExport(id: string, format: "md" | "pdf") {
  const res = await api.exportMeeting(id, format);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `meeting.${format}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
