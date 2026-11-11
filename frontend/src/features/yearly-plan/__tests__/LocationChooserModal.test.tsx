/**
 * Where an activity applies, on the yearly-activities pages (YEARLY_ACTIVITIES plan P5): the whole forest, or chosen
 * blocks / sub-areas. Choosing "all blocks" also sets the whole-forest flag the plan table and the plan check read.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { message } from 'antd';
import en from '../../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    const node = lookup(key);
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../../../components/YearlyActivities/BlockSubAreaSelector', () => ({
  default: ({
    selectedAllBlocks,
    selectedBlocks,
    selectedSubAreas,
    onChange,
  }: {
    selectedAllBlocks: boolean;
    selectedBlocks: string[];
    selectedSubAreas: string[];
    onChange: (type: 'all' | 'block' | 'sub_area', id?: string, checked?: boolean) => void;
  }) => (
    <div data-testid="selector" data-all={String(selectedAllBlocks)} data-blocks={selectedBlocks.join(',')} data-subareas={selectedSubAreas.join(',')}>
      <button onClick={() => onChange('all', undefined, true)}>pick-all</button>
      <button onClick={() => onChange('block', 'B2', true)}>pick-block-B2</button>
      <button onClick={() => onChange('sub_area', 'S1', true)}>pick-subarea-S1</button>
    </div>
  ),
}));
vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { getUnits: vi.fn() },
  yearlyActivitiesApi: {
    getSpatialAssignments: vi.fn(),
    createSpatialAssignment: vi.fn(),
    deleteSpatialAssignment: vi.fn(),
    updateProposedActivity: vi.fn(),
  },
}));

import { yearlyActivitiesApi, yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { LocationChooserModal } from '../LocationChooserModal';

const acts = yearlyActivitiesApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const plan = yearlyPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const line = (over: Partial<YearlyPlanLine> = {}) => ({ id: 'L1', assign_to_all_blocks: false, ...over }) as YearlyPlanLine;

beforeEach(() => {
  vi.clearAllMocks();
  plan.getUnits.mockResolvedValue([{ block_id: 'B1', block_name: 'C-1', sub_areas: [{ id: 'S1', name: 'Patch', category: 'x' }] }]);
  acts.getSpatialAssignments.mockResolvedValue([]);
  acts.createSpatialAssignment.mockResolvedValue({});
  acts.deleteSpatialAssignment.mockResolvedValue({});
  acts.updateProposedActivity.mockResolvedValue({});
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
});

const saveButton = () => screen.getByRole('button', { name: 'Save' });

describe('LocationChooserModal', () => {
  it('stays closed until a line is given, then opens with nothing ticked when nothing is assigned', async () => {
    const { rerender } = render(<LocationChooserModal calculationId="c1" line={null} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.queryByTestId('selector')).toBeNull();
    rerender(<LocationChooserModal calculationId="c1" line={line()} onClose={vi.fn()} onSaved={vi.fn()} />);
    const selector = await screen.findByTestId('selector');
    expect(selector).toHaveAttribute('data-all', 'false'); // the plan table says "not shown on the map yet"
    expect(selector).toHaveAttribute('data-blocks', '');
  });

  it('opens with "all blocks" when the line is marked as the whole forest', async () => {
    render(<LocationChooserModal calculationId="c1" line={line({ assign_to_all_blocks: true })} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(await screen.findByTestId('selector')).toHaveAttribute('data-all', 'true');
  });

  it('opens with the blocks and sub-areas already assigned', async () => {
    acts.getSpatialAssignments.mockResolvedValue([
      { id: 'A1', block_id: 'B1', assignment_type: 'block' },
      { id: 'A2', block_id: 'B1', sub_area_id: 'S1', assignment_type: 'sub_area' },
    ]);
    render(<LocationChooserModal calculationId="c1" line={line()} onClose={vi.fn()} onSaved={vi.fn()} />);
    const selector = await screen.findByTestId('selector');
    expect(selector).toHaveAttribute('data-all', 'false');
    expect(selector).toHaveAttribute('data-blocks', 'B1');
    expect(selector).toHaveAttribute('data-subareas', 'S1');
  });

  it('"all blocks" replaces the earlier assignments and sets the whole-forest flag', async () => {
    acts.getSpatialAssignments.mockResolvedValue([{ id: 'A1', block_id: 'B1', assignment_type: 'block' }]);
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<LocationChooserModal calculationId="c1" line={line()} onClose={onClose} onSaved={onSaved} />);
    await screen.findByTestId('selector');
    fireEvent.click(screen.getByText('pick-all'));
    fireEvent.click(saveButton());
    await waitFor(() => expect(acts.updateProposedActivity).toHaveBeenCalledWith('L1', { assign_to_all_blocks: true }));
    expect(acts.deleteSpatialAssignment).toHaveBeenCalledWith('L1', 'A1');
    expect(acts.createSpatialAssignment).toHaveBeenCalledWith('L1', { assignment_type: 'all_blocks' });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('chosen blocks and sub-areas are assigned, and the whole-forest flag is cleared', async () => {
    render(<LocationChooserModal calculationId="c1" line={line({ assign_to_all_blocks: true })} onClose={vi.fn()} onSaved={vi.fn()} />);
    await screen.findByTestId('selector');
    fireEvent.click(screen.getByText('pick-block-B2'));
    fireEvent.click(screen.getByText('pick-subarea-S1'));
    fireEvent.click(saveButton());
    await waitFor(() => expect(acts.updateProposedActivity).toHaveBeenCalledWith('L1', { assign_to_all_blocks: false }));
    expect(acts.createSpatialAssignment).toHaveBeenCalledWith('L1', { block_id: 'B2', assignment_type: 'block' });
    expect(acts.createSpatialAssignment).toHaveBeenCalledWith('L1', { block_id: 'B1', sub_area_id: 'S1', assignment_type: 'sub_area' });
  });

  it('a failed save says so in plain words, keeps the chooser open and tells nobody the plan changed', async () => {
    acts.updateProposedActivity.mockRejectedValue(Object.assign(new Error('relation x'), { response: { status: 500 } }));
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<LocationChooserModal calculationId="c1" line={line()} onClose={onClose} onSaved={onSaved} />);
    await screen.findByTestId('selector');
    fireEvent.click(saveButton());
    await waitFor(() => expect(message.error).toHaveBeenCalled());
    expect(String((message.error as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0])).not.toContain('relation');
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
