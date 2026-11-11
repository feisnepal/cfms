import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import PurposePickerDialog from '../PurposePickerDialog';

describe('PurposePickerDialog — draw with purpose (Phase 6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('restrictToGeometry offers only Forest Boundary + Blocks purposes', () => {
    render(
      <PurposePickerDialog
        calculationId="calc-1"
        restrictToGeometry
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText('Boundary')).toBeTruthy();
    expect(screen.getByText('Blocks')).toBeTruthy();
    expect(screen.queryByText('Tree Inventory')).toBeNull();
    expect(screen.queryByText('Sample Plot')).toBeNull();
    expect(screen.queryByText('Roads & Trails')).toBeNull();
  });

  it('offers all purposes when not restricted', () => {
    render(
      <PurposePickerDialog
        calculationId="calc-1"
        onCreated={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText('Tree Inventory')).toBeTruthy();
    expect(screen.getByText('Sample Plot')).toBeTruthy();
    expect(screen.getByText('Roads & Trails')).toBeTruthy();
  });
});