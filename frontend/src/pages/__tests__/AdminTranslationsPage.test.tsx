import { describe, it, expect, beforeEach, vi, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AdminTranslationsPage } from '../AdminTranslationsPage';

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  class ResizeObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  }
  (window as any).ResizeObserver = ResizeObserverMock;
  Object.defineProperty(window, 'getComputedStyle', {
    writable: true,
    value: (element: Element) => ({
      getPropertyValue: () => '',
      paddingTop: '0px',
      paddingBottom: '0px',
    }),
  });
});

vi.mock('../../services/api', () => ({
  translationAdminApi: {
    list: vi.fn(),
    upsert: vi.fn(),
    stats: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

vi.mock('../../i18n/index', () => ({
  refreshTranslations: vi.fn().mockResolvedValue(true),
  // `readDetail` (used to show a refused edit's reason) reads the active language
  // from here, and looks the error code up in the bundle via `exists`
  default: { language: 'en', t: (k: string) => k, exists: () => false },
}));

import { translationAdminApi } from '../../services/api';
import { refreshTranslations } from '../../i18n/index';

const rows = [
  { id: 1, key: 'auth.invalid_credentials', en: 'Incorrect email or password', ne: 'इमेल वा पासवर्ड गलत छ', source_file: 'editor', is_override: true, reviewed: false, history_count: 0, updated_by: null },
  { id: 2, key: 'common.save', en: 'Save', ne: 'सुरक्षित गर्नुहोस्', source_file: 'bundle', is_override: false, reviewed: true, history_count: 0, updated_by: null },
];

describe('AdminTranslationsPage (Phase 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (translationAdminApi.list as any).mockResolvedValue({ items: rows, total: 2, page: 1, per_page: 50 });
    (translationAdminApi.upsert as any).mockImplementation(async (key: string, payload: Record<string, unknown>) => ({ ...rows[0], ...payload }));
    (translationAdminApi.stats as any).mockResolvedValue({ total_keys: 2, untranslated_ne: 0, overrides: 1, reviewed: 1, ne_keys: 2, en_keys: 2 });
  });

  it('renders the table with NE/EN rows', async () => {
    render(<AdminTranslationsPage />);
    await waitFor(() => {
      expect(screen.getByText('auth.invalid_credentials')).toBeTruthy();
      expect(screen.getByText('common.save')).toBeTruthy();
    });
    expect(screen.getByDisplayValue('Incorrect email or password')).toBeTruthy();
    expect(screen.getByDisplayValue('सुरक्षित गर्नुहोस्')).toBeTruthy();
  });

  it('saves an edited NE value via PUT and refreshes the overlay', async () => {
    render(<AdminTranslationsPage />);
    await waitFor(() => expect(screen.getByText('common.save')).toBeTruthy());

    const textareas = screen.getAllByRole('textbox');
    fireEvent.change(textareas[4], { target: { value: 'बचत गर्नुहोस्' } });

    const saveButton = await waitFor(() => {
      const buttons = screen.getAllByRole('button');
      const save = buttons.find((b) => b.textContent === 'adminTranslations.save' && !(b as HTMLButtonElement).disabled);
      if (!save) throw new Error('save button still disabled');
      return save;
    });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(translationAdminApi.upsert).toHaveBeenCalledWith('common.save', {
        en: 'Save',
        ne: 'बचत गर्नुहोस्',
      });
      expect(refreshTranslations).toHaveBeenCalled();
    });
  });

  it('searches via the search input', async () => {
    render(<AdminTranslationsPage />);
    await waitFor(() => expect(screen.getByText('common.save')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('adminTranslations.search'), {
      target: { value: 'invalid_credentials' },
    });
    fireEvent.keyDown(screen.getByPlaceholderText('adminTranslations.search'), { key: 'Enter' });

    await waitFor(() => {
      expect(translationAdminApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: 'invalid_credentials', page: 1 }),
      );
    });
  });

  it('shows the note saying where a sentence appears, read-only, under its key', async () => {
    (translationAdminApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: 9,
          key: 'yearlyPlan.next.NO_LOCATION.text',
          en: 'Show where',
          ne: 'कहाँ',
          context: 'Next-step card when an activity has no place. {{activity}} = activity name.',
          source_file: 'bundle',
          is_override: false,
          reviewed: false,
          history_count: 0,
          updated_by: null,
        },
      ],
      total: 1,
      page: 1,
      per_page: 50,
    });
    render(<AdminTranslationsPage />);
    const note = await screen.findByTestId('translation-context');
    expect(note.textContent).toContain('Next-step card when an activity has no place');
    // read-only: it is text, not an input
    expect(note.querySelector('textarea, input')).toBeNull();
  });

  it('shows the reason the server gave when an edit is refused (for example a dropped {{placeholder}})', async () => {
    const { message } = await import('antd');
    const errorSpy = vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
    (translationAdminApi.upsert as unknown as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: {
        data: {
          detail: {
            code: 'translations.placeholder_missing',
            message: 'This wording drops {{activity}}, which the message needs.',
            message_np: 'यो पाठले {{activity}} छोडेको छ।',
          },
        },
      },
    });
    render(<AdminTranslationsPage />);
    await waitFor(() => expect(screen.getByText('common.save')).toBeTruthy());
    fireEvent.change(screen.getAllByRole('textbox')[4], { target: { value: 'बचत' } });
    const save = await waitFor(() => {
      const found = screen
        .getAllByRole('button')
        .find((b) => b.textContent === 'adminTranslations.save' && !(b as HTMLButtonElement).disabled);
      if (!found) throw new Error('save button still disabled');
      return found;
    });
    fireEvent.click(save);
    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    expect(String(errorSpy.mock.calls[0][0])).toContain('{{activity}}');
    expect(String(errorSpy.mock.calls[0][0])).not.toBe('adminTranslations.saveFailed');
  });
});
