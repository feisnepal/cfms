/**
 * TreeModelPanel — the `treemodel` context, composed.
 *
 * The `treemodel` context is the one surface that is not a single component:
 * `SamplingModelTab` rendered the generator and the all-tree-export accordion
 * together inside one padded block. Keeping that composition here (rather than in
 * a lambda inside `contextComponents.tsx`) means it can be code-split like every
 * other context, and means the resolver map stays a flat id -> node lookup with
 * no inline JSX to untangle when the mapping changes in P2b.
 */
import React from 'react';
import TreeModelGenerator, { TotalTreeExportAccordion } from '../../../components/TreeModelGenerator';
import { hasCompartmentsFromResultData } from '../../../hooks/useDimensionLabels';

interface TreeModelPanelProps {
  calculationId: string;
  calculation?: any;
}

const TreeModelPanel: React.FC<TreeModelPanelProps> = ({ calculationId, calculation }) => {
  const hasCompartments = hasCompartmentsFromResultData(
    calculation?.result_data as unknown as Record<string, unknown> | null | undefined,
  );

  return (
    <div className="p-6 space-y-4">
      <TreeModelGenerator
        calculationId={calculationId}
        forestName={calculation?.forest_name || undefined}
        hasCompartments={hasCompartments}
      />
      <TotalTreeExportAccordion calculationId={calculationId} />
    </div>
  );
};

export default TreeModelPanel;
