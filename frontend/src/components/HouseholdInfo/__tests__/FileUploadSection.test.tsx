/** Choosing a household file IS the upload (owner, 2026-10-12): valid rows import at once, problem rows are listed with what to fix. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}${JSON.stringify(v)}` : k) }));
// A plain function, not a vi.fn(): vitest's result tracking of a REJECTING spy raises an unhandled rejection that is blamed on the test.
let handler: (calc: string, file: File) => Promise<any> = async () => ({});
const calls: Array<[string, File, boolean]> = [];
vi.mock('../../../services/api', () => ({
  userGroupApi: { uploadHouseholdData: (calc: string, file: File, opts: { replaceAll?: boolean } = {}) => { calls.push([calc, file, !!opts.replaceAll]); return handler(calc, file); }, addHousehold: vi.fn() },
}));

import FileUploadSection from '../FileUploadSection';

const result = (over: Record<string, unknown> = {}) => ({
  success: true, total_rows: 3, valid_rows: 3, invalid_rows: 0, records_imported: 3, records_updated: 0, validations: [], ...over,
});
const file = () => new File(['x'], 'hh.csv', { type: 'text/csv' });

async function choose(onSuccess = vi.fn(), onPartial = vi.fn()) {
  const { container } = render(<FileUploadSection calculationId="c1" hasExistingData={false} onUploadSuccess={onSuccess} onUploadPartial={onPartial} />);
  await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, file());
  return { onSuccess, onPartial };
}

beforeEach(() => {
  calls.length = 0;
  handler = async () => ({});
});

describe('household upload', () => {
  it('uploads as soon as the file is chosen, with no Upload button to press', async () => {
    handler = async () => result();
    const { onSuccess } = await choose();
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0][0]).toBe('c1');
    expect(screen.queryByText('household.upload.btnImport')).toBeNull();
    expect(screen.queryByText('household.upload.btnAppend')).toBeNull();
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1)); // everything went in: straight on to the households
  });

  it('with problem rows it saves the good ones, stays on the screen and says what to do', async () => {
    handler = async () => result({
      total_rows: 5, valid_rows: 3, invalid_rows: 2, records_imported: 2, records_updated: 1,
      validations: [{ row_number: 4, is_valid: false, errors: ['female_count cannot be negative'], warnings: [], data: {} }],
    });
    const { onSuccess, onPartial } = await choose();
    await waitFor(() => expect(onPartial).toHaveBeenCalledTimes(1)); // the saved households are refreshed
    expect(onSuccess).not.toHaveBeenCalled(); // but the user stays to see the rows to fix
    const summary = await screen.findByTestId('household-upload-summary');
    expect(summary.textContent).toContain('household.upload.donePartial');
    expect(summary.textContent).toContain('"bad":2');
    expect(summary.textContent).toContain('household.upload.fixHint');
  });

  it('says so plainly when nothing could be imported or the file had no rows', async () => {
    handler = async () => result({ success: false, total_rows: 2, valid_rows: 0, invalid_rows: 2, records_imported: 0 });
    const { onSuccess, onPartial } = await choose();
    expect((await screen.findByTestId('household-upload-summary')).textContent).toContain('household.upload.nothingImported');
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onPartial).not.toHaveBeenCalled();
  });

  it('tells the user how the file should look when no household rows were found', async () => {
    handler = async () => result({ success: false, total_rows: 0, valid_rows: 0, invalid_rows: 0, records_imported: 0 });
    await choose();
    expect((await screen.findByTestId('household-upload-summary')).textContent).toContain('household.upload.noRows');
  });

  it('a failed request does not leave the screen stuck on "reading"', async () => {
    handler = async () => { throw new Error('offline'); };
    await choose();
    await waitFor(() => expect(calls.length).toBe(1));
    await waitFor(() => expect(screen.queryByTestId('household-upload-reading')).toBeNull());
    expect(screen.queryByTestId('household-upload-summary')).toBeNull(); // no result to show: the error message is the feedback
  });

  const finding = (over: Record<string, unknown> = {}) => ({
    code: 'household.row_invalid', severity: 'warning', title_en: '2 rows have a problem: female_count cannot be negative', title_ne: '२ पङ्क्तिमा समस्या',
    fix_en: 'Correct these rows (rows 4, 5) in your file and upload it again.', fix_ne: 'सच्याउनुहोस्', where: { rows: [4, 5] }, found: '', expected: '', ...over,
  });

  it('shows what is wrong and how to fix it when the file is refused, instead of a bare message', async () => {
    handler = async () => {
      throw { response: { data: { detail: { code: 'file.corrupt', message: 'm', message_np: 'n', findings: [finding({ code: 'file.corrupt', severity: 'error', title_en: 'The file could not be opened.', fix_en: 'Remove any password and save it again as Excel (.xlsx).', where: {} })] } } } };
    };
    await choose();
    const box = await screen.findByTestId('finding-file.corrupt');
    expect(box.textContent).toContain('The file could not be opened.');
    expect(box.textContent).toContain('Remove any password');
    expect(screen.queryByTestId('household-upload-summary')).toBeNull();
  });

  it('with problem rows it lists them by cause and offers them as a file to correct', async () => {
    handler = async () => result({
      total_rows: 5, valid_rows: 3, invalid_rows: 2, records_imported: 3, records_updated: 0,
      validations: [
        { row_number: 4, is_valid: false, errors: ['female_count cannot be negative'], warnings: [], data: {} },
        { row_number: 5, is_valid: false, errors: ['female_count cannot be negative'], warnings: [], data: {} },
      ],
      findings: [finding()],
    });
    await choose();
    const box = await screen.findByTestId('finding-household.row_invalid');
    expect(box.textContent).toContain('2 rows have a problem');
    expect(screen.getByTestId('finding-where').textContent).toContain('4, 5');
    expect(screen.getByTestId('download-problem-rows').textContent).toContain('"count":2');
  });

  it('replace-the-whole-list is a separate, explicit choice: off by default, and it asks first, saying how many households are in the system', async () => {
    handler = async () => result({ records_removed: 2 });
    const onSuccess = vi.fn();
    const { container } = render(<FileUploadSection calculationId="c1" hasExistingData existingCount={118} onUploadSuccess={onSuccess} />);
    // by default a file just updates and adds
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, file());
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0][2]).toBe(false);

    // switched on: nothing is sent until the user confirms, and the confirmation names the count
    calls.length = 0;
    await userEvent.click(screen.getByLabelText(/household\.upload\.replaceAll/));
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, new File(['y'], 'second.csv', { type: 'text/csv' }));
    const body = await screen.findByText(/household\.upload\.replaceConfirmBody/);
    expect(body.textContent).toContain('"count":118');
    expect(calls.length).toBe(0);
    await userEvent.click(screen.getByText('household.upload.replaceConfirmOk'));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0][2]).toBe(true);
  });
});
