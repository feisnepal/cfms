import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect } from 'vitest';
import { StructureStaleBanner } from '../StructureStaleBanner';

describe('StructureStaleBanner (FS-1b.7)', () => {
  it('renders nothing when result_data has no structure_stale key', () => {
    render(<StructureStaleBanner resultData={{ blocks: [] }} />);
    expect(screen.queryByTestId('structure-stale-banner')).toBeNull();
  });

  it('renders nothing when result_data is null/undefined', () => {
    render(<StructureStaleBanner resultData={null} />);
    expect(screen.queryByTestId('structure-stale-banner')).toBeNull();
    render(<StructureStaleBanner resultData={undefined} />);
    expect(screen.queryAllByTestId('structure-stale-banner')).toHaveLength(0);
  });

  it('renders nothing when every stale domain is false', () => {
    render(
      <StructureStaleBanner
        resultData={{ structure_stale: { analysis: false, sampling: false, field_inventory: false } }}
      />,
    );
    expect(screen.queryByTestId('structure-stale-banner')).toBeNull();
  });

  it('renders when at least one domain is stale', () => {
    render(
      <StructureStaleBanner
        resultData={{
          structure_stale: { analysis: true, sampling: false, since: '2026-09-22T00:00:00Z', change: 'divide C1' },
        }}
      />,
    );
    expect(screen.getByTestId('structure-stale-banner')).toBeInTheDocument();
  });

  it('names only the domains that are actually flagged', () => {
    render(
      <StructureStaleBanner
        resultData={{
          structure_stale: {
            analysis: false,
            sampling: true,
            field_inventory: true,
            since: '2026-09-22T00:00:00Z',
          },
        }}
      />,
    );
    const strip = screen.getByTestId('structure-stale-banner');
    expect(strip.textContent).toContain('Sampling');
    expect(strip.textContent).toContain('Field inventory');
    // A domain with no data behind it is never named — this is the "why do I
    // always see this ribbon" fix: a field-inventory-only forest is not told to
    // re-run analysis or sampling.
    expect(strip.textContent).not.toContain('Analysis');
  });

  it('is dismissible, and a NEW structural change brings it back', async () => {
    const { rerender } = render(
      <StructureStaleBanner
        resultData={{ structure_stale: { analysis: true, since: '2026-09-22T00:00:00Z' } }}
      />,
    );
    expect(screen.getByTestId('structure-stale-banner')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Dismiss this notice' }));
    expect(screen.queryByTestId('structure-stale-banner')).toBeNull();

    // Same change re-fetched (the page polls) -- stays dismissed.
    rerender(
      <StructureStaleBanner
        resultData={{ structure_stale: { analysis: true, since: '2026-09-22T00:00:00Z' } }}
      />,
    );
    expect(screen.queryByTestId('structure-stale-banner')).toBeNull();

    // A divide after the dismissal bumps `since` -- the warning returns.
    rerender(
      <StructureStaleBanner
        resultData={{ structure_stale: { analysis: true, since: '2026-09-23T10:00:00Z' } }}
      />,
    );
    expect(screen.getByTestId('structure-stale-banner')).toBeInTheDocument();
  });

  it('keeps the long explanation out of the permanent text', () => {
    render(
      <StructureStaleBanner
        resultData={{ structure_stale: { analysis: true, since: '2026-09-22T00:00:00Z' } }}
      />,
    );
    // One line: the short title + the domain names, plus the dismiss glyph. The
    // long explanation is in the tooltip, so it costs no permanent height.
    expect(screen.getByTestId('structure-stale-banner').textContent).toBe(
      'Structure changedAnalysis×',
    );
  });
});
