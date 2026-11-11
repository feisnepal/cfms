/** ForumSettingsPage - which forum emails a member gets, how often, and which tags they watch (/forum/settings). */
import React from 'react';
import { Navigate } from 'react-router-dom';
import { Alert, Radio, Select, Spin, Switch, message } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { useT } from '../../i18n/hooks';
import { forumApi, forumErrorMessage, ForumNotificationSettings } from './forumApi';

type Flag = 'on_answer_to_mine' | 'on_comment_reply' | 'on_accepted' | 'on_new_in_watched_tags';
const FLAGS: Flag[] = ['on_answer_to_mine', 'on_comment_reply', 'on_accepted', 'on_new_in_watched_tags'];

const ForumSettingsPage: React.FC = () => {
  const t = useT();
  const { user, isLoading: authLoading } = useAuth();
  const client = useQueryClient();
  const key = ['forum', 'notifications'];
  const settings = useQuery({ queryKey: key, queryFn: forumApi.notificationSettings, enabled: !!user });
  const tags = useQuery({ queryKey: ['forum', 'tags'], queryFn: () => forumApi.tags(), staleTime: 5 * 60_000, enabled: !!user });
  const save = useMutation({
    mutationFn: (change: Partial<ForumNotificationSettings>) => forumApi.setNotificationSettings(change),
    onSuccess: (data) => client.setQueryData(key, data),
    onError: (e) => message.error(forumErrorMessage(e, t('forum.actionFailed'))),
  });
  const watch = useMutation({
    mutationFn: (v: { name: string; on: boolean }) => forumApi.watchTag(v.name, v.on),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
    onError: (e) => message.error(forumErrorMessage(e, t('forum.actionFailed'))),
  });

  if (authLoading) return <div className="py-10 text-center"><Spin /></div>;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent('/forum/settings')}`} replace />;
  if (settings.isLoading || !settings.data) return <div className="py-10 text-center"><Spin /></div>;
  const s = settings.data;
  const off = !s.enabled;

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold mt-0">{t('forum.emailSettings')}</h1>
      <section className="bg-white rounded-lg shadow-sm p-4 flex flex-col gap-4">
        <label className="flex items-center justify-between gap-3">
          <span className="font-medium">{t('forum.emailsOn')}</span>
          <Switch checked={s.enabled} onChange={(v) => save.mutate({ enabled: v })} aria-label={t('forum.emailsOn')} />
        </label>
        {FLAGS.map((flag) => (
          <label key={flag} className={`flex items-center justify-between gap-3 ${off ? 'opacity-50' : ''}`}>
            <span>{t(`forum.notify.${flag}`)}</span>
            <Switch checked={s[flag]} disabled={off} onChange={(v) => save.mutate({ [flag]: v })} aria-label={t(`forum.notify.${flag}`)} />
          </label>
        ))}
        <div className={off ? 'opacity-50' : ''}>
          <div className="mb-1">{t('forum.howOften')}</div>
          <Radio.Group value={s.email_frequency} disabled={off} onChange={(e) => save.mutate({ email_frequency: e.target.value })}>
            <Radio value="immediate">{t('forum.freq.immediate')}</Radio>
            <Radio value="daily">{t('forum.freq.daily')}</Radio>
            <Radio value="weekly">{t('forum.freq.weekly')}</Radio>
            <Radio value="never">{t('forum.freq.never')}</Radio>
          </Radio.Group>
        </div>
      </section>
      <section className="bg-white rounded-lg shadow-sm p-4 mt-4">
        <h2 className="text-base font-semibold mt-0">{t('forum.watchedTags')}</h2>
        <p className="text-sm text-gray-600 mt-0">{t('forum.watchedTagsHint')}</p>
        <Select mode="multiple" className="w-full" value={s.watched_tags} loading={watch.isPending}
          options={(tags.data ?? []).map((tag) => ({ value: tag.name, label: tag.name }))}
          onSelect={(name: string) => watch.mutate({ name, on: true })} onDeselect={(name: string) => watch.mutate({ name, on: false })}
          placeholder={t('forum.watchedTagsPlaceholder')} />
        {s.watched_tags.length > 0 && !s.on_new_in_watched_tags && <Alert className="mt-3" type="info" showIcon title={t('forum.watchedTagsOff')} />}
      </section>
    </div>
  );
};

export default ForumSettingsPage;
