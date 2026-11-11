/**
 * The overlays that ride on a unit layer's features (SFM type, hazard classes, field-inventory numbers, the active unit map, raster
 * analysis). The attribute table shows the features WITH these merged in; one function does it so the table and every export
 * agree on what a unit row holds.
 */
import type { Feature } from 'geojson';
import { mergeSfmProps } from './sfmFeatureProps';
import { mergeHazardProps } from './hazardFeatureProps';
import { mergeAnalysisProps, mergeUnitProps } from './unitMapProps';

export const isUnitLayerType = (layerType: string): boolean =>
  layerType === 'blocks' || layerType === 'sub_blocks' || layerType === 'compartments' || layerType === 'sub_compartments';

interface UnitOverlays {
  sfmBlockTypes: Parameters<typeof mergeSfmProps>[1];
  hazardUnits: Parameters<typeof mergeHazardProps>[1];
  unitMap: Parameters<typeof mergeUnitProps>[1];
  fieldInventoryUnits: Parameters<typeof mergeUnitProps>[2];
  unitAnalysis: Parameters<typeof mergeAnalysisProps>[1];
}

export function mergeUnitLayerProps(data: Feature[] | null, s: UnitOverlays): Feature[] | null {
  return mergeAnalysisProps(
    mergeUnitProps(mergeHazardProps(mergeSfmProps(data, s.sfmBlockTypes), s.hazardUnits), s.unitMap, s.fieldInventoryUnits),
    s.unitAnalysis,
  );
}
