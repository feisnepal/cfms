/** ForumProfilePage - a member's public profile (/forum/users/:id) and, for the signed-in member, their reputation and how it came about (/forum/me). */
import React from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { Alert, Empty, Spin, Table, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { useT } from '../../i18n/hooks';
import { forumApi, ForumReputationEvent } from './forumApi';

const PRIVILEGES = ['vote_up', 'flag', 'comment', 'upload', 'create_tag', 'vote_down', 'edit_others', 'close_others'] as const;

const Stat: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="bg-white rounded-lg shadow-sm p-4 text-center min-w-[7rem]">
    <div className="text-2xl font-semibold">{value}</div>
    <div className="text-xs text-gray-500 capitalize">{label}</div>
  </div>
);

const ForumProfilePage: React.FC<{ self?: boolean }> = ({ self }) => {
  const t = useT();
  const params = useParams();
  const { user, isLoading: authLoading } = useAuth();
  const userId = self ? user?.id : params.id;
  const profile = useQuery({ queryKey: ['forum', 'profile', userId], queryFn: () => forumApi.profile(userId as string), enabled: !!userId, retry: false });
  const mine = !!user && userId === user.id;
  const me = useQuery({ queryKey: ['forum', 'me'], queryFn: forumApi.me, enabled: mine });
  const events = useQuery({ queryKey: ['forum', 'myReputation'], queryFn: forumApi.myReputation, enabled: mine });

  if (self && authLoading) return <div className="py-10 text-center"><Spin /></div>;
  if (self && !user) return <Navigate to={`/login?next=${encodeURIComponent('/forum/me')}`} replace />;
  if (profile.isLoading) return <div className="py-10 text-center"><Spin /></div>;
  if (profile.isError || !profile.data) return <Alert type="warning" showIcon title={t('forum.notFound')} />;
  const p = profile.data;

  const eventLabel = (e: ForumReputationEvent) => {
    const base = t(`forum.event.${e.action_type ?? 'other'}`);
    return e.by_cancel ? t('forum.event.undone', { what: base }) : base;
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold mt-0 flex flex-wrap items-center gap-2">
        {p.name} {p.is_moderator && <Tag color="green" className="m-0">{t('forum.moderator')}</Tag>}
      </h1>
      <div className="text-sm text-gray-500 mb-4">{t('forum.memberSince', { date: new Date(p.member_since).toLocaleDateString() })}</div>
      <div className="flex flex-wrap gap-3 mb-6">
        <Stat label={t('forum.reputation')} value={p.reputation} />
        <Stat label={t('forum.questionsLabel')} value={p.questions} />
        <Stat label={t('forum.answers')} value={p.answers} />
        <Stat label={t('forum.acceptedAnswers')} value={p.accepted_answers} />
      </div>

      {mine && me.data && (
        <section className="bg-white rounded-lg shadow-sm p-4 mb-6">
          <h2 className="text-lg font-semibold mt-0">{t('forum.whatYouCanDo')}</h2>
          <ul className="list-none p-0 m-0 divide-y divide-gray-100">
            {PRIVILEGES.map((k) => (
              <li key={k} className="py-2 flex flex-wrap items-center justify-between gap-2">
                <span>{t(`forum.privilege.${k}`)}</span>
                {me.data.can[k]
                  ? <Tag color="green" className="m-0">{t('forum.allowed')}</Tag>
                  : <Tag className="m-0">{t('forum.needsReputation', { count: me.data.thresholds[k] })}</Tag>}
              </li>
            ))}
          </ul>
          {me.data.votes_left_today !== null && <div className="text-sm text-gray-600 mt-3">{t('forum.votesLeft', { count: me.data.votes_left_today })}</div>}
        </section>
      )}

      {mine && (
        <section>
          <h2 className="text-lg font-semibold">{t('forum.reputationHistory')}</h2>
          {events.isLoading && <Spin />}
          {events.data?.length === 0 && <Empty description={t('forum.noReputationYet')} />}
          {!!events.data?.length && (
            <Table<ForumReputationEvent & { key: number }> size="small" rowKey="key" pagination={{ pageSize: 20, hideOnSinglePage: true }} dataSource={events.data.map((e, key) => ({ ...e, key }))}
              columns={[
                { title: t('forum.date'), dataIndex: 'created_at', width: 170, render: (v: string) => new Date(v).toLocaleString() },
                { title: t('forum.points'), dataIndex: 'value', width: 80, render: (v: number) => <span className={v >= 0 ? 'text-green-700' : 'text-red-700'}>{v > 0 ? `+${v}` : v}</span> },
                { title: t('forum.reason'), render: (_: unknown, e) => eventLabel(e) },
                { title: t('forum.questionLabel'), render: (_: unknown, e) => (e.question_id ? <Link to={`/forum/q/${e.question_id}`}>{e.question_title}</Link> : null) },
              ]} />
          )}
        </section>
      )}
    </div>
  );
};

export default ForumProfilePage;
