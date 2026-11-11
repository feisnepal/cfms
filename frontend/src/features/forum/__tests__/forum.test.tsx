import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import PostBody from '../PostBody';
import { forumErrorMessage } from '../forumApi';

describe('PostBody', () => {
  it('keeps the formatting the server renders', () => {
    const html = renderToStaticMarkup(<PostBody html={'<p>hi <strong>there</strong></p><ul><li>one</li></ul>'} />);
    expect(html).toContain('<strong>there</strong>');
    expect(html).toContain('<li>one</li>');
  });

  it('drops anything that could run even if the server let it through', () => {
    const html = renderToStaticMarkup(
      <PostBody html={'<p onclick="x()">a</p><script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">b</a><iframe src="//e"></iframe>'} />,
    );
    expect(html).not.toMatch(/<script|<img|<iframe|onclick|onerror|javascript:/i);
  });

  it('keeps an https link and its rel', () => {
    const html = renderToStaticMarkup(<PostBody html={'<a href="https://example.org" rel="nofollow ugc noopener" target="_blank">x</a>'} />);
    expect(html).toContain('href="https://example.org"');
    expect(html).toContain('nofollow');
  });
});

describe('forumErrorMessage', () => {
  it('reads the server message', () => {
    expect(forumErrorMessage({ response: { data: { detail: { code: 'forum.rule', message: 'you already answered' } } } }, 'fallback')).toBe('you already answered');
  });
  it('reads a plain string detail', () => {
    expect(forumErrorMessage({ response: { data: { detail: 'nope' } } }, 'fallback')).toBe('nope');
  });
  it('falls back', () => {
    expect(forumErrorMessage(new Error('boom'), 'fallback')).toBe('fallback');
    expect(forumErrorMessage({ response: { data: { detail: [{ loc: ['body'] }] } } }, 'fallback')).toBe('fallback');
  });
});
