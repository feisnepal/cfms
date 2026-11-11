/**
 * SubAreaTablesTab — the read-only area-accounting tables that used to live in
 * the legacy `CalculationDetail.tsx` sub-areas tab. Single Workspace task A5c.
 *
 * The `subareas` context renders the map workspace (drawing + editing);
 * this `areadetail` context is the statutory area breakdown: Table 1
 * (sub-areas), Table 2 / 3 (block-wise area description, from
 * `getBlockAreaDetail`), plus the OP document-variable tags. No map, no
 * "Add Sub-Area" — those are in the workspace.
 *
 * Ported from the deleted legacy page — kept in `hardcodedStrings`
 * LEGACY_PREFIXES, same rule-9 Nepali deferral as `AnalysisTab`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import * as turf from '@turf/turf';
import { forestApi } from '../../services/api';
import type { Calculation, SubArea } from '../../types';
import CopyTag from '../DetailDescription/CopyTag';
import { PromoteToProtectionUnitButton } from './PromoteToProtectionUnitButton';
import { DemoteProtectionUnitButton } from './DemoteProtectionUnitButton';
import { useDimensionLabels, hasCompartmentsFromResultData, analysisUnitKey } from '../../hooks/useDimensionLabels';
import { useT } from '../../i18n/hooks';

interface BlockAreaRow {
  block_name: string;
  total_area_ha?: number;
  tree_cover_area_ha?: number;
  other_landcover_area_ha?: number;
  protected_area_ha?: number;
  private_land_area_ha?: number;
  effective_area_ha?: number;
}
type BlockAreaTotals = Omit<BlockAreaRow, 'block_name'>;
interface BlockAreaResponse {
  block_details?: BlockAreaRow[];
  totals?: BlockAreaTotals | null;
}

interface BlockBreakdown {
  blockId?: string;
  block_id?: string;
  blockName?: string;
  area: number;
  percentage: number;
}

interface SubAreaTablesTabProps {
  calculationId: string;
  calculation?: Calculation | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  private_land: 'Private Land',
  protected: 'Protected',
  plantation: 'Plantation',
  religious: 'Religious',
  biodiversity: 'Biodiversity',
  'pro-poor': 'Pro-Poor',
  tourist: 'Tourist',
  office: 'Office',
};

const n = (v: number | undefined, digits = 2): string => (v ?? 0).toFixed(digits);

export default function SubAreaTablesTab({ calculationId, calculation: calcProp }: SubAreaTablesTabProps) {
  const t = useT();
  const [calc, setCalc] = useState<Calculation | null>(calcProp ?? null);
  const [loadingCalc, setLoadingCalc] = useState(!calcProp);
  const [rows, setRows] = useState<BlockAreaRow[]>([]);
  const [totals, setTotals] = useState<BlockAreaTotals | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  // Bumped after a promote/demote so both fetch effects re-run.
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = useCallback(async () => {
    if (!calculationId) return;
    const data = await forestApi.getCalculation(calculationId);
    setCalc(data);
    setReloadKey((k) => k + 1);
  }, [calculationId]);

  useEffect(() => {
    if (calcProp && reloadKey === 0) {
      setCalc(calcProp);
      return;
    }
    if (!calculationId) return;
    let cancelled = false;
    setLoadingCalc(true);
    forestApi
      .getCalculation(calculationId)
      .then((data: Calculation) => {
        if (!cancelled) setCalc(data);
      })
      .catch(() => {
        if (!cancelled) setCalc(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingCalc(false);
      });
    return () => {
      cancelled = true;
    };
  }, [calculationId, calcProp, reloadKey]);

  // Compartment-divided forests analyse per compartment (backend PolygonSource);
  // read the SAME units here so Tables 1-3 are compartment-wise, not the parent
  // block. Falls back to `blocks` when no compartments array is populated.
  const unitKey = analysisUnitKey(
    calc?.result_data as unknown as Record<string, unknown> | null | undefined,
  );
  const blocks = useMemo(
    () =>
      (calc?.result_data?.[unitKey] ?? []) as Array<{
        block_id?: string;
        block_name: string;
        working_circle?: string;
        geometry?: { type?: string; coordinates?: unknown };
      }>,
    [calc?.result_data, unitKey],
  );
  const protectionUnits = useMemo(
    () => blocks.filter((b) => b.working_circle === 'protection'),
    [blocks],
  );
  const circleOf = useMemo(() => {
    const m = new Map<string, string>();
    blocks.forEach((b) => b.block_name && m.set(b.block_name, b.working_circle || 'production'));
    return m;
  }, [blocks]);
  const subAreas = useMemo<SubArea[]>(() => calc?.result_data?.sub_areas ?? [], [calc?.result_data]);
  const hasBlocks = blocks.length > 0;

  useEffect(() => {
    if (!calc?.id || !hasBlocks) {
      setRows([]);
      setTotals(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    forestApi
      .getBlockAreaDetail(calc.id)
      .then((data: BlockAreaResponse) => {
        if (cancelled) return;
        setRows(data.block_details ?? []);
        setTotals(data.totals ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setRows([]);
        setTotals(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [calc?.id, hasBlocks, reloadKey]);

  const hasCompartments = hasCompartmentsFromResultData(
    calc?.result_data as unknown as Record<string, unknown> | null | undefined,
  );
  const labels = useDimensionLabels({ hasCompartments });

  const lookupBlockName = (blockId?: string, fallback?: string): string => {
    if (!blockId) return fallback || '-';
    const match = blocks.find((b) => b.block_id === blockId);
    return match?.block_name || fallback || '-';
  };

  // A sub-area records only its parent *block* id/name. After the block is
  // divided the analysed units are compartments, so that stored ref no longer
  // names a unit and Table 1's unit column would keep showing the old block
  // name. When the refs no longer line up with the units, resolve each
  // sub-area's unit(s) geometrically — the same basis the backend area tables
  // use. A no-op for every forest whose sub-areas are tagged correctly.
  const toPolyFeature = (
    geom: { type?: string; coordinates?: unknown } | null | undefined,
  ): GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null => {
    if (!geom || !geom.coordinates) return null;
    try {
      if (geom.type === 'Polygon') {
        return turf.polygon(geom.coordinates as GeoJSON.Position[][]);
      }
      if (geom.type === 'MultiPolygon') {
        return turf.multiPolygon(geom.coordinates as GeoJSON.Position[][][]);
      }
    } catch {
      /* malformed coordinates — treat as unresolvable */
    }
    return null;
  };

  const unitFeatures = useMemo(
    () =>
      blocks
        .map((b) => {
          const feat = toPolyFeature(b.geometry);
          return feat ? { name: b.block_name, feat } : null;
        })
        .filter((x): x is { name: string; feat: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> } => x !== null),
    [blocks],
  );

  const refsMisaligned = useMemo(() => {
    if (subAreas.length === 0 || blocks.length === 0) return false;
    const unitNames = new Set(blocks.map((b) => b.block_name).filter(Boolean));
    return !subAreas.some((sa) => {
      const bb = (sa.blockBreakdown || sa.block_breakdown || []) as Array<{ blockName?: string }>;
      return (
        unitNames.has(sa.blockName as string) ||
        unitNames.has(sa.block_name as string) ||
        bb.some((i) => unitNames.has(i.blockName as string))
      );
    });
  }, [subAreas, blocks]);

  const geomBreakdowns = useMemo<Array<Array<{ name: string; area: number; percentage: number }>>>(() => {
    if (!refsMisaligned) return subAreas.map(() => []);
    return subAreas.map((sa) => {
      const saFeat = toPolyFeature(sa.geometry as { type?: string; coordinates?: unknown });
      if (!saFeat) return [];
      let saArea = 0;
      try {
        saArea = turf.area(saFeat);
      } catch {
        /* leave saArea at 0 -> percentages fall back to 0 */
      }
      const parts: Array<{ name: string; area: number; percentage: number }> = [];
      for (const u of unitFeatures) {
        try {
          const inter = turf.intersect(turf.featureCollection([saFeat, u.feat]));
          if (!inter) continue;
          const m2 = turf.area(inter);
          if (m2 < 1) continue;
          parts.push({
            name: u.name,
            area: m2 / 10000,
            percentage: saArea > 0 ? (m2 / saArea) * 100 : 0,
          });
        } catch {
          /* bad geometry pair — skip this unit */
        }
      }
      parts.sort((a, b) => b.area - a.area);
      return parts;
    });
  }, [refsMisaligned, subAreas, unitFeatures]);

  if (loadingCalc) {
    return <div className="p-6 text-gray-500">{t('common.loading')}</div>;
  }
  if (!calc) {
    return <div className="p-6 text-red-600">Area data is not available for this calculation.</div>;
  }
  if (!hasBlocks) {
    return (
      <div className="p-6">
        <div className="text-center py-12 bg-gray-50 rounded-lg">
          <p className="text-gray-500">No {labels.unitLabelPluralLower} defined yet.</p>
          <p className="text-sm text-gray-400 mt-1">Upload a boundary file or create on map first.</p>
        </div>
      </div>
    );
  }

  const subAreasTotal = subAreas.reduce((sum, sa) => sum + parseFloat(String(sa.area_hectares ?? 0)), 0);

  return (
    <div className="sub-area-tables-tab p-6 space-y-6">
      {/* Table 1: Sub-Areas Detail */}
      {subAreas.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="bg-purple-50 px-4 py-2 border-b border-gray-200">
            <h4 className="text-sm font-semibold text-purple-800">Table 1: Sub-Areas Detail</h4>
          </div>
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Sub-Area Name</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Area (ha)</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{labels.unitNameHeaderEn}</th>
                <th className="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {subAreas.map((sa, idx) => {
                const bd = (sa.blockBreakdown || sa.block_breakdown) as BlockBreakdown[] | undefined;
                const isCrossBlock = !!bd && bd.length > 1;
                const currentBlockName = lookupBlockName(
                  sa.blockId || sa.block_id,
                  sa.blockName || sa.block_name,
                );
                const geomParts = geomBreakdowns[idx] ?? [];
                const excluded = sa.isExcluded || sa.is_excluded;
                return (
                  <tr key={sa.id ?? idx} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm font-medium text-gray-900">{sa.name}</td>
                    <td className="px-4 py-2 text-sm text-gray-500">
                      {sa.category ? CATEGORY_LABELS[sa.category] ?? sa.category : '-'}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-900 text-right">
                      {(sa.area_hectares ?? 0).toFixed(4)}
                    </td>
                    <td className="px-4 py-2 text-sm">
                      {refsMisaligned && geomParts.length > 0 ? (
                        geomParts.length === 1 ? (
                          <span className="text-gray-500">{geomParts[0].name}</span>
                        ) : (
                          <div className="text-xs space-y-0.5">
                            {geomParts.map((p, i) => (
                              <div key={i} className="text-gray-600">
                                <span className="font-medium">{p.name}</span>
                                : {p.area.toFixed(2)} ha ({p.percentage.toFixed(1)}%)
                              </div>
                            ))}
                          </div>
                        )
                      ) : refsMisaligned ? (
                        <span className="text-gray-400 italic" title="Could not resolve compartment geometrically">
                          {currentBlockName}
                        </span>
                      ) : isCrossBlock ? (
                        <div className="text-xs space-y-0.5">
                          {bd!.map((b, i) => (
                            <div key={i} className="text-gray-600">
                              <span className="font-medium">
                                {lookupBlockName(b.blockId || b.block_id, b.blockName)}
                              </span>
                              : {b.area.toFixed(2)} ha ({b.percentage.toFixed(1)}%)
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="text-gray-500">{currentBlockName}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-center">
                      {excluded ? (
                        <span className="px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800">
                          Excluded
                        </span>
                      ) : (
                        <span className="px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800">
                          Included
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-left">
                      {sa.category === 'protected' && sa.id != null && (
                        <PromoteToProtectionUnitButton
                          calculationId={calculationId}
                          subAreaId={String(sa.id)}
                          subAreaName={sa.name}
                          onDone={refresh}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
              <tr className="bg-gray-100 font-semibold">
                <td className="px-4 py-2 text-sm text-gray-900" colSpan={2}>
                  SUB-AREAS TOTAL
                </td>
                <td className="px-4 py-2 text-sm text-gray-900 text-right">{subAreasTotal.toFixed(2)}</td>
                <td className="px-4 py-2" />
                <td className="px-4 py-2" />
                <td className="px-4 py-2" />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Protection Working Circle units (P5) */}
      {protectionUnits.length > 0 && (
        <div className="bg-white rounded-lg border border-emerald-200 overflow-hidden">
          <div className="bg-emerald-50 px-4 py-2 border-b border-emerald-200">
            <h4 className="text-sm font-semibold text-emerald-800">
              {t('protectionUnit.wcHeading')}
            </h4>
            <p className="text-xs text-emerald-700">{t('protectionUnit.wcHint')}</p>
          </div>
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  {labels.unitNameHeaderEn}
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {protectionUnits.map((u) => (
                <tr key={u.block_id ?? u.block_name}>
                  <td className="px-4 py-2 text-sm font-medium text-gray-900">{u.block_name}</td>
                  <td className="px-4 py-2 text-left">
                    {u.block_id != null && (
                      <DemoteProtectionUnitButton
                        calculationId={calculationId}
                        blockId={String(u.block_id)}
                        unitName={u.block_name}
                        onDone={refresh}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Table 2: Block-wise Detailed Area Description */}
      {rows.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="bg-blue-50 px-4 py-2 border-b border-gray-200">
            <h4 className="text-sm font-semibold text-blue-800">
              Table 2: {labels.unitWiseNp('क्षेत्रफलको विस्तृत विवरण')}
            </h4>
            <p className="text-xs text-blue-600">(Block-wise Detailed Area Description)</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-xs">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-2 py-2 text-left font-medium text-gray-500 uppercase">
                    {labels.unitNameHeaderNp}
                    <br />
                    <span className="font-normal text-gray-400">({labels.unitNameHeaderEn})</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    {labels.unitLabelNp} को कुल क्षेत्रफल
                    <br />
                    <span className="font-normal text-gray-400">(Total Area ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    रूखले ढाकेको
                    <br />
                    <span className="font-normal text-gray-400">(Tree Cover ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    अन्यले ढाकेको
                    <br />
                    <span className="font-normal text-gray-400">(Other Landcover ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    संरक्षित क्षेत्र
                    <br />
                    <span className="font-normal text-gray-400">(Protected ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    निजि आवादी
                    <br />
                    <span className="font-normal text-gray-400">(Private Land ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    बहिष्कृत क्षेत्र
                    <br />
                    <span className="font-normal text-gray-400">(Excluded ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    शुद्ध वन क्षेत्रफल
                    <br />
                    <span className="font-normal text-gray-400">(Net Forest ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    प्रभावित क्षेत्र
                    <br />
                    <span className="font-normal text-gray-400">(Effective ha)</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {rows.map((detail, idx) => {
                  const excluded = (detail.protected_area_ha || 0) + (detail.private_land_area_ha || 0);
                  const netForest = (detail.total_area_ha || 0) - excluded;
                  return (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-2 py-2 text-sm font-medium text-gray-900">
                        {detail.block_name}
                        {circleOf.get(detail.block_name) === 'protection' && (
                          <span className="ml-2 px-1.5 py-0.5 text-[10px] font-semibold rounded bg-emerald-100 text-emerald-800">
                            {t('protectionUnit.wcTag')}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-sm text-gray-900 text-right">{n(detail.total_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-green-700 text-right">{n(detail.tree_cover_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-gray-600 text-right">{n(detail.other_landcover_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-orange-600 text-right">{n(detail.protected_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-red-600 text-right">{n(detail.private_land_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-red-700 text-right">{excluded > 0 ? excluded.toFixed(2) : '-'}</td>
                      <td className="px-2 py-2 text-sm text-green-700 font-semibold text-right">{netForest.toFixed(2)}</td>
                      <td
                        className={`px-2 py-2 text-sm font-semibold text-right ${
                          (detail.effective_area_ha || 0) < 0 ? 'text-red-700' : 'text-blue-700'
                        }`}
                      >
                        {n(detail.effective_area_ha)}
                      </td>
                    </tr>
                  );
                })}
                {totals && (
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-2 py-2 text-sm text-gray-900">TOTAL</td>
                    <td className="px-2 py-2 text-sm text-gray-900 text-right">{n(totals.total_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-green-800 text-right">{n(totals.tree_cover_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-gray-800 text-right">{n(totals.other_landcover_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-orange-700 text-right">{n(totals.protected_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-red-700 text-right">{n(totals.private_land_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-red-800 text-right">
                      {((totals.protected_area_ha || 0) + (totals.private_land_area_ha || 0)).toFixed(2)}
                    </td>
                    <td className="px-2 py-2 text-sm text-green-800 text-right">
                      {(
                        (totals.total_area_ha || 0) -
                        (totals.protected_area_ha || 0) -
                        (totals.private_land_area_ha || 0)
                      ).toFixed(2)}
                    </td>
                    <td
                      className={`px-2 py-2 text-sm font-bold text-right ${
                        (totals.effective_area_ha || 0) < 0 ? 'text-red-700' : 'text-blue-700'
                      }`}
                    >
                      {n(totals.effective_area_ha)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Table 3: Community Forests and Block Area Description */}
      {rows.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="bg-amber-50 px-4 py-2 border-b border-gray-200">
            <h4 className="text-sm font-semibold text-amber-800">
              Table 3: सामुदायिक वन तथा वन खण्डको क्षेत्रफल सम्वन्धी विवरण
            </h4>
            <p className="text-xs text-amber-600">(Community Forests and Block Area Description)</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-xs">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-2 py-2 text-left font-medium text-gray-500 uppercase">
                    {labels.unitNameHeaderNp}
                    <br />
                    <span className="font-normal text-gray-400">({labels.unitNameHeaderEn})</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    {labels.unitLabelNp} को कुल क्षेत्रफल
                    <br />
                    <span className="font-normal text-gray-400">(Total Area ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    रूखले ढाकेको
                    <br />
                    <span className="font-normal text-gray-400">(Tree Cover ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    अन्यले ढाकेको
                    <br />
                    <span className="font-normal text-gray-400">(Other Landcover ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    संरक्षित क्षेत्र
                    <br />
                    <span className="font-normal text-gray-400">(Protected ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    निजि आवादी
                    <br />
                    <span className="font-normal text-gray-400">(Private Land ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    {labels.unitLabelNp} को क्षेत्रफल
                    <br />
                    <span className="font-normal text-gray-400">(Official Area ha)</span>
                  </th>
                  <th className="px-2 py-2 text-right font-medium text-gray-500 uppercase">
                    प्रभावित क्षेत्र
                    <br />
                    <span className="font-normal text-gray-400">(Effective ha)</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {rows.map((detail, idx) => {
                  const officialArea = (detail.total_area_ha || 0) - (detail.private_land_area_ha || 0);
                  return (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-2 py-2 text-sm font-medium text-gray-900">
                        {detail.block_name}
                        {circleOf.get(detail.block_name) === 'protection' && (
                          <span className="ml-2 px-1.5 py-0.5 text-[10px] font-semibold rounded bg-emerald-100 text-emerald-800">
                            {t('protectionUnit.wcTag')}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-sm text-gray-900 text-right">{n(detail.total_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-green-700 text-right">{n(detail.tree_cover_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-gray-600 text-right">{n(detail.other_landcover_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-orange-600 text-right">{n(detail.protected_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-red-600 text-right">{n(detail.private_land_area_ha)}</td>
                      <td className="px-2 py-2 text-sm text-purple-700 font-semibold text-right">{officialArea.toFixed(2)}</td>
                      <td
                        className={`px-2 py-2 text-sm font-semibold text-right ${
                          (detail.effective_area_ha || 0) < 0 ? 'text-red-700' : 'text-blue-700'
                        }`}
                      >
                        {n(detail.effective_area_ha)}
                      </td>
                    </tr>
                  );
                })}
                {totals && (
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-2 py-2 text-sm text-gray-900">TOTAL</td>
                    <td className="px-2 py-2 text-sm text-gray-900 text-right">{n(totals.total_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-green-800 text-right">{n(totals.tree_cover_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-gray-800 text-right">{n(totals.other_landcover_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-orange-700 text-right">{n(totals.protected_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-red-700 text-right">{n(totals.private_land_area_ha)}</td>
                    <td className="px-2 py-2 text-sm text-purple-800 font-bold text-right">
                      {((totals.total_area_ha || 0) - (totals.private_land_area_ha || 0)).toFixed(2)}
                    </td>
                    <td
                      className={`px-2 py-2 text-sm font-bold text-right ${
                        (totals.effective_area_ha || 0) < 0 ? 'text-red-700' : 'text-blue-700'
                      }`}
                    >
                      {n(totals.effective_area_ha)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* OP Document Variables */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="bg-gray-100 px-4 py-2 border-b border-gray-200">
          <h4 className="text-sm font-semibold text-gray-700">OP Document Variables</h4>
        </div>
        <div className="px-4 py-3 flex flex-wrap gap-2">
          <CopyTag label="{{sub_areas_detail}}" value="{{sub_areas_detail}}" variant="section" />
          <CopyTag label="{{block_area_detail_merged}}" value="{{block_area_detail_merged}}" variant="section" />
          {subAreas.length > 0 && (
            <CopyTag label="{{map:subarea}}" value="{{map:subarea}}" variant="section" />
          )}
        </div>
      </div>

      {loadingDetail && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center">
          <div className="inline-block animate-spin rounded-full h-6 w-6 border-b-2 border-amber-600 mb-2" />
          <p className="text-sm text-gray-500">Calculating block area details...</p>
        </div>
      )}
    </div>
  );
}
