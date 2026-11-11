/** Assistant access API (backend/app/api/chat.py): who may use the chat and how much of today's allowance is left. */
import api from '../../services/api';

export type ChatAccessStateName = 'none' | 'requested' | 'approved' | 'revoked' | 'expired' | 'switched_off' | 'not_eligible';

export interface ChatAccessState {
  state: ChatAccessStateName;
  allowed: boolean;
  daily_cap_tokens: number;
  tokens_used_today: number;
  tokens_left_today: number;
  approx_questions_left: number;
  expires_at: string | null;
  read_only: boolean;
}

export interface ChatAdminRow {
  user_id: string;
  email: string;
  full_name: string | null;
  role: string;
  status: 'requested' | 'approved' | 'revoked';
  daily_cap_tokens: number;
  requested_at: string;
  request_note: string | null;
  approved_at: string | null;
  expires_at: string | null;
  tokens_used_today: number;
  messages_today: number;
  thumbs_down_30d: number;
}

export interface ChatAdminSettings {
  enabled: boolean;
  pool_daily_tokens: number | null;
  pool_used_today: number;
}

export interface ChatReplyOut {
  session_id: string;
  message_id: string;
  reply: string;
  sources: string[];
  state: ChatAccessState;
}

const base = '/api/chat';

export const chatApi = {
  access: async (): Promise<ChatAccessState> => (await api.get(`${base}/access/me`)).data,
  send: async (message: string, sessionId: string | null, step?: string | null): Promise<ChatReplyOut> =>
    (await api.post(`${base}/messages`, { message, session_id: sessionId, step: step || null })).data,
  feedback: async (messageId: string, value: -1 | 0 | 1): Promise<void> => {
    await api.put(`${base}/messages/${messageId}/feedback`, { value });
  },
  adminList: async (): Promise<ChatAdminRow[]> => (await api.get(`${base}/admin/access`)).data,
  adminApprove: async (userId: string, cap?: number): Promise<void> => {
    await api.post(`${base}/admin/access/${userId}/approve`, cap === undefined ? {} : { daily_cap_tokens: cap });
  },
  adminRevoke: async (userId: string): Promise<void> => {
    await api.post(`${base}/admin/access/${userId}/revoke`);
  },
  adminSetCap: async (userId: string, cap: number): Promise<void> => {
    await api.put(`${base}/admin/access/${userId}/cap`, { daily_cap_tokens: cap });
  },
  adminSettings: async (): Promise<ChatAdminSettings> => (await api.get(`${base}/admin/settings`)).data,
  adminSaveSettings: async (enabled: boolean, pool: number | null): Promise<ChatAdminSettings> =>
    (await api.put(`${base}/admin/settings`, { enabled, pool_daily_tokens: pool })).data,
  requestAccess: async (note?: string): Promise<ChatAccessState> => (await api.post(`${base}/access/request`, { note: note || null })).data,
};

export function chatErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') return (detail as { message: string }).message;
  return fallback;
}
