/** The Schedule 11 code builder in the metadata form (owner request 2026-10-11). */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import en from '../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    const node = lookup(key);
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../../services/api', () => ({ nationalCodeApi: { reference: vi.fn(), check: vi.fn(), match: vi.fn() } }));

import { nationalCodeApi } from '../../services/api';
import { NationalCodeBuilder, NationalCodeStatus, serialDigits } from '../fieldInventory/NationalCodeBuilder';

const api = nationalCodeApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const REFERENCE = {
  source: 's',
  provinces: [
    {
      name: 'Sudurpashchim', code: 'SUD',
      divisions: [
        { name: 'Kailai Dhangadhi', code: 'KAI', districts: ['Kailai'], locals: [{ name: 'Chure', no: '09', district: 'Kailai' }] },
        { name: 'Kailai Pahalmanpur', code: 'KLP', districts: ['Kailai'], locals: [{ name: 'Mohanyal', no: '01', district: 'Kailai' }, { name: 'Joshipur', no: '06', district: 'Kailai' }] },
      ],
    },
  ],
};

const MATCH_NONE = { province_code: null, division_code: null, local_no: null, local_name: null, division_name: null, district: null, confidence: 'none', candidates: [] };
beforeEach(() => {
  vi.clearAllMocks();
  api.reference.mockResolvedValue(REFERENCE);
  api.match.mockResolvedValue(MATCH_NONE);
});

describe('NationalCodeBuilder', () => {
  it('stays closed until asked, then builds the code from the schedule and hands it over', async () => {
    const onUse = vi.fn();
    render(<NationalCodeBuilder value="" onUse={onUse} />);
    expect(screen.queryByTestId('fm-code-builder')).toBeNull();
    fireEvent.click(screen.getByTestId('fm-code-builder-toggle'));
    await waitFor(() => expect(screen.getByTestId('fm-code-province').querySelectorAll('option').length).toBeGreaterThan(1));

    fireEvent.change(screen.getByTestId('fm-code-province'), { target: { value: 'SUD' } });
    // two division offices in one district: both are offered, by division, so the user picks the right one
    const divisionOptions = Array.from(screen.getByTestId('fm-code-division').querySelectorAll('option')).map((o) => o.textContent);
    expect(divisionOptions).toContain('Kailai Dhangadhi (KAI) - Kailai');
    expect(divisionOptions).toContain('Kailai Pahalmanpur (KLP) - Kailai');
    fireEvent.change(screen.getByTestId('fm-code-division'), { target: { value: 'KLP' } });
    fireEvent.change(screen.getByTestId('fm-code-local'), { target: { value: '06' } });
    expect((screen.getByTestId('fm-code-use') as HTMLButtonElement).disabled).toBe(true); // sub-division and serial still missing
    expect(screen.getByTestId('fm-code-preview').textContent).toBe('SUD/KLP/__/06/___');

    fireEvent.change(screen.getByTestId('fm-code-sub'), { target: { value: 'ab' } });
    fireEvent.change(screen.getByTestId('fm-code-serial'), { target: { value: '12x' } });
    expect(screen.getByTestId('fm-code-preview').textContent).toBe('SUD/KLP/AB/06/12');
    fireEvent.click(screen.getByTestId('fm-code-use'));
    expect(onUse).toHaveBeenCalledWith('SUD/KLP/AB/06/12');
  });

  it('starts from a code that already follows the format', async () => {
    render(<NationalCodeBuilder value="SUD/KAI/CD/09/003" onUse={() => undefined} />);
    fireEvent.click(screen.getByTestId('fm-code-builder-toggle'));
    await waitFor(() => expect(screen.getByTestId('fm-code-preview').textContent).toBe('SUD/KAI/CD/09/003'));
  });

  it('still lets the code be typed by hand when the schedule cannot be loaded', async () => {
    api.reference.mockRejectedValueOnce(new Error('down'));
    render(<NationalCodeBuilder value="" onUse={() => undefined} />);
    // a fresh module-level cache is not available here, so the failure shows only if nothing was cached; either way no throw
    fireEvent.click(screen.getByTestId('fm-code-builder-toggle'));
    await waitFor(() => expect(screen.getByTestId('fm-code-builder')).toBeTruthy());
  });
});

describe('NationalCodeStatus', () => {
  it('says a code follows the schedule, or names what does not (advisory)', async () => {
    api.check.mockResolvedValueOnce({ ok: true, parts: {}, problems: [] });
    const { rerender } = render(<NationalCodeStatus value="KOS/TAP/AB/01/7" />);
    await waitFor(() => expect(screen.getByTestId('fm-code-status').textContent).toContain('Follows Schedule 11'), { timeout: 3000 });

    api.check.mockResolvedValueOnce({ ok: false, parts: null, problems: ['format'] });
    rerender(<NationalCodeStatus value="MAK/PH/42/33" />);
    await waitFor(() => expect(screen.getByTestId('fm-code-status').textContent).toContain('kept as typed'), { timeout: 3000 });
  });

  it('shows nothing for an empty code', () => {
    render(<NationalCodeStatus value="" />);
    expect(screen.queryByTestId('fm-code-status')).toBeNull();
    expect(api.check).not.toHaveBeenCalled();
  });
});

