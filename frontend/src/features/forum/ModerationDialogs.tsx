/** FlagModal and CloseModal - report a post to the moderators; close a question (as a duplicate, off topic or resolved). */
import React, { useEffect, useState } from 'react';
import { Input, Modal, Radio, Select, message } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useT } from '../../i18n/hooks';
import { forumApi, forumErrorMessage, ForumPost } from './forumApi';

const { TextArea } = Input;

interface FlagProps {
  post: ForumPost | null;
  onClose: () => void;
  onDone: () => void;
}

export const FlagModal: React.FC<FlagProps> = ({ post, onClose, onDone }) => {
  const t = useT();
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (post) setReason(''); }, [post]);
  if (!post) return null;
  const send = async () => {
    setSaving(true);
    try {
      await forumApi.flag(post.id, reason.trim());
      message.success(t('forum.flagSent'));
      onDone();
      onClose();
    } catch (e) {
      message.error(forumErrorMessage(e, t('forum.actionFailed')));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal open title={t('forum.flagTitle')} onCancel={onClose} onOk={send} okText={t('forum.flag')} confirmLoading={saving}
      okButtonProps={{ disabled: reason.trim().length < 5 }} cancelText={t('common.cancel')}>
      <p className="mt-0 text-sm text-gray-600">{t('forum.flagHint')}</p>
      <TextArea rows={3} value={reason} maxLength={300} showCount onChange={(e) => setReason(e.target.value)} placeholder={t('forum.flagReasonPlaceholder')} aria-label={t('forum.flagReason')} />
    </Modal>
  );
};

interface CloseProps {
  question: ForumPost | null;
  onClose: () => void;
  onDone: () => void;
}

export const CloseModal: React.FC<CloseProps> = ({ question, onClose, onDone }) => {
  const t = useT();
  const [reason, setReason] = useState<'duplicate' | 'off_topic' | 'resolved'>('duplicate');
  const [search, setSearch] = useState('');
  const [original, setOriginal] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (question) { setReason('duplicate'); setSearch(''); setOriginal(undefined); } }, [question]);
  const found = useQuery({
    queryKey: ['forum', 'closeSearch', search],
    queryFn: () => forumApi.list({ q: search, match: 'any', per_page: 8 }),
    enabled: !!question && reason === 'duplicate' && search.trim().length >= 3,
  });
  if (!question) return null;
  const options = (found.data?.items ?? []).filter((q) => q.id !== question.id && !q.closed).map((q) => ({ value: q.id, label: q.title ?? q.id }));
  const send = async () => {
    setSaving(true);
    try {
      await forumApi.close(question.id, reason, reason === 'duplicate' ? original : undefined);
      onDone();
      onClose();
    } catch (e) {
      message.error(forumErrorMessage(e, t('forum.actionFailed')));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal open title={t('forum.closeTitle')} onCancel={onClose} onOk={send} okText={t('forum.close')} confirmLoading={saving}
      okButtonProps={{ disabled: reason === 'duplicate' && !original }} cancelText={t('common.cancel')}>
      <p className="mt-0 text-sm text-gray-600">{t('forum.closeHint')}</p>
      <Radio.Group value={reason} onChange={(e) => setReason(e.target.value)} className="flex flex-col gap-1">
        <Radio value="duplicate">{t('forum.reasonDuplicate')}</Radio>
        <Radio value="off_topic">{t('forum.reasonOffTopic')}</Radio>
        <Radio value="resolved">{t('forum.reasonResolved')}</Radio>
      </Radio.Group>
      {reason === 'duplicate' && (
        <Select showSearch className="w-full mt-3" filterOption={false} value={original} onSearch={setSearch} onChange={setOriginal}
          options={options} placeholder={t('forum.searchOriginal')} notFoundContent={search.trim().length < 3 ? t('forum.typeToSearch') : t('forum.noMatches')} />
      )}
    </Modal>
  );
};
