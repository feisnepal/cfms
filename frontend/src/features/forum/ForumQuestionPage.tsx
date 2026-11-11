/** ForumQuestionPage - one question with its answers and comments, votes, accepting, editing. Public to read. */
import React, { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Input, Modal, Spin, Tag, Tooltip, message } from 'antd';
import { CheckCircleFilled, CaretDownOutlined, CaretUpOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { useT } from '../../i18n/hooks';
import { findContext } from '../../components/calculation/calcContexts';
import { forumApi, forumErrorMessage, ForumPost } from './forumApi';
import PostBody from './PostBody';
import Attachments from './Attachments';
import EditPostModal from './EditPostModal';
import { CloseModal, FlagModal } from './ModerationDialogs';
import RevisionsDrawer from './RevisionsDrawer';
import { useDocumentMeta } from './useDocumentMeta';

const { TextArea } = Input;

const when = (iso: string) => new Date(iso).toLocaleString();

const ForumQuestionPage: React.FC = () => {
  const t = useT();
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const client = useQueryClient();
  const key = ['forum', 'thread', id];
  const thread = useQuery({ queryKey: key, queryFn: () => forumApi.thread(id), retry: false });
  const me = useQuery({ queryKey: ['forum', 'me'], queryFn: forumApi.me, enabled: !!user });
  const [answerText, setAnswerText] = useState('');
  const [editing, setEditing] = useState<ForumPost | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const [flagging, setFlagging] = useState<ForumPost | null>(null);
  const [closing, setClosing] = useState<ForumPost | null>(null);
  const [commentFor, setCommentFor] = useState<string | null>(null);
  const [commentText, setCommentText] = useState('');

  const refresh = () => client.invalidateQueries({ queryKey: ['forum'] });
  const fail = (e: unknown) => message.error(forumErrorMessage(e, t('forum.actionFailed')));
  const run = useMutation({
    mutationFn: (job: () => Promise<unknown>) => job(),
    onSuccess: refresh,
    onError: fail,
  });

  useDocumentMeta(thread.data ? `${thread.data.question.title} - ${t('forum.title')}` : undefined, thread.data ? `${window.location.origin}/forum/q/${id}` : undefined);

  if (thread.isLoading) return <div className="py-10 text-center"><Spin /></div>;
  if (thread.isError || !thread.data) return <Alert type="warning" showIcon title={t('forum.notFound')} description={<Link to="/forum">{t('forum.allQuestions')}</Link>} />;

  const { question, answers, comments, related, following } = thread.data;
  const needLogin = () => navigate(`/login?next=${encodeURIComponent(`/forum/q/${id}`)}`);
  const signedIn = () => (user ? true : (needLogin(), false));
  const isAsker = !!user && question.author?.id === user.id;
  const canAccept = isAsker || !!me.data?.is_moderator;
  const canClose = !!user && (isAsker || !!me.data?.can.close_others);

  const vote = (post: ForumPost, direction: 'up' | 'down') => {
    if (!signedIn()) return;
    run.mutate(() => forumApi.vote(post.id, post.my_vote === direction ? 'none' : direction));
  };

  /** Why a vote is not offered: not allowed yet (reputation), or the member's own post. Empty when it is. */
  const voteBlock = (post: ForumPost, dir: 'up' | 'down'): string => {
    if (!user || !me.data) return '';
    if (post.author?.id === user.id) return t('forum.ownPost');
    if (post.my_vote === dir) return '';
    const key = dir === 'up' ? 'vote_up' : 'vote_down';
    if (!me.data.can[key]) return t('forum.needsReputation', { count: me.data.thresholds[key] });
    if (me.data.votes_left_today === 0) return t('forum.noVotesLeft');
    return '';
  };

  const renderVoteButton = (post: ForumPost, dir: 'up' | 'down') => {
    const block = voteBlock(post, dir);
    const active = post.my_vote === dir;
    const colour = active ? (dir === 'up' ? 'text-green-700' : 'text-red-700') : block ? 'text-gray-200' : 'text-gray-400 hover:text-gray-700';
    return (
      <Tooltip title={block || undefined}>
        <button type="button" aria-label={t(dir === 'up' ? 'forum.voteUp' : 'forum.voteDown')} aria-disabled={!!block} onClick={() => !block && vote(post, dir)}
          className={`bg-transparent border-0 p-1 ${block ? 'cursor-not-allowed' : 'cursor-pointer'} ${colour}`}>
          {dir === 'up' ? <CaretUpOutlined style={{ fontSize: 24 }} /> : <CaretDownOutlined style={{ fontSize: 24 }} />}
        </button>
      </Tooltip>
    );
  };

  const renderVotes = (post: ForumPost) => (
    <div className="flex flex-col items-center w-12 flex-shrink-0 select-none">
      {renderVoteButton(post, 'up')}
      <span className="text-lg font-semibold">{post.score}</span>
      {renderVoteButton(post, 'down')}
      {post.kind === 'answer' && (post.accepted
        ? <CheckCircleFilled aria-label={t('forum.accepted')} style={{ fontSize: 26, color: '#15803d' }} />
        : canAccept && <button type="button" title={t('forum.acceptThis')} onClick={() => run.mutate(() => forumApi.accept(post.id))} className="bg-transparent border-0 cursor-pointer text-gray-300 hover:text-green-700 p-1"><CheckCircleFilled style={{ fontSize: 26 }} /></button>)}
    </div>
  );

  const renderByline = (post: ForumPost) => (
    <div className="text-xs text-gray-500 flex flex-wrap items-center gap-x-3 gap-y-1">
      <span>{post.author ? <Link to={`/forum/users/${post.author.id}`} className="text-gray-600 hover:underline">{`${post.author.name} (${post.author.reputation})`}</Link> : t('forum.formerMember')}</span>
      <span>{when(post.created_at)}</span>
      {post.pending_review && <Tag color="orange" className="m-0">{t('forum.heldBadge')}</Tag>}
      {post.deleted && <Tag color="red" className="m-0">{t('forum.deletedBadge')}</Tag>}
      {post.can_edit && !post.deleted && <button type="button" className="bg-transparent border-0 p-0 text-green-800 cursor-pointer" onClick={() => setEditing(post)}>{t('forum.edit')}</button>}
      {post.kind !== 'comment' && <button type="button" className="bg-transparent border-0 p-0 text-gray-600 cursor-pointer" onClick={() => setHistoryFor(post.id)}>{t('forum.history')}</button>}
      {post.can_delete && !post.deleted && (
        <button type="button" className="bg-transparent border-0 p-0 text-red-700 cursor-pointer"
          onClick={() => Modal.confirm({ title: t('forum.confirmDelete'), okText: t('forum.delete'), okButtonProps: { danger: true }, onOk: () => run.mutateAsync(() => forumApi.remove(post.id)) })}>{t('forum.delete')}</button>
      )}
      {post.flag_count > 0 && <Tag color="red" className="m-0">{t('forum.flagCount', { count: post.flag_count })}</Tag>}
      {post.my_flag ? <span>{t('forum.flagged')}</span>
        : !!user && post.author?.id !== user.id && !post.deleted && !post.pending_review && (
          <button type="button" className="bg-transparent border-0 p-0 text-gray-600 cursor-pointer" onClick={() => setFlagging(post)}>{t('forum.flag')}</button>
        )}
      {post.kind === 'question' && canClose && !post.deleted && (post.closed
        ? <button type="button" className="bg-transparent border-0 p-0 text-green-800 cursor-pointer" onClick={() => run.mutate(() => forumApi.reopen(post.id))}>{t('forum.reopen')}</button>
        : <button type="button" className="bg-transparent border-0 p-0 text-gray-600 cursor-pointer" onClick={() => setClosing(post)}>{t('forum.close')}</button>)}
      {me.data?.is_moderator && post.deleted && <button type="button" className="bg-transparent border-0 p-0 text-green-800 cursor-pointer" onClick={() => run.mutate(() => forumApi.restore(post.id))}>{t('forum.restore')}</button>}
      {me.data?.is_moderator && post.pending_review && <button type="button" className="bg-transparent border-0 p-0 text-green-800 cursor-pointer" onClick={() => run.mutate(() => forumApi.approve(post.id))}>{t('forum.approve')}</button>}
    </div>
  );

  const renderComments = (post: ForumPost) => (
    <div className="mt-3 border-t border-gray-100 pt-2 text-sm">
      {(comments[post.id] ?? []).map((c) => (
        <div key={c.id} className="py-1 border-b border-gray-100 last:border-0">
          <PostBody html={c.body_html} className="inline" /> <span className="text-xs text-gray-500">— {c.author?.name ?? t('forum.formerMember')}, {when(c.created_at)}</span>
          {c.can_delete && !c.deleted && <button type="button" className="ml-2 bg-transparent border-0 p-0 text-xs text-red-700 cursor-pointer" onClick={() => run.mutate(() => forumApi.remove(c.id))}>{t('forum.delete')}</button>}
        </div>
      ))}
      {commentFor === post.id ? (
        <div className="mt-2 flex gap-2">
          <Input value={commentText} onChange={(e) => setCommentText(e.target.value)} maxLength={1000} placeholder={t('forum.commentPlaceholder')} />
          <Button type="primary" disabled={commentText.trim().length < 5} loading={run.isPending}
            onClick={() => run.mutate(async () => { await forumApi.comment(post.id, commentText.trim()); setCommentText(''); setCommentFor(null); })}>{t('forum.addComment')}</Button>
          <Button onClick={() => setCommentFor(null)}>{t('common.cancel')}</Button>
        </div>
      ) : (
        <button type="button" className="mt-1 bg-transparent border-0 p-0 text-green-800 cursor-pointer text-xs" onClick={() => signedIn() && (setCommentFor(post.id), setCommentText(''))}>{t('forum.addComment')}</button>
      )}
    </div>
  );

  const renderPost = (post: ForumPost) => (
    <div className="flex gap-3">
      {renderVotes(post)}
      <div className="min-w-0 flex-1">
        <PostBody html={post.body_html} />
        <Attachments post={post} isModerator={!!me.data?.is_moderator} onChanged={refresh} />
        <div className="mt-2">{renderByline(post)}</div>
        {renderComments(post)}
      </div>
    </div>
  );

  return (
    <div className="grid gap-6 md:grid-cols-[1fr_16rem]">
      <div>
        <h1 className="text-2xl font-semibold mt-0 break-words">{question.title}</h1>
        <div className="flex flex-wrap items-center gap-2 mb-3 text-xs text-gray-500">
          <span>{question.view_count} {t('forum.views')}</span>
          <Tooltip title={t('forum.followHint')}>
            <Button size="small" type={following ? 'default' : 'primary'} ghost={!following} loading={run.isPending}
              onClick={() => signedIn() && run.mutate(() => forumApi.follow(question.id, !following))}>{following ? t('forum.following') : t('forum.follow')}</Button>
          </Tooltip>
          {question.tags.map((name) => <Link key={name} to={`/forum?tag=${encodeURIComponent(name)}`}><Tag className="m-0">{name}</Tag></Link>)}
          {question.workflow_step && <Link to={`/forum?step=${encodeURIComponent(question.workflow_step)}`}><Tag color="blue" className="m-0">{findContext(question.workflow_step) ? t(findContext(question.workflow_step)!.item.labelKey) : question.workflow_step}</Tag></Link>}
        </div>
        {question.closed && (
          <Alert className="mb-3" type="info" showIcon
            title={t(`forum.closedAs.${question.closed_reason ?? 'resolved'}`)}
            description={question.duplicate_of && <Link to={`/forum/q/${question.duplicate_of.id}`}>{question.duplicate_of.title ?? question.duplicate_of.id}</Link>} />
        )}
        {question.pending_review && <Alert className="mb-3" type="warning" showIcon title={t('forum.heldNotice')} />}
        <section className="bg-white rounded-lg shadow-sm p-4">{renderPost(question)}</section>

        <h2 className="text-lg font-semibold mt-6">{t('forum.answerCount', { count: answers.length })}</h2>
        <div className="flex flex-col gap-4">
          {answers.map((a) => <section key={a.id} className={`bg-white rounded-lg shadow-sm p-4 ${a.accepted ? 'ring-2 ring-green-600' : ''}`}>{renderPost(a)}</section>)}
        </div>

        <h2 className="text-lg font-semibold mt-6">{t('forum.yourAnswer')}</h2>
        {question.closed ? <Alert type="info" showIcon title={t('forum.closedNotice')} /> : (
          <div className="bg-white rounded-lg shadow-sm p-4">
            <TextArea rows={6} value={answerText} onChange={(e) => setAnswerText(e.target.value)} maxLength={20000} placeholder={t('forum.answerPlaceholder')} />
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="text-xs text-gray-500">{t('forum.markdownHint')}</span>
              <Button type="primary" loading={run.isPending} disabled={answerText.trim().length < 30}
                onClick={() => signedIn() && run.mutate(async () => { await forumApi.answer(question.id, answerText.trim()); setAnswerText(''); })}>{t('forum.postAnswer')}</Button>
            </div>
            {!user && <div className="mt-2 text-sm"><Link to={`/login?next=${encodeURIComponent(`/forum/q/${id}`)}`}>{t('forum.signInToAnswer')}</Link></div>}
          </div>
        )}
      </div>

      <aside className="bg-white rounded-lg shadow-sm p-4 h-fit">
        <h2 className="text-sm font-semibold uppercase text-gray-500 mt-0">{t('forum.related')}</h2>
        {related.length === 0 && <div className="text-sm text-gray-500">{t('forum.noRelated')}</div>}
        <ul className="list-none p-0 m-0 flex flex-col gap-2">
          {related.map((r) => <li key={r.id}><Link to={`/forum/q/${r.id}`} className="text-sm text-green-800 hover:underline">{r.title}</Link></li>)}
        </ul>
      </aside>

      <FlagModal post={flagging} onClose={() => setFlagging(null)} onDone={refresh} />
      <CloseModal question={closing} onClose={() => setClosing(null)} onDone={refresh} />
      <EditPostModal post={editing} onClose={() => setEditing(null)} onSaved={refresh} />
      <RevisionsDrawer postId={historyFor} onClose={() => setHistoryFor(null)} />
    </div>
  );
};

export default ForumQuestionPage;