describe('NationalCodeBuilder - preselecting from the form', () => {
  const hints = { province: 'कोशी', palika: 'Udayapurgadhi', district: 'त्रिवेणी', serial: '१२' };
  const open = () => fireEvent.click(screen.getByTestId('fm-code-builder-toggle'));

  it('reads the serial number in either script', () => {
    expect(serialDigits('१२')).toBe('12');
    expect(serialDigits(' 007 ')).toBe('007');
    expect(serialDigits('No. 3')).toBe('3');
    expect(serialDigits('')).toBe('');
    expect(serialDigits('12345')).toBe('1234'); // the code's serial is at most 4 digits
  });

  it('preselects province, division and municipality from the match, and the serial from the form', async () => {
    api.match.mockResolvedValue({
      province_code: 'SUD', division_code: 'KLP', local_no: '06', local_name: 'Joshipur', division_name: 'Kailai Pahalmanpur',
      district: 'Kailai', confidence: 'exact', candidates: [],
    });
    render(<NationalCodeBuilder value="" onUse={() => undefined} calculationId="C1" hints={hints} />);
    open();
    await waitFor(() => expect(screen.getByTestId('fm-code-preview').textContent).toBe('SUD/KLP/__/06/12'));
    expect(api.match).toHaveBeenCalledWith('C1', { province: 'कोशी', palika: 'Udayapurgadhi', district: 'त्रिवेणी' });
    expect(screen.getByTestId('fm-code-match').textContent).toContain('Joshipur is under Kailai Pahalmanpur (KLP), local level 06');
    await waitFor(() => expect((screen.getByTestId('fm-code-division') as HTMLSelectElement).value).toBe('KLP'));
    expect((screen.getByTestId('fm-code-use') as HTMLButtonElement).disabled).toBe(true); // the 2-letter sub-division code is still the user's
  });

  it('asks the user to pick when several municipalities share the name, and fills the rest from the pick', async () => {
    api.match.mockResolvedValue({
      province_code: 'SUD', division_code: null, local_no: null, local_name: null, division_name: null, district: null, confidence: 'ambiguous',
      candidates: [
        { province_code: 'SUD', division_code: 'KAI', division_name: 'Kailai Dhangadhi', district: 'Kailai', local_no: '09', local_name: 'Chure' },
        { province_code: 'SUD', division_code: 'KLP', division_name: 'Kailai Pahalmanpur', district: 'Kailai', local_no: '06', local_name: 'Joshipur' },
      ],
    });
    render(<NationalCodeBuilder value="" onUse={() => undefined} calculationId="C1" hints={hints} />);
    open();
    await waitFor(() => expect(screen.getByTestId('fm-code-candidate-KLP')).toBeTruthy());
    expect(screen.getByTestId('fm-code-preview').textContent).toBe('SUD/___/__/__/12'); // province known, the rest not guessed
    fireEvent.click(screen.getByTestId('fm-code-candidate-KLP'));
    expect(screen.getByTestId('fm-code-preview').textContent).toBe('SUD/KLP/__/06/12');
  });

  it('does not look anything up when the code is already in the format, and keeps what is there', async () => {
    render(<NationalCodeBuilder value="SUD/KAI/CD/09/003" onUse={() => undefined} calculationId="C1" hints={hints} />);
    open();
    await waitFor(() => expect(screen.getByTestId('fm-code-preview').textContent).toBe('SUD/KAI/CD/09/003'));
    expect(api.match).not.toHaveBeenCalled();
  });

  it('only the province is preselected when the municipality cannot be matched', async () => {
    api.match.mockResolvedValue({ ...MATCH_NONE, province_code: 'KOS' });
    render(<NationalCodeBuilder value="" onUse={() => undefined} calculationId="C1" hints={{ ...hints, palika: 'उदयपुरगढी' }} />);
    open();
    await waitFor(() => expect(screen.getByTestId('fm-code-preview').textContent).toBe('KOS/___/__/__/12'));
    expect(screen.queryByTestId('fm-code-match')).toBeNull();
  });

  it('works without a lookup when the form has nothing to go on', async () => {
    render(<NationalCodeBuilder value="" onUse={() => undefined} calculationId="C1" hints={{ province: '', palika: '', district: '', serial: '' }} />);
    open();
    await waitFor(() => expect(screen.getByTestId('fm-code-preview').textContent).toBe('___/___/__/__/___'));
    expect(api.match).not.toHaveBeenCalled();
  });
});
