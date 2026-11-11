/** "Update attribute": an uploaded inventory can be ticked and shows no "open the step" link; a missing one cannot and does. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import en from '../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string): string => (typeof lookup(key) === 'string' ? (lookup(key) as string) : key);
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../../services/api', () => ({ attributeComponentsApi: { list: vi.fn(), run: vi.fn() } }));

import { attributeComponentsApi } from '../../services/api';
import { UpdateAttributeDialog } from '../UpdateAttributeDialog';

const api = attributeComponentsApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const item = (over: Record<string, unknown>) => ({
  key: 'inventory', label_en: 'Inventory analysis', label_ne: 'x', state: 'up_to_date', available: true, can_run: true,
  reason_en: '', reason_ne: '', open_step: '', ...over,
});
const show = () =>
  render(
    <MemoryRouter>
      <UpdateAttributeDialog calculationId="C1" open onClose={() => {}} />
    </MemoryRouter>,
  );

beforeEach(() => vi.clearAllMocks());

describe('UpdateAttributeDialog - inventory item', () => {
  it('is tickable and has no open-step link when the inventory is uploaded', async () => {
    api.list.mockResolvedValue([item({ state: 'out_of_date', reason_en: 'The units changed since the inventory was processed.' })]);
    show();
    const box = (await screen.findByRole('checkbox')) as HTMLInputElement;
    expect(box.disabled).toBe(false);
    expect(box.checked).toBe(true); // out of date -> ticked for the user
    expect(screen.queryByText(en.attributeUpdate.openStep)).toBeNull();
  });

  it('is not tickable and offers the Field Inventory step when nothing is uploaded', async () => {
    api.list.mockResolvedValue([
      item({ state: 'unavailable', available: false, can_run: false, reason_en: 'Upload it in the Field Inventory step.', open_step: 'fieldinventory' }),
    ]);
    show();
    await waitFor(() => expect(screen.getByText(en.attributeUpdate.openStep)).toBeTruthy());
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(true);
  });
});
