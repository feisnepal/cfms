/**
 * ForestMetadataPanel — the record, and the requests it makes.
 *
 * WORKSPACE_FLOW_NAV_PLAN D5. Two things are worth pinning here.
 *
 * 1. The seeded/unsaved distinction. The GET fills the form from the
 *    calculation's own analysis, but `persisted: false` means those values are
 *    *suggestions*. A panel that rendered them as a saved record would claim a
 *    forest has a recorded CF code and fiscal year when nobody has entered them,
 *    and that claim ends up printed on a document.
 *
 * 2. That generation carries no metadata. The endpoint reads the stored record
 *    itself, so anything the client posted about the forest would be a second,
 *    unchecked source of truth for the same fields. The wire shape of that call
 *    is asserted in `services/__tests__/reportApi.test.ts`, against axios,
 *    because the section-picker bug it fixes was never visible from the button.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import React from 'react';

import en from '../../i18n/locales/en.json';
import ne from '../../i18n/locales/ne.json';

const getMetadata = vi.fn();
const saveMetadata = vi.fn();
const getSections = vi.fn();
const generateReport = vi.fn();
const getReportStatus = vi.fn();
const downloadReport = vi.fn();

// `useT` is deliberately not mocked: the counts in the progress line only mean
// anything if the real bundle is resolving the placeholders.

vi.mock('../../services/api', () => ({
  // The Schedule 11 code helper under the code field: not what this file tests, so it answers "nothing to say".
  nationalCodeApi: {
    reference: vi.fn().mockResolvedValue({ source: 's', provinces: [] }),
    check: vi.fn().mockResolvedValue({ ok: true, parts: {}, problems: [] }),
    match: vi.fn().mockResolvedValue({ province_code: null, division_code: null, local_no: null, local_name: null, division_name: null, district: null, confidence: 'none', candidates: [] }),
  },
  FOREST_METADATA_FIELDS: [
    'forest_name',
    'group_name',
    'province',
    'district',
    'palika',
    'ward',
    'division',
    'sub_division',
    'cf_national_code',
    'fy_start',
    'fy_end',
  ],
  FOREST_METADATA_OPTIONAL_FIELDS: [
    'cf_registration_number',
    'constitution_approved_year',
    'user_group_reg_no',
    'cf_sn_number',
    'cf_boundary_east',
    'cf_boundary_south',
    'cf_boundary_west',
    'cf_boundary_north',
    'physiography_zone',
    'protected_area_status',
    'forest_type',
    'forest_abundance',
    'forest_avg_age',
    'main_non_timber_fp',
    'avg_crown_density_pct',
    'ug_province',
    'ug_district',
    'ug_municipality',
    'ug_municipality_type',
    'ug_ward',
    'ug_division',
    'ug_sub_division',
    'ug_settlement',
    'ug_boundary_east',
    'ug_boundary_south',
    'ug_boundary_west',
    'ug_boundary_north',

    'sub_division_chief',
    'forest_management_section_chief',
    'division_forest_officer',
    'technical_assistance_org',
    'cf_handover_date',
    'cf_first_renewal_date',
    'cf_history_note',
  ],
  forestMetadataApi: {
    get: (...a: any[]) => getMetadata(...a),
    save: (...a: any[]) => saveMetadata(...a),
  },
  reportApi: {
    getAvailableSections: (...a: any[]) => getSections(...a),
    generateReport: (...a: any[]) => generateReport(...a),
    getReportStatus: (...a: any[]) => getReportStatus(...a),
    downloadReport: (...a: any[]) => downloadReport(...a),
  },
}));

/** A GET that found a calculation with no record saved against it yet. */
const SEEDED = {
  forest_name: 'Kali Prasad forest',
  group_name: null,
  province: 'बाग्मती',
  district: null,
  palika: null,
  ward: '4',
  division: null,
  sub_division: null,
  cf_national_code: null,
  fy_start: null,
  fy_end: null,
  persisted: false,
};

const SECTIONS = {
  sections: [
    { section: '1', title_ne: 'परिचय', title_en: 'Introduction', status: 'available', auto_generate: true },
    { section: '2', title_ne: 'वन', title_en: 'Forest', status: 'available', auto_generate: true },
    { section: '3', title_ne: 'प्रजाति', title_en: 'Species', status: 'missing_data', auto_generate: false },
  ],
};

