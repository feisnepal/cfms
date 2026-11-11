/** Community Q&A forum API (backend/app/api/forum.py). Reading is public; writes need a signed-in account. */
import api from '../../services/api';

export type ForumSort = 'active' | 'newest' | 'votes' | 'unanswered';

export interface ForumAuthor {
  id: string;
  name: string;
  reputation: number;
}

export interface ForumPost {
  id: string;
  kind: 'question' | 'answer' | 'comment';
  parent_id: string | null;
  root_id: string | null;
  title: string | null;
  body_md: string;
  /** Rendered and escaped by the server; still passed through DOMPurify before it reaches the page. */
  body_html: string;
  author: ForumAuthor | null;
  score: number;
  answer_count: number;
  comment_count: number;
  view_count: number;
  tags: string[];
  workflow_step: string | null;
  accepted: boolean;
  closed: boolean;
  closed_reason: 'duplicate' | 'off_topic' | 'resolved' | null;
  /** the question this one duplicates, when closed as a duplicate */
  duplicate_of: { id: string; title: string | null } | null;
  /** open flags; only a moderator is told */
  flag_count: number;
  /** the viewer has a live flag on it */
  my_flag: boolean;
  pending_review: boolean;
  deleted: boolean;
  created_at: string;
  last_activity_at: string;
  my_vote: 'up' | 'down' | null;
  can_edit: boolean;
  can_delete: boolean;
  attachments: ForumAttachment[];
}

export interface ForumAttachment {
  id: string;
  width: number;
  height: number;
  file_name: string;
  /** false: only the uploader and moderators can see it until a moderator approves it */
  approved: boolean;
}

export interface ForumFlagged {
  post: ForumPost;
  question_id: string;
  question_title: string | null;
  flags: { id: string; reason: string | null; by: string | null; created_at: string }[];
}

export interface ForumMember {
  id: string;
  name: string;
  email: string;
  is_moderator: boolean;
}

export interface ForumNotificationSettings {
  enabled: boolean;
  on_answer_to_mine: boolean;
  on_comment_reply: boolean;
  on_accepted: boolean;
  on_new_in_watched_tags: boolean;
  email_frequency: 'immediate' | 'daily' | 'weekly' | 'never';
  watched_tags: string[];
}

export interface ForumStepCount {
  questions: number;
  unanswered: number;
}

export interface ForumList {
  items: ForumPost[];
  total: number;
  page: number;
  per_page: number;
}

export interface ForumThread {
  question: ForumPost;
  answers: ForumPost[];
  comments: Record<string, ForumPost[]>;
  related: ForumPost[];
  /** the signed-in viewer follows this question */
  following: boolean;
}

export interface ForumTag {
  name: string;
  description_md: string | null;
  used_count: number;
}

export interface ForumMe {
  id: string;
  name: string;
  reputation: number;
  is_moderator: boolean;
  /** the reputation each privilege needs: vote_up, vote_down, flag, comment, create_tag, edit_others, close_others, upload */
  thresholds: Record<string, number>;
  /** what this member may do now (a moderator may do everything) */
  can: Record<string, boolean>;
  /** null for a moderator: no cap */
  votes_left_today: number | null;
}

export interface ForumReputationEvent {
  value: number;
  by_cancel: boolean;
  created_at: string;
  action_type: string | null;
  post_kind: string | null;
  question_id: string | null;
  question_title: string | null;
}

export interface ForumProfile {
  id: string;
  name: string;
  reputation: number;
  is_moderator: boolean;
  member_since: string;
  questions: number;
  answers: number;
  accepted_answers: number;
}

export interface ForumRevision {
  revision: number;
  title: string | null;
  body_md: string;
  body_html: string;
  tag_names: string | null;
  summary: string | null;
  author_name: string | null;
  revised_at: string;
}

export interface ForumListParams {
  sort?: ForumSort;
  tag?: string;
  q?: string;
  /** 'any': a question with any of the meaningful words matches, best match first (for "already asked?"). Default 'all'. */
  match?: 'all' | 'any';
  mine?: boolean;
  step?: string;
  page?: number;
  per_page?: number;
}

const base = '/api/forum';

