/** ForumAskPage - the ask form. Needs an account; the workflow step can arrive in the address (?step=). */
import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Button, Input, Select, Upload, message } from 'antd';
import type { UploadFile } from 'antd';
import { PictureOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { useT } from '../../i18n/hooks';
import { findContext } from '../../components/calculation/calcContexts';
import { forumApi, forumErrorMessage } from './forumApi';
import { tagForStep } from './stepTags';
import { resetStepCounts } from './useStepCounts';

const { TextArea } = Input;

const ForumAskPage: React.FC = () => {
  const t = useT();
  const navigate = useNavigate();
  const { user } = useAuth();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const step = params.get('step') ?? undefined;
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [tags, setTags] = useState<string[]>(() => {
    const fromStep = tagForStep(params.get('step'));
    return fromStep ? [fromStep] : [];
  });
  const [similarFor, setSimilarFor] = useState('');
  const [files, setFiles] = useState<UploadFile[]>([]);
  // a question already asked is better than a new one: look for similar titles once the person has typed enough, and wait for a pause in typing
  useEffect(() => {
    const text = title.trim();
    if (text.length < 12) {
      setSimilarFor('');
      return;
    }
    const timer = window.setTimeout(() => setSimilarFor(text), 600);
    return () => window.clearTimeout(timer);
  }, [title]);
  const similar = useQuery({
    queryKey: ['forum', 'similar', similarFor],
    queryFn: () => forumApi.list({ q: similarFor, match: 'any', per_page: 5 }),
    enabled: similarFor.length >= 12,
    staleTime: 60_000,
  });
  const known = useQuery({ queryKey: ['forum', 'tags'], queryFn: () => forumApi.tags(), staleTime: 5 * 60_000 });

  const ask = useMutation({
    mutationFn: async () => {
      const post = await forumApi.ask({ title: title.trim(), body: body.trim(), tags, workflow_step: step });
      // the question exists now; each picture is a separate upload, and one that fails must not lose the question
      let failed = 0;
      for (const f of files) {
        try {
          if (f.originFileObj) await forumApi.attach(post.id, f.originFileObj);
        } catch {
          failed += 1;
        }
      }
      if (failed) message.warning(t('forum.somePicturesFailed', { count: failed }));
      return post;
    },
    onSuccess: (post) => {
      client.invalidateQueries({ queryKey: ['forum'] });
      resetStepCounts();
      navigate(`/forum/q/${post.id}`);
    },
    onError: (e) => message.error(forumErrorMessage(e, t('forum.actionFailed'))),
  });

  if (!user) {
    return <Alert type="info" showIcon title={t('forum.signInToAsk')} description={<Link to={`/login?next=${encodeURIComponent('/forum/ask' + (step ? `?step=${step}` : ''))}`}>{t('forum.signIn')}</Link>} />;
  }

  const stepContext = step ? findContext(step) : null;
  const stepName = stepContext ? t(stepContext.item.labelKey) : step;
  const ready = title.trim().length >= 15 && body.trim().length >= 30 && tags.length >= 1 && tags.length <= 5;
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold mt-0">{t('forum.ask')}</h1>
      <Alert className="mb-4" type="warning" showIcon title={t('forum.privacyWarning')} />
      {step && <Alert className="mb-4" type="info" showIcon title={t('forum.askedFromStep', { step: stepName })} />}
      <div className="bg-white rounded-lg shadow-sm p-4 flex flex-col gap-4">
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t('forum.titleLabel')}</span>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} showCount placeholder={t('forum.titlePlaceholder')} />
          {!!similar.data?.items.length && (
            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
              <div className="font-medium mb-1">{t('forum.alreadyAsked')}</div>
              <ul className="list-none p-0 m-0 flex flex-col gap-1">
                {similar.data.items.map((q) => (
                  <li key={q.id}>
                    <Link to={`/forum/q/${q.id}`} target="_blank" className="text-green-800 hover:underline">{q.title}</Link>
                    <span className="text-xs text-gray-500"> · {q.answer_count} {t('forum.answers')}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t('forum.bodyLabel')}</span>
          <TextArea rows={10} value={body} onChange={(e) => setBody(e.target.value)} maxLength={20000} placeholder={t('forum.bodyPlaceholder')} />
          <span className="text-xs text-gray-500">{t('forum.markdownHint')}</span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t('forum.tagsLabel')}</span>
          <Select mode="tags" value={tags} onChange={(v) => setTags(v.map((x) => x.toLowerCase()))} maxCount={5} tokenSeparators={[',', ' ']}
            options={known.data?.map((x) => ({ value: x.name, label: x.name }))} placeholder={t('forum.tagsPlaceholder')} />
        </label>
        <div className="flex flex-col gap-1">
          <span className="font-medium">{t('forum.screenshots')}</span>
          <Upload accept="image/png,image/jpeg,image/webp" listType="picture" fileList={files} maxCount={4} multiple
            beforeUpload={(file) => {
              if (file.size > 5 * 1024 * 1024) {
                message.error(t('forum.pictureTooBig'));
                return Upload.LIST_IGNORE;
              }
              return false;
            }}
            onChange={({ fileList }) => setFiles(fileList)}>
            {files.length < 4 && <Button icon={<PictureOutlined />}>{t('forum.addPicture')}</Button>}
          </Upload>
          <span className="text-xs text-gray-500">{t('forum.screenshotsHint')}</span>
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={() => navigate('/forum')}>{t('common.cancel')}</Button>
          <Button type="primary" disabled={!ready} loading={ask.isPending} onClick={() => ask.mutate()}>{t('forum.postQuestion')}</Button>
        </div>
      </div>
    </div>
  );
};

export default ForumAskPage;
