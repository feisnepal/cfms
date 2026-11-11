import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import ChatPanelView, { type ChatTurn } from '../ChatPanelView';
import { chatErrorMessage, type ChatAccessState } from '../chatApi';

const base: ChatAccessState = {
  state: 'approved', allowed: true, daily_cap_tokens: 100000, tokens_used_today: 25000, tokens_left_today: 75000,
  approx_questions_left: 7, expires_at: null, read_only: false,
};
const render = (access: ChatAccessState | null, extra: Partial<{ loading: boolean; error: string | null; turns: ChatTurn[] }> = {}) =>
  renderToStaticMarkup(
    <ChatPanelView
      access={access} loading={!!extra.loading} error={extra.error ?? null} busy={false} onRequest={() => {}} onRetry={() => {}}
      turns={extra.turns ?? []} sending={false} onSend={() => {}} onFeedback={() => {}}
    />,
  );

describe('ChatPanelView', () => {
  it('offers a request form when the user has not asked', () => {
    const html = render({ ...base, state: 'none', allowed: false });
    expect(html).toContain('<textarea');
    expect(html).toContain('<button');
  });
  it('lets a withdrawn or expired user ask again', () => {
    expect(render({ ...base, state: 'revoked', allowed: false })).toContain('<textarea');
    expect(render({ ...base, state: 'expired', allowed: false })).toContain('<textarea');
  });
  it('shows waiting with no request form', () => {
    expect(render({ ...base, state: 'requested', allowed: false })).not.toContain('<textarea');
  });
  it('shows no input at all for switched-off and not-eligible', () => {
    for (const state of ['switched_off', 'not_eligible'] as const) {
      expect(render({ ...base, state, allowed: false })).not.toContain('<textarea');
    }
  });
  it('shows the allowance and a usable composer when approved', () => {
    const html = render(base);
    expect(html).toContain('aria-valuenow="75"');
    expect(html).toContain('<textarea');
    expect(html).not.toMatch(/<textarea[^>]*disabled/);
  });
  it('shows the conversation, the sources and thumbs on answers only', () => {
    const html = render(base, {
      turns: [
        { id: '1', role: 'user', text: 'How wide is a fire line?' },
        { id: '2', role: 'assistant', text: '1.5 m per side.', sources: ['Fire line width'], feedback: -1 },
      ],
    });
    expect(html).toContain('1.5 m per side.');
    expect(html).toContain('Fire line width');
    expect((html.match(/aria-pressed/g) || []).length).toBe(2);
    expect(html).toContain('aria-pressed="true"');
  });
  it('escapes what a model writes', () => {
    const html = render(base, { turns: [{ id: '1', role: 'assistant', text: '<img src=x onerror=alert(1)>' }] });
    expect(html).not.toContain('<img');
  });
  it('says so for a read-only account', () => {
    expect(render({ ...base, read_only: true })).not.toBe(render(base));
  });
  it('shows an error with a retry when nothing loaded', () => {
    const html = render(null, { error: 'boom' });
    expect(html).toContain('boom');
    expect(html).toContain('<button');
  });
});

describe('chatErrorMessage', () => {
  it('reads the server message', () => {
    expect(chatErrorMessage({ response: { data: { detail: { code: 'x', message: 'not allowed' } } } }, 'fb')).toBe('not allowed');
    expect(chatErrorMessage({ response: { data: { detail: 'plain' } } }, 'fb')).toBe('plain');
    expect(chatErrorMessage(new Error('x'), 'fb')).toBe('fb');
  });
});