export const forumApi = {
  list: async (params: ForumListParams): Promise<ForumList> => (await api.get(`${base}/questions`, { params })).data,
  thread: async (id: string): Promise<ForumThread> => (await api.get(`${base}/questions/${id}`)).data,
  steps: async (): Promise<Record<string, ForumStepCount>> => (await api.get(`${base}/steps`)).data,
  tags: async (q?: string): Promise<ForumTag[]> => (await api.get(`${base}/tags`, { params: q ? { q } : undefined })).data,
  me: async (): Promise<ForumMe> => (await api.get(`${base}/me`)).data,
  ask: async (body: { title: string; body: string; tags: string[]; workflow_step?: string }): Promise<ForumPost> =>
    (await api.post(`${base}/questions`, body)).data,
  answer: async (questionId: string, body: string): Promise<ForumPost> => (await api.post(`${base}/questions/${questionId}/answers`, { body })).data,
  comment: async (postId: string, body: string): Promise<ForumPost> => (await api.post(`${base}/posts/${postId}/comments`, { body })).data,
  vote: async (postId: string, direction: 'up' | 'down' | 'none'): Promise<ForumPost> => (await api.post(`${base}/posts/${postId}/vote`, { direction })).data,
  accept: async (answerId: string): Promise<ForumPost> => (await api.post(`${base}/answers/${answerId}/accept`)).data,
  edit: async (postId: string, body: { body?: string; title?: string; tags?: string[]; summary?: string }): Promise<ForumPost> =>
    (await api.patch(`${base}/posts/${postId}`, body)).data,
  remove: async (postId: string): Promise<ForumPost> => (await api.delete(`${base}/posts/${postId}`)).data,
  restore: async (postId: string): Promise<ForumPost> => (await api.post(`${base}/posts/${postId}/restore`)).data,
  approve: async (postId: string): Promise<ForumPost> => (await api.post(`${base}/posts/${postId}/approve`)).data,
  attach: async (postId: string, file: File): Promise<ForumPost> => {
    const form = new FormData();
    form.append('file', file);
    return (await api.post(`${base}/posts/${postId}/attachments`, form)).data;
  },
  removeAttachment: async (id: string): Promise<ForumPost> => (await api.delete(`${base}/attachments/${id}`)).data,
  approveAttachment: async (id: string): Promise<ForumPost> => (await api.post(`${base}/attachments/${id}/approve`)).data,
  attachmentUrl: (id: string): string => `${base}/attachments/${id}`,
  /** An unapproved picture is visible to its uploader only, and an <img> cannot send the login: fetch it as a blob. */
  attachmentBlob: async (id: string): Promise<Blob> => (await api.get(`${base}/attachments/${id}`, { responseType: 'blob' })).data,
  myReputation: async (): Promise<ForumReputationEvent[]> => (await api.get(`${base}/me/reputation`)).data,
  profile: async (userId: string): Promise<ForumProfile> => (await api.get(`${base}/users/${userId}`)).data,
  revisions: async (postId: string): Promise<ForumRevision[]> => (await api.get(`${base}/posts/${postId}/revisions`)).data,
  held: async (): Promise<ForumPost[]> => (await api.get(`${base}/moderation/held`)).data,
  flag: async (postId: string, reason: string): Promise<ForumPost> => (await api.post(`${base}/posts/${postId}/flag`, { reason })).data,
  flagged: async (): Promise<ForumFlagged[]> => (await api.get(`${base}/moderation/flagged`)).data,
  resolveFlags: async (postId: string, resolution: 'dismissed' | 'user_warned' | 'deleted'): Promise<ForumPost> =>
    (await api.post(`${base}/moderation/posts/${postId}/resolve`, { resolution })).data,
  close: async (questionId: string, reason: string, duplicateOf?: string): Promise<ForumPost> =>
    (await api.post(`${base}/questions/${questionId}/close`, { reason, duplicate_of: duplicateOf })).data,
  members: async (params: { q?: string; moderators_only?: boolean }): Promise<ForumMember[]> => (await api.get(`${base}/moderation/members`, { params })).data,
  setModerator: async (userId: string, isModerator: boolean): Promise<ForumMember> =>
    (await api.put(`${base}/moderation/moderators/${userId}`, { is_moderator: isModerator })).data,
  notificationSettings: async (): Promise<ForumNotificationSettings> => (await api.get(`${base}/me/notifications`)).data,
  setNotificationSettings: async (change: Partial<Omit<ForumNotificationSettings, 'watched_tags'>>): Promise<ForumNotificationSettings> =>
    (await api.put(`${base}/me/notifications`, change)).data,
  watchTag: async (name: string, following: boolean): Promise<{ following: boolean }> =>
    (await api.put(`${base}/me/tags/${encodeURIComponent(name)}`, { following })).data,
  follow: async (questionId: string, following: boolean): Promise<{ following: boolean }> =>
    (await api.put(`${base}/questions/${questionId}/following`, { following })).data,
  reopen: async (questionId: string): Promise<ForumPost> => (await api.post(`${base}/questions/${questionId}/reopen`)).data,
};

/** The server's plain-English reason for a refused action (`detail.message`), or a fallback. */
export function forumErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message: unknown }).message === 'string') {
    return (detail as { message: string }).message;
  }
  return fallback;
}
