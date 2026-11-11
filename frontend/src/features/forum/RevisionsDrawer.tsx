/** RevisionsDrawer - the edit history of a post, newest first. Public, like the post. */
import React from 'react';
import { Drawer, Empty, Spin, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useT } from '../../i18n/hooks';
import { forumApi } from './forumApi';
import PostBody from './PostBody';

const RevisionsDrawer: React.FC<{ postId: string | null; onClose: () => void }> = ({ postId, onClose }) => {
  const t = useT();
  const revisions = useQuery({ queryKey: ['forum', 'revisions', postId], queryFn: () => forumApi.revisions(postId as string), enabled: !!postId });
  return (
    <Drawer open={!!postId} onClose={onClose} title={t('forum.history')} size={640}>
      {revisions.isLoading && <div className="py-10 text-center"><Spin /></div>}
      {revisions.data?.length === 0 && <Empty />}
      <div className="flex flex-col gap-4">
        {revisions.data?.map((r) => (
          <section key={r.revision} className="border border-gray-200 rounded-lg p-3">
            <div className="text-xs text-gray-500 flex flex-wrap gap-x-3 mb-2">
              <strong>{t('forum.revision', { n: r.revision })}</strong>
              <span>{r.author_name ?? t('forum.formerMember')}</span>
              <span>{new Date(r.revised_at).toLocaleString()}</span>
              {r.summary && <em>{r.summary}</em>}
            </div>
            {r.title && <div className="font-medium mb-1">{r.title}</div>}
            {r.tag_names && <div className="mb-2">{r.tag_names.split(' ').map((n) => <Tag key={n} className="m-0 mr-1">{n}</Tag>)}</div>}
            <PostBody html={r.body_html} />
          </section>
        ))}
      </div>
    </Drawer>
  );
};

export default RevisionsDrawer;
