import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import AdminChatView from '../AdminChatView';
import type { ChatAdminRow, ChatAdminSettings } from '../chatApi';

const row = (over: Partial<ChatAdminRow>): ChatAdminRow => ({
  user_id: 'u1', email: 'a@x.com', full_name: 'Asha', role: 'user', status: 'requested', daily_cap_tokens: 100000,
  requested_at: '2026-11-10T00:00:00Z', request_note: 'I am the secretary', approved_at: null, expires_at: null,
  tokens_used_today: 1234, messages_today: 3, thumbs_down_30d: 2, ...over,
});
const settings = (over: Partial<ChatAdminSettings> = {}): ChatAdminSettings => ({ enabled: true, pool_daily_tokens: null, pool_used_today: 5000, ...over });
const render = (rows: ChatAdminRow[], s: ChatAdminSettings | null = settings(), error: string | null = null) =>
  renderToStaticMarkup(
    <AdminChatView settings={s} rows={rows} busy={false} error={error} onSaveSettings={() => {}} onApprove={() => {}} onRevoke={() => {}} onSetCap={() => {}} />,
  );

describe('AdminChatView', () => {
  it('shows a waiting request with its note, an approve button and no save-limit button', () => {
    const html = render([row({})]);
    expect(html).toContain('I am the secretary');
    expect(html).toContain('1,234');
    expect(html).toMatch(/bg-green-600 text-white disabled:opacity-50"[^>]*>Approve|>Approve</);
    expect(html).not.toContain('Save limit');
  });
  it('lets an approved person be limited or withdrawn but not approved again', () => {
    const html = render([row({ status: 'approved' })]);
    expect(html).toContain('Save limit');
    expect(html).toContain('>Withdraw<');
    expect(html).not.toContain('>Approve<');
  });
  it('lets a withdrawn person be approved again but not withdrawn again', () => {
    const html = render([row({ status: 'revoked' })]);
    expect(html).toContain('>Approve<');
    expect(html).not.toContain('>Withdraw<');
  });
  it('lists waiting requests before approved before withdrawn', () => {
    const html = render([row({ user_id: 'c', status: 'revoked', email: 'c@x.com' }), row({ user_id: 'a', status: 'approved', email: 'a@x.com' }), row({ user_id: 'b', status: 'requested', email: 'b@x.com' })]);
    expect(html.indexOf('b@x.com')).toBeLessThan(html.indexOf('a@x.com'));
    expect(html.indexOf('a@x.com')).toBeLessThan(html.indexOf('c@x.com'));
  });
  it('states plainly when the assistant is switched off, with a switch-on button', () => {
    const html = render([], settings({ enabled: false }));
    expect(html).toContain('SWITCHED OFF');
    expect(html).toContain('Switch on');
    expect(html).not.toContain('Switch off now');
  });
  it('shows the shared pool and what is used', () => {
    expect(render([], settings({ pool_daily_tokens: 200000 }))).toContain('5,000');
  });
  it('says so when nobody has asked, and shows an error', () => {
    expect(render([])).toContain('Nobody has asked');
    expect(render([], null, 'boom')).toContain('boom');
  });
  it('escapes a request note', () => {
    expect(render([row({ request_note: '<img src=x onerror=alert(1)>' })])).not.toContain('<img');
  });
});
