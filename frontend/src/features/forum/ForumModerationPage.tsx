/** ForumModerationPage - the moderator's queue: reported posts and the new members' posts waiting to be let through. */
import React from 'react';
import { Link, Navigate } from 'react-router-dom';
import { Alert, Badge, Button, Empty, Modal, Spin, Tabs, Tag, message } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { useT } from '../../i18n/hooks';
import { forumApi, forumErrorMessage, ForumFlagged, ForumPost } from './forumApi';
import PostBody from './PostBody';
import ModeratorsPanel from './ModeratorsPanel';

const when = (iso: string) => new Date(iso).toLocaleString();

const ForumModerationPage: React.FC = () => {
  const t = useT();
  const { user, isLoading: authLoading } = useAuth();
  const client = useQueryClient();
  const me = useQuery({ queryKey: ['forum', 'me'], queryFn: forumApi.me, enabled: !!user });
  const allowed = !!me.data?.is_moderator;
  const flagged = useQuery({ queryKey: ['forum', 'flagged'], queryFn: forumApi.flagged, enabled: allowed });
  const held = useQuery({ queryKey: ['forum', 'held'], queryFn: forumApi.held, enabled: allowed });
  const run = useMutation({
    mutationFn: (job: () => Promise<unknown>) => job(),
    onSuccess: () => client.invalidateQueries({ queryKey: ['forum'] }),
    onError: (e) => message.error(forumErrorMessage(e, t('forum.actionFailed'))),
  });

  if (authLoading) return <div className="py-10 text-center"><Spin /></div>;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent('/forum/moderation')}`} replace />;
  if (me.isLoading) return <div className="py-10 text-center"><Spin /></div>;
  if (!allowed) return <Alert type="warning" showIcon title={t('forum.moderatorsOnly')} />;

  const where = (p: ForumPost, questionId: string) => `/forum/q/${questionId}${p.kind === 'question' ? '' : `#${p.id}`}`;

  const renderFlagged = (item: ForumFlagged) => {
    const p = item.post;
    return (
      <section key={p.id} className="bg-white rounded-lg shadow-sm p-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Tag color="red" className="m-0">{t('forum.flagCount', { count: item.flags.length })}</Tag>
          <Tag className="m-0">{t(`forum.kind.${p.kind}`)}</Tag>
          <Link to={where(p, item.question_id)} className="font-medium text-green-800 hover:underline">{item.question_title ?? t('forum.openPost')}</Link>
          <span className="text-xs text-gray-500">{p.author?.name ?? t('forum.formerMember')}</span>
        </div>
        <PostBody html={p.body_html} className="mt-2 text-sm max-h-48 overflow-auto" />
        <ul className="m-0 mt-2 pl-5 text-sm text-gray-700">
          {item.flags.map((f) => <li key={f.id}>{f.reason} <span className="text-xs text-gray-500">- {f.by ?? t('forum.formerMember')}, {when(f.created_at)}</span></li>)}
        </ul>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button onClick={() => run.mutate(() => forumApi.resolveFlags(p.id, 'dismissed'))} loading={run.isPending}>{t('forum.resolveDismiss')}</Button>
          <Button onClick={() => run.mutate(() => forumApi.resolveFlags(p.id, 'user_warned'))} loading={run.isPending}>{t('forum.resolveWarn')}</Button>
          <Button danger loading={run.isPending}
            onClick={() => Modal.confirm({ title: t('forum.resolveDeleteConfirm'), okText: t('forum.resolveDelete'), okButtonProps: { danger: true }, onOk: () => run.mutateAsync(() => forumApi.resolveFlags(p.id, 'deleted')) })}>
            {t('forum.resolveDelete')}
          </Button>
        </div>
        <div className="mt-1 text-xs text-gray-500">{t('forum.resolveHint')}</div>
      </section>
    );
  };

  const renderHeld = (p: ForumPost) => (
    <section key={p.id} className="bg-white rounded-lg shadow-sm p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Tag className="m-0">{t(`forum.kind.${p.kind}`)}</Tag>
        <Link to={where(p, p.root_id ?? p.id)} className="font-medium text-green-800 hover:underline">{p.title ?? t('forum.openPost')}</Link>
        <span className="text-xs text-gray-500">{p.author?.name ?? t('forum.formerMember')}, {when(p.created_at)}</span>
      </div>
      <PostBody html={p.body_html} className="mt-2 text-sm max-h-48 overflow-auto" />
      <div className="mt-3 flex gap-2">
        <Button type="primary" loading={run.isPending} onClick={() => run.mutate(() => forumApi.approve(p.id))}>{t('forum.approve')}</Button>
        <Button danger loading={run.isPending} onClick={() => run.mutate(() => forumApi.remove(p.id))}>{t('forum.delete')}</Button>
      </div>
    </section>
  );

  const list = <T,>(q: { isLoading: boolean; data?: T[] }, render: (x: T) => React.ReactNode, empty: string) =>
    q.isLoading ? <div className="py-6 text-center"><Spin /></div>
      : q.data && q.data.length > 0 ? <div className="flex flex-col gap-3">{q.data.map(render)}</div>
      : <Empty description={empty} />;

  return (
    <div>
      <h1 className="text-2xl font-semibold mt-0">{t('forum.moderation')}</h1>
      <Tabs items={[
        { key: 'flagged', label: <span>{t('forum.flaggedTab')} <Badge count={flagged.data?.length ?? 0} showZero={false} /></span>, children: list(flagged, renderFlagged, t('forum.noFlagged')) },
        { key: 'held', label: <span>{t('forum.heldTab')} <Badge count={held.data?.length ?? 0} showZero={false} /></span>, children: list(held, renderHeld, t('forum.noHeld')) },
        ...(user.role === 'super_admin' ? [{ key: 'moderators', label: t('forum.moderatorsTab'), children: <ModeratorsPanel /> }] : []),
      ]} />
    </div>
  );
};

export default ForumModerationPage;
