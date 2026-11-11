/** PostBody - a forum post's rendered text. The server escapes everything first; DOMPurify is the second lock, not the only one. */
import React from 'react';
import DOMPurify from 'dompurify';
import './forum.css';

const SANITISE = {
  ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'code', 'pre', 'ul', 'ol', 'li', 'blockquote', 'a'],
  ALLOWED_ATTR: ['href', 'rel', 'target'],
  ALLOWED_URI_REGEXP: /^(?:https?:|mailto:)/i,
  // DOMPurify tests every attribute that is not on its own safe list against ALLOWED_URI_REGEXP, so without this `rel="nofollow ugc noopener"` is stripped
  ADD_URI_SAFE_ATTR: ['rel', 'target'],
};

const PostBody: React.FC<{ html: string; className?: string }> = ({ html, className }) => (
  <div className={`forum-body ${className ?? ''}`} dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html, SANITISE) }} />
);

export default PostBody;
