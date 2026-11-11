/** EditPostModal - edit a post. A question can also change its title and tags; every edit is kept in the history, with the reason given here. */
import React, { useEffect, useState } from 'react';
import { Input, Modal, Select, message } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useT } from '../../i18n/hooks';
import { forumApi, forumErrorMessage, ForumPost } from './forumApi';

const { TextArea } = Input;

interface Props {
  post: ForumPost | null;
  onClose: () => void;
  onSaved: () => void;
}

const EditPostModal: React.FC<Props> = ({ post, onClose, onSaved }) => {
  const t = useT();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [summary, setSummary] = useState('');
  const [saving, setSaving] = useState(false);
  const known = useQuery({ queryKey: ['forum', 'tags'], queryFn: () => forumApi.tags(), staleTime: 5 * 60_000, enabled: post?.kind === 'question' });

  useEffect(() => {
    if (!post) return;
    setTitle(post.title ?? '');
    setBody(post.body_md);
    setTags(post.tags);
    setSummary('');
  }, [post]);

  if (!post) return null;
  const isQuestion = post.kind === 'question';
  const minBody = post.kind === 'comment' ? 5 : 30;
  const valid = body.trim().length >= minBody && (!isQuestion || (title.trim().length >= 15 && tags.length >= 1 && tags.length <= 5));

  const save = async () => {
    setSaving(true);
    try {
      await forumApi.edit(post.id, {
        body: body.trim(),
        ...(isQuestion ? { title: title.trim(), tags } : {}),
        summary: summary.trim() || undefined,
      });
      onSaved();
      onClose();
    } catch (e) {
      message.error(forumErrorMessage(e, t('forum.actionFailed')));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open title={t('forum.edit')} onCancel={onClose} okText={t('common.save')} okButtonProps={{ disabled: !valid, loading: saving }} onOk={save} width={720}>
      <div className="flex flex-col gap-3">
        {isQuestion && (
          <>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} showCount placeholder={t('forum.titlePlaceholder')} />
            <Select mode="tags" value={tags} onChange={(v) => setTags(v.map((x) => x.toLowerCase()))} maxCount={5} tokenSeparators={[',', ' ']}
              options={known.data?.map((x) => ({ value: x.name, label: x.name }))} placeholder={t('forum.tagsPlaceholder')} />
          </>
        )}
        <TextArea rows={10} value={body} onChange={(e) => setBody(e.target.value)} maxLength={20000} />
        <Input value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={300} placeholder={t('forum.editSummaryPlaceholder')} />
      </div>
    </Modal>
  );
};

export default EditPostModal;