let Panel: any;
beforeEach(async () => {
  Panel = (await import('../fieldInventory/ForestMetadataPanel')).ForestMetadataPanel;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const mount = async (record: any = SEEDED) => {
  getMetadata.mockResolvedValue(record);
  getSections.mockResolvedValue(SECTIONS);
  render(<Panel calculationId="calc-1" />);
  await waitFor(() => expect(screen.getByTestId('forest-metadata-panel')).toBeTruthy());
};

const value = (testid: string) => (screen.getByTestId(testid) as HTMLInputElement).value;
const disabled = (testid: string) => (screen.getByTestId(testid) as HTMLButtonElement).disabled;

describe('the form is seeded but does not pretend to be a record', () => {
  it('fills from the analysis and says it is not saved yet', async () => {
    await mount();
    // Seeded...
    expect(value('fm-forest_name')).toBe('Kali Prasad forest');
    expect(value('fm-ward')).toBe('4');
    expect(value('fm-province')).toBe('बाग्मती');
    // ...but not yet a record.
    expect(screen.getByTestId('forest-metadata-unsaved')).toBeTruthy();
    expect(screen.queryByTestId('forest-metadata-saved')).toBeNull();
  });

  it('marks a stored record as saved, with its timestamp', async () => {
    await mount({ ...SEEDED, persisted: true, updated_at: '2026-09-26T12:00:00+05:45' });
    expect(screen.getByTestId('forest-metadata-saved')).toBeTruthy();
    expect(screen.queryByTestId('forest-metadata-unsaved')).toBeNull();
    expect(screen.getByTestId('forest-metadata-updated')).toBeTruthy();
  });

  it('offers no save until something actually changes', async () => {
    await mount();
    // A save that would write back the same values is a button that lies about
    // having recorded something.
    expect(disabled('fm-save')).toBe(true);

    fireEvent.change(screen.getByTestId('fm-cf_national_code'), { target: { value: 'CF-08123' } });
    await waitFor(() => expect(disabled('fm-save')).toBe(false));
  });

  it('treats clearing a field as a change', async () => {
    // Clearing is how a mistyped value goes away, so a field emptied from a
    // stored record has to count as dirty.
    await mount({ ...SEEDED, persisted: true, cf_national_code: 'CF-08123' });
    expect(disabled('fm-save')).toBe(true);
    fireEvent.change(screen.getByTestId('fm-cf_national_code'), { target: { value: '' } });
    await waitFor(() => expect(disabled('fm-save')).toBe(false));
  });

  it('sends every field, blanks included, so a value can be cleared', async () => {
    await mount();
    saveMetadata.mockResolvedValue({ message: 'saved', data: { ...SEEDED, persisted: true } });
    getMetadata.mockResolvedValue({ ...SEEDED, cf_national_code: 'CF-08123', persisted: true });

    fireEvent.change(screen.getByTestId('fm-cf_national_code'), { target: { value: 'CF-08123' } });
    fireEvent.click(screen.getByTestId('fm-save'));

    await waitFor(() => expect(saveMetadata).toHaveBeenCalled());
    const [, payload] = saveMetadata.mock.calls[0];
    expect(payload.cf_national_code).toBe('CF-08123');
    // A field the user never touched is still present, and blank. Omitting it
    // would leave the stored value in place and make "clear this" unexpressible.
    expect(payload).toHaveProperty('fy_start', '');
    // Including the two the old form had no input for at all.
    expect(payload).toHaveProperty('division', '');
    expect(payload).toHaveProperty('sub_division', '');
  });

  it('re-reads after saving, so the badge reflects the server', async () => {
    await mount();
    saveMetadata.mockResolvedValue({ message: 'saved', data: { ...SEEDED, persisted: true } });
    getMetadata.mockResolvedValue({ ...SEEDED, cf_national_code: 'CF-08123', persisted: true });

    fireEvent.change(screen.getByTestId('fm-cf_national_code'), { target: { value: 'CF-08123' } });
    fireEvent.click(screen.getByTestId('fm-save'));

    // Not the typed value: the backend normalises blank to NULL and may reject
    // or adjust one, so what it stored is the only honest thing to display.
    await waitFor(() => expect(screen.getByTestId('forest-metadata-saved')).toBeTruthy());
  });

  it('shows the server\'s own reason when a save is refused', async () => {
    // The backend rejects a save with nothing in it, and enforces fiscal-year
    // rules the form knows nothing about. A blanket "could not save" would hide
    // every one of those reasons behind the same sentence.
    await mount();
    saveMetadata.mockRejectedValue({
      response: {
        data: {
          detail: {
            code: 'forest_metadata.empty_update',
            message: 'Nothing to save',
            message_np: 'सुरक्षित गर्नुपर्ने कुनै विवरण छैन',
          },
        },
      },
    });

    fireEvent.change(screen.getByTestId('fm-forest_name'), { target: { value: '' } });
    fireEvent.click(screen.getByTestId('fm-save'));

    await waitFor(() => expect(screen.getByText('Nothing to save')).toBeTruthy());
  });

  it('surfaces a failed load and offers a retry', async () => {
    getMetadata.mockRejectedValue(new Error('boom'));
    getSections.mockResolvedValue(SECTIONS);
    render(<Panel calculationId="calc-1" />);

    await waitFor(() => expect(screen.getByTestId('forest-metadata-error')).toBeTruthy());
    // Spelled out rather than keyed, so a missing bundle entry fails here.
    expect(screen.getByTestId('forest-metadata-error').textContent).toContain(
      en.forestMetadata.loadFailed,
    );
  });
});

describe('every field is mandatory (owner, 2026-10-11)', () => {
  const FULL = {
    forest_name: 'F', group_name: 'G', province: 'P', district: 'D', palika: 'M', ward: '4', division: 'V', sub_division: 'S',
    cf_national_code: '1/2/3/4/5', fy_start: '2082/83', fy_end: '2086/87', persisted: true, updated_at: null,
  };

  it('shows each empty field red and counts how many are still empty', async () => {
    await mount({ ...FULL, division: '', sub_division: '   ' });
    expect(screen.getByTestId('fm-missing').textContent).toContain('2');
    expect((screen.getByTestId('fm-division') as HTMLInputElement).className).toContain('border-red-500');
    expect((screen.getByTestId('fm-sub_division') as HTMLInputElement).className).toContain('border-red-500');
    expect((screen.getByTestId('fm-ward') as HTMLInputElement).className).not.toContain('border-red-500');
    expect(screen.getByTestId('fm-division').getAttribute('aria-invalid')).toBe('true');
  });

  it('goes quiet as soon as the last field is filled', async () => {
    await mount({ ...FULL, division: '' });
    expect(screen.getByTestId('fm-missing')).toBeTruthy();
    fireEvent.change(screen.getByTestId('fm-division'), { target: { value: 'Kathmandu' } });
    expect(screen.queryByTestId('fm-missing')).toBeNull();
    expect((screen.getByTestId('fm-division') as HTMLInputElement).className).not.toContain('border-red-500');
  });

  it('no longer has an Address (Tole) or Serial Number field', async () => {
    await mount({ ...FULL });
    expect(screen.queryByTestId('fm-address')).toBeNull();
    expect(screen.queryByTestId('fm-serial_number')).toBeNull();
  });
});

describe('generation carries no metadata', () => {
  // The poll is a 2s interval; driven by hand rather than waited out.
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const tick = async (ms = 2100) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  };

  it('sends the chosen sections and the image flag, and nothing about the forest', async () => {
    await mount();
    generateReport.mockResolvedValue({ job_id: 'job-1' });
    getReportStatus.mockResolvedValue({ status: 'running', progress: 50, sections_completed: ['1'] });

    fireEvent.click(screen.getByTestId('fm-generate'));
    await waitFor(() => expect(generateReport).toHaveBeenCalled());

    // Two arguments: there is no third one for forest facts to travel in. The
    // server reads the record, so a posted blob would be a second unchecked
    // source of truth for the very fields the record holds.
    expect(generateReport).toHaveBeenCalledWith('calc-1', ['1', '2'], true);
    expect(generateReport.mock.calls[0]).toHaveLength(3);
  });

  it('preselects the sections the server can write, and locks the ones it cannot', async () => {
    await mount();
    const boxes = screen.getByTestId('fm-sections').querySelectorAll('input[type="checkbox"]');
    // 1, 2 available+auto, 3 missing_data -- one per section, in order.
    expect(boxes).toHaveLength(3);
    expect((boxes[0] as HTMLInputElement).checked).toBe(true);
    expect((boxes[1] as HTMLInputElement).checked).toBe(true);
    expect((boxes[2] as HTMLInputElement).disabled).toBe(true);
  });

  it('counts completed sections from the job, not from the tick boxes', async () => {
    await mount();
    generateReport.mockResolvedValue({ job_id: 'job-1' });
    getReportStatus.mockResolvedValue({ status: 'running', progress: 50, sections_completed: ['1'] });

    fireEvent.click(screen.getByTestId('fm-generate'));
    await tick();

    expect(getReportStatus).toHaveBeenCalledWith('job-1');
    // Two available sections were ticked, but only one had actually been
    // written -- so the count comes from the job, not from the boxes.
    expect(screen.getByTestId('fm-progress').textContent).toContain('1/2');
  });

  it('stops polling when the pane goes away mid-report', async () => {
    // The job keeps running server-side; the client must not keep polling a
    // component that is no longer mounted.
    await mount();
    generateReport.mockResolvedValue({ job_id: 'job-1' });
    getReportStatus.mockResolvedValue({ status: 'running', progress: 10, sections_completed: [] });

    fireEvent.click(screen.getByTestId('fm-generate'));
    expect(screen.getByTestId('fm-progress')).toBeTruthy();

    getReportStatus.mockClear();
    cleanup();
    await tick(10000);
    expect(getReportStatus).not.toHaveBeenCalled();
  });

  it('stops polling and shows the cause when the report fails', async () => {
    await mount();
    generateReport.mockResolvedValue({ job_id: 'job-1' });
    getReportStatus.mockResolvedValue({
      status: 'failed',
      progress: 20,
      sections_completed: ['1'],
      error: 'no data for section 2',
    });

    fireEvent.click(screen.getByTestId('fm-generate'));
    await tick();

    // The server's own words, untranslated, because they name the real cause.
    expect(screen.getByText('no data for section 2')).toBeTruthy();
    getReportStatus.mockClear();
    await tick(10000);
    expect(getReportStatus).not.toHaveBeenCalled();
  });

  it('will not generate with nothing selected', async () => {
    getMetadata.mockResolvedValue(SEEDED);
    getSections.mockResolvedValue({ sections: [] });
    render(<Panel calculationId="calc-1" />);
    await waitFor(() => expect(screen.getByTestId('fm-generate')).toBeTruthy());

    fireEvent.click(screen.getByTestId('fm-generate'));
    expect(generateReport).not.toHaveBeenCalled();
  });

  it('refuses to run the poll for a calculation that has no sections yet', async () => {
    // A calculation with no reportable sections renders the failure notice and
    // keeps Generate disabled, rather than offering a job that cannot finish.
    await mount();
    expect(disabled('fm-generate')).toBe(false);
    getSections.mockResolvedValue({ sections: [] });
    cleanup();
    getSections.mockResolvedValue({ sections: [] });
    getMetadata.mockResolvedValue(SEEDED);
    render(<Panel calculationId="calc-1" />);
    await waitFor(() => expect(screen.getByTestId('fm-generate')).toBeTruthy());
    expect(disabled('fm-generate')).toBe(true);
  });
});

describe('the panel is bilingual', () => {
  it('has distinct Nepali copy for every key the pane owns', () => {
    // Nested sections (the Schedule 11 code builder) are compared leaf by leaf: "a.b.c" -> text.
    const flat = (node: unknown, prefix = ''): Record<string, string> =>
      Object.entries(node as Record<string, unknown>).reduce<Record<string, string>>((acc, [k, v]) => {
        if (v && typeof v === 'object') Object.assign(acc, flat(v, `${prefix}${k}.`));
        else acc[`${prefix}${k}`] = String(v);
        return acc;
      }, {});
    const enFlat = flat(en.forestMetadata);
    const neFlat = flat(ne.forestMetadata);
    for (const key of Object.keys(enFlat)) {
      expect(neFlat[key], `ne.forestMetadata.${key} missing`).toBeTruthy();
      expect(neFlat[key], `ne.forestMetadata.${key} is still English`).not.toBe(enFlat[key]);
    }
  });

  it('reuses the report field labels instead of keeping a parallel set', () => {
    // These labels already existed for the old form. A second copy would drift
    // the moment one of them was reworded.
    for (const key of ['forestName', 'province', 'ward', 'cfCode', 'fyStart', 'fyEnd']) {
      expect(en.reports.tab[key as keyof typeof en.reports.tab], `en.reports.tab.${key}`).toBeTruthy();
      expect(ne.reports.tab[key as keyof typeof ne.reports.tab], `ne.reports.tab.${key}`).toBeTruthy();
    }
  });

  it('labels the two fields the old form could never reach', () => {
    // `build_cover_page` printed a placeholder for these, so they had to gain
    // labels rather than stay invisible.
    expect(en.forestMetadata.division).toBeTruthy();
    expect(en.forestMetadata.subDivision).toBeTruthy();
    expect(ne.forestMetadata.division).not.toBe(en.forestMetadata.division);
    expect(ne.forestMetadata.subDivision).not.toBe(en.forestMetadata.subDivision);
  });
});
