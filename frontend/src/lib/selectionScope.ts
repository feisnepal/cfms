// A unit (block / compartment) that is not divided further is ONE record shown in two
// layers (Compartments and Sub-Compartments; Blocks and Sub-Blocks). Selecting it in
// either layer must read as selected in the other: the map already highlights by feature
// id, so the attribute table has to agree or the user sees a highlighted polygon with an
// unselected row (owner report 2026-10-03, SUBCOMPARTMENT_LAYER_TRACKER.md SL-4).
// Feature ids are UUIDs, unique across these layers, so sharing the ids is safe: a layer
// simply highlights the rows it actually contains.
const UNIT_LAYER_IDS = new Set(['blocks', 'sub_blocks', 'compartments', 'sub_compartments']);

export function selectedIdsForLayer(
  selection: { layerId: string | null; featureIds: string[] },
  layerKey: string | null,
): string[] {
  if (!layerKey || !selection.layerId) return [];
  if (selection.layerId === layerKey) return selection.featureIds;
  if (UNIT_LAYER_IDS.has(selection.layerId) && UNIT_LAYER_IDS.has(layerKey)) return selection.featureIds;
  return [];
}
