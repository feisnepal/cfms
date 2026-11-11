/**
 * The label of a row of the tree analysis: the unit the row IS, by its own name - exactly what the attribute table shows for that unit
 * (owner, 2026-10-15). It used to be the whole path "compartment > sub-compartment", whose first part is often a long system-made name
 * ("बनस्खन्डी - Compartment 1 > बनस्खन्डी - Compartment 1-SC2_merged") that is nowhere in the attribute table.
 *
 * The server sends `unit_name` (looked up from the units as they are now); older data without it falls back to the same rule here: the
 * sub-compartment, else the compartment, else the block.
 */
export function getHierarchyPath(row: {
  unit_name?: string;
  block_name?: string;
  compartment?: string;
  sub_compartment?: string;
}): string {
  const real = (v?: string) => (v && v.trim() && v !== '-' ? v : '');
  return real(row.unit_name) || real(row.sub_compartment) || real(row.compartment) || real(row.block_name) || '-';
}

/** Truncate label for chart axis */
export function truncateLabel(label: string, max = 28): string {
  return label.length > max ? label.substring(0, max - 3) + '...' : label;
}
