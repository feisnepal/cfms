/** ModeratorsPanel - a super admin picks who moderates the forum: search a member, make them a moderator, or take the role back. */
import React, { useState } from 'react';
import { Button, Empty, Input, Spin, Tag, message } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useT } from '../../i18n/hooks';
import { forumApi, forumErrorMessage, ForumMember } from './forumApi';

const ModeratorsPanel: React.FC = () => {
  const t = useT();
  const client = useQueryClient();
  const [term, setTerm] = useState('');
  const current = useQuery({ queryKey: ['forum', 'moderators'], queryFn: () => forumApi.members({ moderators_only: true }) });
  const found = useQuery({ queryKey: ['forum', 'memberSearch', term], queryFn: () => forumApi.members({ q: term }), enabled: term.trim().length >= 2 });
  const change = useMutation({
    mutationFn: (v: { id: string; on: boolean }) => forumApi.setModerator(v.id, v.on),
    onSuccess: () => client.invalidateQueries({ queryKey: ['forum'] }),
    onError: (e) => message.error(forumErrorMessage(e, t('forum.actionFailed'))),
  });

  const row = (m: ForumMember) => (
    <li key={m.id} className="flex items-center justify-between gap-3 py-2 border-b border-gray-100 last:border-0">
      <span className="min-w-0 break-words">
        {m.name} <span className="text-xs text-gray-500">{m.email}</span> {m.is_moderator && <Tag color="green" className="m-0 ml-1">{t('forum.moderatorBadge')}</Tag>}
      </span>
      <Button size="small" danger={m.is_moderator} loading={change.isPending && change.variables?.id === m.id}
        onClick={() => change.mutate({ id: m.id, on: !m.is_moderator })}>
        {m.is_moderator ? t('forum.removeModerator') : t('forum.makeModerator')}
      </Button>
    </li>
  );

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <section className="bg-white rounded-lg shadow-sm p-4">
        <h2 className="text-base font-semibold mt-0">{t('forum.currentModerators')}</h2>
        {current.isLoading ? <Spin /> : current.data && current.data.length > 0
          ? <ul className="list-none p-0 m-0">{current.data.map(row)}</ul>
          : <Empty description={t('forum.noModerators')} />}
        <p className="text-xs text-gray-500 mb-0 mt-3">{t('forum.superAdminAlways')}</p>
      </section>
      <section className="bg-white rounded-lg shadow-sm p-4">
        <h2 className="text-base font-semibold mt-0">{t('forum.findMember')}</h2>
        <Input allowClear value={term} onChange={(e) => setTerm(e.target.value)} maxLength={60} placeholder={t('forum.findMemberPlaceholder')} aria-label={t('forum.findMember')} />
        <div className="mt-2">
          {term.trim().length < 2 ? null : found.isLoading ? <Spin />
            : found.data && found.data.length > 0 ? <ul className="list-none p-0 m-0">{found.data.map(row)}</ul>
            : <Empty description={t('forum.noMatches')} />}
        </div>
      </section>
    </div>
  );
};

export default ModeratorsPanel;
