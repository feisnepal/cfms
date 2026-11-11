/** Every upload screen says whether the data is already in the system (owner decision D3). */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

import { UploadStateLine } from '../UploadStateLine';

describe('UploadStateLine', () => {
  it('says the data is not in the system', () => {
    render(<UploadStateLine present={false} detail="ignored" />);
    const line = screen.getByTestId('upload-state-line');
    expect(line.getAttribute('data-present')).toBe('false');
    expect(line.textContent).toContain('uploadState.notInSystem');
    expect(line.textContent).not.toContain('ignored'); // a detail only makes sense when something is there
  });

  it('says the data is in the system, and what it is', () => {
    render(<UploadStateLine present detail="census.csv" />);
    const line = screen.getByTestId('upload-state-line');
    expect(line.getAttribute('data-present')).toBe('true');
    expect(line.textContent).toContain('uploadState.inSystem');
    expect(line.textContent).toContain('census.csv');
  });
});
