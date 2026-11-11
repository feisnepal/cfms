import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import NtfpStagesStrip from '../NtfpStagesStrip';
import { ntfpStages } from '../../../lib/ntfp';

const stages = ntfpStages({ picked: 0, designSpecies: 3, plots: 36, hasDesign: true, recorded: 40, assigned: 108, plannedRows: null });

describe('NtfpStagesStrip', () => {
  it('says the survey is optional and names the five stages', () => {
    render(<NtfpStagesStrip stages={stages} active="collect" onSelect={() => {}} />);
    expect(screen.getByText(/This survey is optional: the plan can be finished without it/)).toBeInTheDocument();
    for (const name of ['Choose species', 'Lay out plots', 'Bring in findings', 'Read results', 'Plan the harvest']) expect(screen.getByText(name)).toBeInTheDocument();
  });

  it('says on each stage where it stands and what it needs', () => {
    render(<NtfpStagesStrip stages={stages} active="collect" onSelect={() => {}} />);
    expect(screen.getByTestId('ntfp-stage-species')).toHaveTextContent('3 species in the design');
    expect(screen.getByTestId('ntfp-stage-design')).toHaveTextContent('36 plots laid out');
    expect(screen.getByTestId('ntfp-stage-collect')).toHaveTextContent('40 of 108 recorded');
    expect(screen.getByTestId('ntfp-stage-harvest')).toHaveTextContent('No harvest planned yet');
    expect(screen.getByTestId('ntfp-stage-collect')).toHaveAttribute('data-status', 'current');
    expect(screen.getByTestId('ntfp-stage-species')).toHaveAttribute('data-status', 'done');
  });

  it('takes the person to a stage when it is clicked, even one that is waiting (nothing is locked)', () => {
    const onSelect = vi.fn();
    const early = ntfpStages({ picked: 0, designSpecies: 0, plots: 0, hasDesign: false, recorded: 0, assigned: 0, plannedRows: null });
    render(<NtfpStagesStrip stages={early} active="species" onSelect={onSelect} />);
    expect(screen.getByTestId('ntfp-stage-results')).toHaveTextContent('Needs findings first');
    fireEvent.click(screen.getByText('Read results'));
    expect(onSelect).toHaveBeenCalledWith('results');
  });
});
