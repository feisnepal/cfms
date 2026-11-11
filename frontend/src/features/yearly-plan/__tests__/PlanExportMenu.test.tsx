/**
 * The Export button of the yearly plan (P2, D10/D11): two named files from the ONE server exporter, and an
 * exported file is always saved data — so unsaved changes are asked about first.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { message } from 'antd';
import en from '../../../i18n/locales/en.json';

const lang = vi.hoisted(() => ({ current: 'en' }));
vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string): string => (typeof lookup(key) === 'string' ? (lookup(key) as string) : key);
  return {
    useTranslation: () => ({
      t,
      i18n: {
        get language() {
          return lang.current;
        },
      },
    }),
  };
});
vi.mock('../../../utils/download', () => ({ downloadFromApi: vi.fn(), downloadBlob: vi.fn() }));

import { downloadFromApi } from '../../../utils/download';
import { PlanExportMenu } from '../PlanExportMenu';
import { downloadPlanFile, planExportLang, planExportUrl } from '../planExport';

const download = downloadFromApi as unknown as ReturnType<typeof vi.fn>;

async function openMenu() {
  fireEvent.mouseEnter(screen.getByTestId('plan-export'));
  fireEvent.click(screen.getByTestId('plan-export'));
  await screen.findByText('Yearly plan (CSV)');
}

beforeEach(() => {
  vi.clearAllMocks();
  lang.current = 'en';
  download.mockResolvedValue(undefined);
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
});

describe('the exporter', () => {
  it('always calls the same two routes', () => {
    expect(planExportUrl('c1', 'plan')).toBe('/api/yearly-activities/calculations/c1/yearly-plan/export');
    expect(planExportUrl('c1', 'features')).toBe('/api/yearly-activities/calculations/c1/activity-features/export');
  });

  it('asks for a CSV with headers in the interface language', async () => {
    await downloadPlanFile('c1', 'plan', 'ne');
    expect(download).toHaveBeenCalledWith('/api/yearly-activities/calculations/c1/yearly-plan/export', expect.any(String), {
      format: 'csv',
      lang: 'ne',
    });
    expect(planExportLang('ne')).toBe('ne');
    expect(planExportLang('en-US')).toBe('en');
    expect(planExportLang(undefined)).toBe('en');
  });
});

describe('the Export menu', () => {
  it('offers the two named files', async () => {
    render(<PlanExportMenu calculationId="c1" />);
    await openMenu();
    expect(screen.getByText('Yearly plan (CSV)')).toBeInTheDocument();
    expect(screen.getByText('Activity features (CSV)')).toBeInTheDocument();
  });

  it('downloads the yearly plan straight away when everything is saved', async () => {
    render(<PlanExportMenu calculationId="c1" />);
    await openMenu();
    fireEvent.click(screen.getByText('Yearly plan (CSV)'));
    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(download.mock.calls[0][0]).toBe('/api/yearly-activities/calculations/c1/yearly-plan/export');
    expect(screen.queryByTestId('export-save-first')).toBeNull();
  });

  it('downloads the activity features from the other route', async () => {
    render(<PlanExportMenu calculationId="c1" />);
    await openMenu();
    fireEvent.click(screen.getByText('Activity features (CSV)'));
    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(download.mock.calls[0][0]).toContain('/activity-features/export');
  });

  it('with unsaved changes it asks first, and "Export saved data" exports without saving', async () => {
    const onSave = vi.fn().mockResolvedValue(true);
    render(<PlanExportMenu calculationId="c1" unsaved onSave={onSave} />);
    await openMenu();
    fireEvent.click(screen.getByText('Yearly plan (CSV)'));
    fireEvent.click(await screen.findByTestId('export-saved'));
    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(onSave).not.toHaveBeenCalled();
  });

  it('"Save, then export" saves first and only then exports', async () => {
    const order: string[] = [];
    const onSave = vi.fn().mockImplementation(async () => {
      order.push('save');
      return true;
    });
    download.mockImplementation(async () => {
      order.push('export');
    });
    render(<PlanExportMenu calculationId="c1" unsaved onSave={onSave} />);
    await openMenu();
    fireEvent.click(screen.getByText('Yearly plan (CSV)'));
    fireEvent.click(await screen.findByTestId('export-save-first'));
    await waitFor(() => expect(order).toEqual(['save', 'export']));
  });

  it('when saving fails nothing is exported (the page has already said why)', async () => {
    const onSave = vi.fn().mockResolvedValue(false);
    render(<PlanExportMenu calculationId="c1" unsaved onSave={onSave} />);
    await openMenu();
    fireEvent.click(screen.getByText('Yearly plan (CSV)'));
    fireEvent.click(await screen.findByTestId('export-save-first'));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(download).not.toHaveBeenCalled();
  });

  it('Cancel exports nothing', async () => {
    render(<PlanExportMenu calculationId="c1" unsaved onSave={vi.fn()} />);
    await openMenu();
    fireEvent.click(screen.getByText('Yearly plan (CSV)'));
    fireEvent.click(await screen.findByTestId('export-cancel'));
    expect(download).not.toHaveBeenCalled();
  });

  it('a failed download says so in plain words and never shows the server text', async () => {
    download.mockRejectedValue(new Error('relation "x" does not exist'));
    render(<PlanExportMenu calculationId="c1" />);
    await openMenu();
    fireEvent.click(screen.getByText('Yearly plan (CSV)'));
    await waitFor(() => expect(message.error).toHaveBeenCalled());
    const shown = String((message.error as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(shown).toContain('Could not create the file');
    expect(shown).not.toContain('relation');
  });

  it('is disabled when there is nothing to export', () => {
    render(<PlanExportMenu calculationId="c1" disabled />);
    expect(screen.getByTestId('plan-export')).toBeDisabled();
  });
});
