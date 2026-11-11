/** The shared "what is wrong and how to fix it" report (UP-2.2). */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}${JSON.stringify(v)}` : k) }));

import i18n from '../../i18n';
import { UploadReport } from '../UploadReport';
import { findingsFromBody, findingsFromError, problemRowsCsv, type UploadFinding } from '../../lib/uploadFindings';

const f = (over: Partial<UploadFinding> = {}): UploadFinding => ({
  code: 'household.row_invalid', severity: 'warning', title_en: '2 rows have a problem: female_count cannot be negative',
  title_ne: '२ पङ्क्तिमा समस्या छ', fix_en: 'Correct these rows and upload again.', fix_ne: 'यी पङ्क्ति सच्याउनुहोस्।',
  where: { rows: [4, 5] }, found: 'x', expected: '', ...over,
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('UploadReport', () => {
  it('shows nothing when there is nothing to report', () => {
    const { container } = render(<UploadReport findings={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('says what is wrong, where, and how to fix it', () => {
    render(<UploadReport findings={[f()]} />);
    const box = screen.getByTestId('finding-household.row_invalid');
    expect(box.textContent).toContain('2 rows have a problem');
    expect(screen.getByTestId('finding-where').textContent).toContain('uploadReport.rows 4, 5');
    expect(box.textContent).toContain('uploadReport.howToFix');
    expect(box.textContent).toContain('Correct these rows and upload again.');
  });

  it('speaks the user\'s language', async () => {
    await i18n.changeLanguage('ne');
    render(<UploadReport findings={[f()]} />);
    const box = screen.getByTestId('finding-household.row_invalid');
    expect(box.textContent).toContain('२ पङ्क्तिमा समस्या छ');
    expect(box.textContent).toContain('यी पङ्क्ति सच्याउनुहोस्।');
    expect(box.textContent).not.toContain('Correct these rows');
  });

  it('puts errors first, and keeps notes quiet (no "how to fix" for an info line)', () => {
    render(<UploadReport findings={[f({ code: 'a.info', severity: 'info', title_en: 'Stand types found: tree.' }), f({ code: 'b.err', severity: 'error', title_en: 'No data.' })]} />);
    const order = screen.getAllByTestId(/^finding-/).map((n) => n.getAttribute('data-severity')).filter(Boolean);
    expect(order).toEqual(['error', 'info']);
    expect(screen.getByTestId('finding-a.info').textContent).not.toContain('uploadReport.howToFix');
  });

  it('shortens a long row list but says how many more', () => {
    render(<UploadReport findings={[f({ where: { rows: Array.from({ length: 20 }, (_, i) => i + 3) } })]} />);
    expect(screen.getByTestId('finding-where').textContent).toContain('(+8)');
  });

  it('offers the problem rows as a file to correct, only when it knows them', async () => {
    const createObjectURL = vi.fn(() => 'blob:x');
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const { rerender } = render(<UploadReport findings={[f()]} />);
    expect(screen.queryByTestId('download-problem-rows')).toBeNull();
    rerender(<UploadReport findings={[f()]} problemRows={[{ row: 4, problem: 'bad' }]} />);
    await userEvent.click(screen.getByTestId('download-problem-rows'));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});

describe('uploadFindings helpers', () => {
  it('reads the findings out of a refused upload and out of an imperfect success body', () => {
    const err = { response: { data: { detail: { code: 'file.empty', findings: [f({ code: 'file.empty' })] } } } };
    expect(findingsFromError(err)?.[0].code).toBe('file.empty');
    expect(findingsFromError({ response: { data: { detail: 'plain text' } } })).toBeNull();
    expect(findingsFromError(new Error('offline'))).toBeNull();
    expect(findingsFromBody({ findings: [f()] })).toHaveLength(1);
    expect(findingsFromBody({})).toEqual([]);
    expect(findingsFromBody({ findings: [{ nope: 1 }] })).toEqual([]); // anything that is not a finding is ignored
  });

  it('writes the problem rows as a CSV that Excel opens correctly, quoting the text', () => {
    const csv = problemRowsCsv([{ row: 4, problem: 'a "quoted", problem' }]);
    expect(csv.startsWith('﻿row,problem')).toBe(true);
    expect(csv).toContain('4,"a ""quoted"", problem"');
  });

  describe('proposed corrections', () => {
    const proposal = { row: 4, column: 'pole_dbh_cm', stand: 'pole', measure: 'dbh', old: 50, new: 22.3, range: '10 to under 30 cm', belongs_to: 'tree' };
    const withProposals = () => f({ code: 'field_inventory.corrections_proposed', severity: 'error', where: { file: 'fi.csv', rows: [4], proposals: [proposal] } });

    it('lists the row, the old value, the proposed one and the class the value belongs to', () => {
      render(<UploadReport findings={[withProposals()]} />);
      const table = screen.getByTestId('proposals');
      expect(table.textContent).toContain('pole_dbh_cm');
      expect(table.textContent).toContain('50');
      expect(table.textContent).toContain('22.3');
      expect(table.textContent).toContain('uploadReport.proposals.classNote{"class":"tree"}');
      expect(screen.queryByTestId('apply-corrections')).toBeNull(); // no handler given: nothing to press
    });

    it('offers to apply them when the caller can import again', async () => {
      const onApply = vi.fn();
      render(<UploadReport findings={[withProposals()]} onApplyCorrections={onApply} />);
      await userEvent.click(screen.getByTestId('apply-corrections'));
      expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ code: 'field_inventory.corrections_proposed' }));
    });
  });

  it('offers to renumber the sample plots when the fix is renumber_plots', async () => {
    const onRenumber = vi.fn();
    const finding = f({ code: 'sample_plots.numbers_not_consecutive', severity: 'error', auto_fix: 'renumber_plots', where: { file: 'plots.csv' } });
    const { rerender } = render(<UploadReport findings={[finding]} />);
    expect(screen.queryByTestId('renumber-plots')).toBeNull();
    rerender(<UploadReport findings={[finding]} onRenumber={onRenumber} />);
    await userEvent.click(screen.getByTestId('renumber-plots'));
    expect(onRenumber).toHaveBeenCalledWith(expect.objectContaining({ auto_fix: 'renumber_plots' }));
  });
});
