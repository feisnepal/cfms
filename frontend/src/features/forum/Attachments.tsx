/** Attachments - the screenshots on a post: shown under the text, added by the author, approved or removed by a moderator or the uploader. */
import React, { useEffect, useState } from 'react';
import { Button, Image, Tag, Upload, message } from 'antd';
import { PictureOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { forumApi, forumErrorMessage, ForumAttachment, ForumPost } from './forumApi';

const MAX_PER_POST = 4;
const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPT = 'image/png,image/jpeg,image/webp';

/** One picture. An approved one is a plain address; an unapproved one (the uploader's own) needs the login, so it is fetched as a blob. */
const Picture: React.FC<{ att: ForumAttachment }> = ({ att }) => {
  const [src, setSrc] = useState<string | undefined>(att.approved ? forumApi.attachmentUrl(att.id) : undefined);
  useEffect(() => {
    if (att.approved) {
      setSrc(forumApi.attachmentUrl(att.id));
      return;
    }
    let url: string | undefined;
    let cancelled = false;
    forumApi.attachmentBlob(att.id).then((blob) => {
      if (cancelled) return;
      url = URL.createObjectURL(blob);
      setSrc(url);
    }).catch(() => undefined); // a picture that cannot be fetched just stays blank
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [att.id, att.approved]);
  return src ? <Image src={src} alt={att.file_name} width={160} style={{ objectFit: 'cover', borderRadius: 6 }} /> : <div style={{ width: 160, height: 100 }} className="bg-gray-100 rounded" />;
};

interface Props {
  post: ForumPost;
  isModerator: boolean;
  onChanged: () => void;
}

const Attachments: React.FC<Props> = ({ post, isModerator, onChanged }) => {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) => message.error(forumErrorMessage(e, t('forum.actionFailed')));
  const run = async (job: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await job();
      onChanged();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  if (post.attachments.length === 0 && !post.can_edit) return null;
  const canAdd = post.can_edit && !post.deleted && post.attachments.length < MAX_PER_POST;
  return (
    <div className="mt-3">
      <div className="flex flex-wrap gap-3">
        {post.attachments.map((a) => (
          <div key={a.id} className="flex flex-col items-start gap-1">
            <Picture att={a} />
            {!a.approved && <Tag color="orange" className="m-0">{t('forum.pictureHeld')}</Tag>}
            <div className="text-xs flex gap-3">
              {!a.approved && isModerator && <button type="button" className="bg-transparent border-0 p-0 text-green-800 cursor-pointer" onClick={() => run(() => forumApi.approveAttachment(a.id))}>{t('forum.approve')}</button>}
              {post.can_delete && <button type="button" className="bg-transparent border-0 p-0 text-red-700 cursor-pointer" onClick={() => run(() => forumApi.removeAttachment(a.id))}>{t('forum.deletePicture')}</button>}
            </div>
          </div>
        ))}
      </div>
      {canAdd && (
        <Upload accept={ACCEPT} showUploadList={false} disabled={busy}
          beforeUpload={(file) => {
            if (file.size > MAX_BYTES) message.error(t('forum.pictureTooBig'));
            else run(() => forumApi.attach(post.id, file));
            return false;
          }}>
          <Button size="small" icon={<PictureOutlined />} loading={busy} className="mt-2">{t('forum.addPicture')}</Button>
        </Upload>
      )}
    </div>
  );
};

export default Attachments;
