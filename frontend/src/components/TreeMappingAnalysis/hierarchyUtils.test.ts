import { describe, expect, it } from 'vitest';
import { getHierarchyPath } from './hierarchyUtils';

describe('the label of a row in the tree analysis', () => {
  it('is the unit the row is, by its own name - not the "compartment > sub-compartment" path', () => {
    expect(
      getHierarchyPath({
        unit_name: 'l',
        block_name: 'बनस्खन्डी - Compartment 1',
        compartment: 'बनस्खन्डी - Compartment 1',
        sub_compartment: 'l',
      }),
    ).toBe('l');
  });

  it('uses the unit_name the server looked up from the units as they are now', () => {
    expect(getHierarchyPath({ unit_name: 'e', compartment: 'x', sub_compartment: 'y' })).toBe('e');
  });

  it('without unit_name (older data) takes the sub-compartment, else the compartment, else the block', () => {
    expect(getHierarchyPath({ block_name: 'B1', compartment: 'C-2', sub_compartment: 'SC-3' })).toBe('SC-3');
    expect(getHierarchyPath({ block_name: 'B1', compartment: 'C-2', sub_compartment: '-' })).toBe('C-2');
    expect(getHierarchyPath({ block_name: 'B1', compartment: '-', sub_compartment: '-' })).toBe('B1');
  });

  it('says "-" for trees that fell in no unit', () => {
    expect(getHierarchyPath({ block_name: '-', compartment: '-', sub_compartment: '-', unit_name: '-' })).toBe('-');
    expect(getHierarchyPath({})).toBe('-');
  });

  it('ignores blanks', () => {
    expect(getHierarchyPath({ unit_name: '  ', sub_compartment: '', compartment: 'C-1' })).toBe('C-1');
  });
});
