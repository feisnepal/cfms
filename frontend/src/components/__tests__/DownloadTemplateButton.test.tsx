import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const downloadTemplates = vi.fn();
const messageError = vi.fn();
vi.mock('../../services/api', () => ({ uploadApi: { downloadTemplates: (u: string) => downloadTemplates(u) } }));
vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  return { ...actual, message: { ...actual.message, error: (m: string) => messageError(m) } };
});

import DownloadTemplateButton from '../DownloadTemplateButton';

describe('DownloadTemplateButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    downloadTemplates.mockResolvedValue(undefined);
  });

  it('downloads the templates with ropani as the default household unit', async () => {
    render(<DownloadTemplateButton />);
    fireEvent.click(screen.getByRole('button', { name: /Download data template/i }));
    await waitFor(() => expect(downloadTemplates).toHaveBeenCalledWith('ropani'));
  });

  it('offers kaththa from the menu', async () => {
    render(<DownloadTemplateButton />);
    fireEvent.click(screen.getByRole('button', { name: 'Template options' }));
    fireEvent.click(await screen.findByText('Households in kaththa'));
    await waitFor(() => expect(downloadTemplates).toHaveBeenCalledWith('kaththa'));
  });

  it('says so when the download fails, and can be used again', async () => {
    downloadTemplates.mockRejectedValueOnce(new Error('boom'));
    render(<DownloadTemplateButton />);
    const button = screen.getByRole('button', { name: /Download data template/i });
    fireEvent.click(button);
    await waitFor(() => expect(messageError).toHaveBeenCalledWith('Could not download the templates. Please try again.'));
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(downloadTemplates).toHaveBeenCalledTimes(2));
  });

  it('explains what the zip holds in its tooltip', () => {
    render(<DownloadTemplateButton />);
    expect(screen.getByRole('button', { name: /Download data template/i }).getAttribute('title')).toContain('coordinate-system');
  });
});
