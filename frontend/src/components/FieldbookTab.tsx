/** FieldbookTab — tab for fieldbook data entry, review, and export. */
import { useState, useEffect } from 'react';
import { fieldbookApi } from '../services/api';
import { downloadFromApi } from '../utils/download';
import { useT } from '../i18n/hooks';
import { formatDecimal } from '../i18n/numberFormat';
import { summariseLines, lineKind, lineIsClosed } from '../lib/fieldbookLines';

interface FieldbookTabProps {
  calculationId: string;
}

function VarHint({ name, className = '' }: { name: string; className?: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono cursor-pointer select-none 
        ${copied ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'} ${className}`}
      onClick={() => {
        navigator.clipboard.writeText(`{{${name}}}`);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      title={t('biodiversity.copyTemplate', { name: `{{${name}}}` })}
    >
      {copied ? `✓ ${t('biodiversity.copied')}` : `{{${name}}}`}
    </span>
  );
}

export function FieldbookTab({ calculationId }: FieldbookTabProps) {
  const t = useT();
  const [fieldbook, setFieldbook] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  // Which points to list: all, only the outer boundary, only internal ones, or only junctions
  const [pointFilter, setPointFilter] = useState<'all' | 'outer' | 'internal' | 'junction'>('all');

  const getErrorDetail = (err: any): string => {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg).join('; ');
    if (err?.message) return err.message;
    return t('fieldbook.msgUnexpected');
  };

  // Generation settings — 50m interpolation is the default (कार्यविधि-agnostic
  // fieldbook rule: every vertex used, gaps over 50m interpolated); the
  // dropdown still lets the user pick vertices-only or a coarser interval.
  const [interpolationDistance, setInterpolationDistance] = useState(50);
  const [extractElevation, setExtractElevation] = useState(true);

  // Topographic features toggle (default: OFF for performance)
  const [includeTopographic, setIncludeTopographic] = useState(false);

  useEffect(() => {
    loadFieldbook();
  }, [calculationId]);

  const loadFieldbook = async (skipCache: boolean = false) => {
    // Include topographic in cache key to separate cached results
    const cacheKey = `fieldbook_${calculationId}_${includeTopographic}`;

    // Try to load from cache first (unless explicitly skipped)
    if (!skipCache) {
      try {
        const cached = sessionStorage.getItem(cacheKey);
        if (cached) {
          const cachedData = JSON.parse(cached);
          setFieldbook(cachedData);
          console.log('✅ Loaded fieldbook from cache (instant)');
          return; // Return early with cached data
        }
      } catch (e) {
        console.warn(t('fieldbook.msgCacheRead'));
      }
    }

    // Fetch from server
    setLoading(true);
    setError(null);
    try {
      console.log('🔄 Fetching fieldbook from server...');
      const data = await fieldbookApi.list(calculationId, includeTopographic);
      setFieldbook(data);

      // Cache the result
      try {
        sessionStorage.setItem(cacheKey, JSON.stringify(data));
        console.log('💾 Cached fieldbook data for next load');
      } catch (e) {
        console.warn(t('fieldbook.msgCacheFull'));
      }
    } catch (err: any) {
      if (err.response?.status !== 404) {
        setError(getErrorDetail(err));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    // Auto-delete stale empty fieldbook (0 points) before generating
    if (fieldbook && fieldbook.total_count === 0) {
      try {
        await fieldbookApi.delete(calculationId);
      } catch (e) {
        // Ignore — fieldbook may not exist on server
      }
    } else if (fieldbook && fieldbook.total_count > 0) {
      if (!confirm(t('fieldbook.confirmGenerate'))) {
        return;
      }
      try {
        await fieldbookApi.delete(calculationId);
      } catch (e) {
        // Ignore
      }
    }

    setGenerating(true);
    setError(null);
    try {
      const result = await fieldbookApi.generate(calculationId, {
        interpolation_distance_meters: interpolationDistance,
        extract_elevation: extractElevation,
        calculate_reference: false,
      } as any);

      const sourceLine = result.unit_type && result.unit_count
        ? `Generated from ${result.unit_count} ${result.unit_type}${result.unit_count === 1 ? '' : 's'}\n`
        : '';
      const splitLine = result.outer_points != null
        ? `Outer (O): ${result.outer_points}   Internal (I): ${result.internal_points}   Junctions: ${result.junction_points}\n`
        : '';
      alert(`Fieldbook generated successfully!\n\n${sourceLine}Total points: ${result.total_points}\n${splitLine}Vertices: ${result.total_vertices}\nInterpolated: ${result.interpolated_points}\nOuter perimeter: ${formatDecimal(parseFloat(result.total_perimeter_meters), 2)}m`);

      // Clear cache and reload fresh data
      const cacheKey = `fieldbook_${calculationId}`;
      sessionStorage.removeItem(cacheKey);
      await loadFieldbook(true); // Skip cache, fetch fresh
    } catch (err: any) {
      setError(getErrorDetail(err));
    } finally {
      setGenerating(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(t('fieldbook.confirmDelete'))) {
      return;
    }

    try {
      await fieldbookApi.delete(calculationId);

      // Clear cache
      const cacheKey = `fieldbook_${calculationId}`;
      sessionStorage.removeItem(cacheKey);

      setFieldbook(null);
      alert(t('fieldbook.msgDeleted'));
    } catch (err: any) {
      setError(getErrorDetail(err));
    }
  };

  const handleExport = async (format: 'csv' | 'excel' | 'gpx' | 'geojson') => {
    try {
      await downloadFromApi(
        `/api/calculations/${calculationId}/fieldbook`,
        `fieldbook_${calculationId}.${format === 'excel' ? 'xlsx' : format === 'geojson' ? 'geojson' : format}`,
        { format }
      );
    } catch (err: any) {
      alert(err.message || getErrorDetail(err));
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center py-12">
        <div className="text-gray-600">{t('fieldbook.tabLoading')}</div>
      </div>
    );
  }

  const allPoints: any[] = fieldbook?.points ?? [];
  const pointCounts = {
    outer: allPoints.filter((p) => p.boundary_class === 'outer').length,
    internal: allPoints.filter((p) => p.boundary_class === 'internal').length,
    junction: allPoints.filter((p) => p.is_junction).length,
  };
  const classified = pointCounts.outer + pointCounts.internal > 0; // false for a book made before outer/internal existed
  // The server lists the lines (outer rings closed, internal edges open); count them for the summary line
  const bookLines: { id: string }[] = fieldbook?.lines ?? [];
  const linesInfo = {
    ...summariseLines(bookLines.map((l) => ({ id: l.id, kind: lineKind(l.id), closed: lineIsClosed(l.id), positions: [], labels: [] }))),
    total: bookLines.length,
  };
  const visiblePoints = allPoints.filter((p) =>
    pointFilter === 'all' ? true
      : pointFilter === 'junction' ? !!p.is_junction
        : p.boundary_class === pointFilter,
  );

  return (
    <div className="space-y-6">
      {/* Generation Form */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-4">
          {fieldbook && fieldbook.total_count > 0 ? t('fieldbook.generated') : t('fieldbook.generate')}
        </h3>

        {(!fieldbook || fieldbook.total_count === 0) && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('fieldbook.interpolationDistance')}
              </label>
              <select
                value={interpolationDistance}
                onChange={(e) => setInterpolationDistance(parseInt(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white"
              >
                <option value={50}>50 (recommended)</option>
                <option value={0}>0 — No interpolation (vertices only)</option>
                <option value={100}>100</option>
                <option value={150}>150</option>
                <option value={200}>200</option>
              </select>
              <p className="text-xs text-gray-500 mt-1">
                {t('fieldbook.interpolationHint')}
              </p>
            </div>

            <div className="flex items-center">
              <input
                type="checkbox"
                id="extractElevation"
                checked={extractElevation}
                onChange={(e) => setExtractElevation(e.target.checked)}
                className="h-4 w-4 text-blue-600"
              />
              <label htmlFor="extractElevation" className="ml-2 text-sm text-gray-700">
                {t('fieldbook.extractElevation')}
              </label>
            </div>

            <div className="flex items-center">
              <input
                type="checkbox"
                id="includeTopographic"
                checked={includeTopographic}
                onChange={(e) => setIncludeTopographic(e.target.checked)}
                className="h-4 w-4 text-blue-600"
              />
              <label htmlFor="includeTopographic" className="ml-2 text-sm text-gray-700">
                {t('fieldbook.calcTopographic')}
              </label>
            </div>

            

            <button
              onClick={handleGenerate}
              disabled={generating}
              className="w-full bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:bg-gray-400"
            >
              {generating ? t('fieldbook.generating') : t('fieldbook.generate')}
            </button>
          </div>
        )}

        {fieldbook && fieldbook.total_count > 0 && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <div className="text-gray-600">{t('fieldbook.totalPoints')} <VarHint name="fieldbook_total_points" /></div>
                <div className="text-lg font-semibold">{fieldbook.total_count}</div>
              </div>
              <div>
                <div className="text-gray-600">{t('fieldbook.verticesLabel')} <VarHint name="fieldbook_vertex_count" /></div>
                <div className="text-lg font-semibold">{fieldbook.total_vertices ?? '-'}</div>
              </div>
              <div>
                <div className="text-gray-600">{t('fieldbook.interpolatedLabel')} <VarHint name="fieldbook_interpolated_count" /></div>
                <div className="text-lg font-semibold">{fieldbook.interpolated_points ?? '-'}</div>
              </div>
              <div>
                <div className="text-gray-600">{t('fieldbook.perimeter')} <VarHint name="fieldbook_perimeter_m" /></div>
                <div className="text-lg font-semibold">{fieldbook.total_perimeter_meters ? parseFloat(fieldbook.total_perimeter_meters).toLocaleString() : '-'}</div>
              </div>
            </div>

            {classified && linesInfo.total > 0 && (
              <p className="text-xs text-gray-600" data-testid="fieldbook-lines-summary">
                {t('fieldbook.linesSummary', { rings: linesInfo.outerRings, edges: linesInfo.internalEdges })}
                {linesInfo.loops > 0 && ` ${t('fieldbook.linesLoops', { loops: linesInfo.loops })}`}
              </p>
            )}

            {classified && (
              <div className="grid grid-cols-3 gap-4 text-sm" data-testid="fieldbook-split">
                <div>
                  <div className="text-gray-600">{t('fieldbook.outerPoints')}</div>
                  <div className="text-lg font-semibold text-blue-700">{fieldbook.outer_points ?? pointCounts.outer}</div>
                </div>
                <div>
                  <div className="text-gray-600">{t('fieldbook.internalPoints')}</div>
                  <div className="text-lg font-semibold text-gray-800">{fieldbook.internal_points ?? pointCounts.internal}</div>
                </div>
                <div>
                  <div className="text-gray-600">{t('fieldbook.junctionPoints')}</div>
                  <div className="text-lg font-semibold text-amber-700">{fieldbook.junction_points ?? pointCounts.junction}</div>
                </div>
              </div>
            )}

            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => handleExport('csv')}
                className="flex-1 min-w-[120px] bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 text-sm"
              >
                📄 CSV
              </button>
              <button
                onClick={() => handleExport('excel')}
                className="flex-1 min-w-[120px] bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 text-sm"
              >
                📊 Excel
              </button>
              <button
                onClick={() => handleExport('geojson')}
                className="flex-1 min-w-[120px] bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 text-sm"
              >
                🗺️ GeoJSON
              </button>
              <button
                onClick={() => handleExport('gpx')}
                className="flex-1 min-w-[120px] bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 text-sm"
              >
                📍 GPX
              </button>
              <button
                onClick={handleDelete}
                className="bg-red-600 text-white px-4 py-2 rounded-md hover:bg-red-700 text-sm"
              >
                🗑️ Delete
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
            {error}
          </div>
        )}
      </div>

      {/* Enhanced Points Table with Elevation Arrows */}
      {fieldbook && fieldbook.points && fieldbook.points.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="text-lg font-semibold">
              Fieldbook Points ({fieldbook.total_count})
              <VarHint name="fieldbook_points" className="ml-2" />
              <VarHint name="fieldbook_block_summary" className="ml-1" />
            </h3>
            <p className="text-xs text-gray-500 mt-1">
              Elevation arrows: ↑ rise, ↓ fall, → flat. Topographic features (nearest ridge/river) shown with distance and direction.
            </p>
            {classified && (
              <>
                <p className="text-xs text-gray-500 mt-1">{t('fieldbook.orderHint')}</p>
                <div className="flex flex-wrap gap-2 mt-3" role="group" aria-label="Point filter" data-testid="fieldbook-filters">
                  {([
                    ['all', t('fieldbook.filterAll'), allPoints.length],
                    ['outer', t('fieldbook.filterOuter'), pointCounts.outer],
                    ['internal', t('fieldbook.filterInternal'), pointCounts.internal],
                    ['junction', t('fieldbook.filterJunctions'), pointCounts.junction],
                  ] as const).map(([key, label, count]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setPointFilter(key)}
                      aria-pressed={pointFilter === key}
                      data-testid={`fieldbook-filter-${key}`}
                      className={`px-3 py-1 rounded-full text-xs font-medium border ${
                        pointFilter === key
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      {label} ({count})
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colPoint')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colType')}</th>
                  {classified && (
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colClass')}</th>
                  )}
                  {/* The remark says what the point is AND which units it separates (outer: A, B). It replaces the
                      separate Block and Separates columns, which only repeated it. */}
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('attributeTable.col.remark')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Sub-area</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colCoordinates')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">UTM</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colElevation')}</th>
                  <th className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colChange')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colNearestFeature')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">Azimuth (°)</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colDistance')}</th>
                  {classified && (
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colNextPoint')}</th>
                  )}
                  {classified && (
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fieldbook.colLine')}</th>
                  )}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {visiblePoints.map((point: any, idx: number) => {
                  // Calculate elevation change from previous point
                  let elevationChange = null;
                  let elevationDiff = 0;
                  let arrow = '→';
                  let changeColor = 'text-gray-400';

                  if (idx > 0 && point.elevation && visiblePoints[idx - 1].elevation) {
                    const prevElevation = parseFloat(visiblePoints[idx - 1].elevation);
                    const currElevation = parseFloat(point.elevation);
                    elevationDiff = currElevation - prevElevation;

                    if (Math.abs(elevationDiff) > 1) {
                      if (elevationDiff > 0) {
                        arrow = '↑';
                        changeColor = Math.abs(elevationDiff) > 20 ? 'text-green-700 font-bold' : 'text-green-600';
                      } else {
                        arrow = '↓';
                        changeColor = Math.abs(elevationDiff) > 20 ? 'text-red-700 font-bold' : 'text-red-600';
                      }
                      elevationChange = `${elevationDiff > 0 ? '+' : ''}${formatDecimal(elevationDiff, 1)}m`;
                    }
                  }

                  return (
                    <tr
                      key={point.id}
                      className={`hover:bg-gray-50 ${point.is_junction ? 'bg-amber-50' : point.boundary_class === 'outer' ? 'bg-blue-50/40' : ''}`}
                    >
                      <td className="px-3 py-2 text-sm font-mono font-medium">{point.point_label || `P${point.point_number}`}</td>
                      <td className="px-3 py-2 text-sm">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          point.point_type === 'vertex'
                            ? 'bg-blue-100 text-blue-800'
                            : 'bg-gray-100 text-gray-700'
                        }`}>
                          {point.point_type === 'vertex' ? 'V' : 'I'}
                        </span>
                      </td>
                      {classified && (
                        <>
                          <td className="px-3 py-2 text-sm">
                            <span
                              className={`px-2 py-1 rounded text-xs font-medium ${
                                point.boundary_class === 'outer' ? 'bg-sky-100 text-sky-800' : 'bg-gray-100 text-gray-700'
                              }`}
                            >
                              {point.boundary_class === 'outer' ? t('fieldbook.outerLabel') : t('fieldbook.internalLabel')}
                            </span>
                            {point.is_junction && (
                              <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-200 text-amber-900" title={t('fieldbook.colJunction')}>
                                ✦ {point.junction_degree}
                              </span>
                            )}
                          </td>
                        </>
                      )}
                      <td className="px-3 py-2 text-xs text-gray-700" data-testid="fieldbook-remark">
                        {point.remarks || <span className="text-gray-400">-</span>}
                      </td>
                      <td className="px-3 py-2 text-sm">
                        {point.sub_area_name ? (
                          <div className="space-y-0.5">
                            <span className={`px-2 py-1 rounded text-xs font-medium ${
                              point.is_excluded ? 'bg-red-100 text-red-800' : 'bg-purple-100 text-purple-800'
                            }`}>
                              {point.sub_area_name}
                            </span>
                            {point.sub_area_category && (
                              <div className="text-[10px] text-gray-500">{point.sub_area_category}</div>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-400 text-xs">-</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs font-mono text-gray-700">
                        <div>{formatDecimal(parseFloat(point.latitude), 5)}</div>
                        <div className="text-gray-500">{formatDecimal(parseFloat(point.longitude), 5)}</div>
                      </td>
                      <td className="px-3 py-2 text-xs font-mono text-gray-600">
                        {point.easting_utm && point.northing_utm ? (
                          <>
                            <div>E {formatDecimal(parseFloat(point.easting_utm), 0)}</div>
                            <div className="text-gray-500">N {formatDecimal(parseFloat(point.northing_utm), 0)}</div>
                            <div className="text-gray-400 text-[10px]">{point.utm_zone}N</div>
                          </>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-sm font-mono text-right font-medium">
                        {point.elevation ? (
                          <span className="text-blue-900">{formatDecimal(parseFloat(point.elevation), 1)}</span>
                        ) : (
                          <span className="text-gray-400">{t('fieldbook.na')}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {elevationChange ? (
                          <div className="flex flex-col items-center">
                            <span className={`text-xl ${changeColor}`}>{arrow}</span>
                            <span className={`text-xs ${changeColor}`}>{elevationChange}</span>
                          </div>
                        ) : (
                          <span className="text-gray-300 text-sm">-</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {point.nearest_feature ? (
                          <div className="space-y-1">
                            <div className="flex items-center gap-1">
                              <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                point.feature_type?.toLowerCase() === 'river'
                                  ? 'bg-blue-100 text-blue-800'
                                  : 'bg-amber-100 text-amber-800'
                              }`}>
                                {point.feature_type?.toLowerCase() === 'river' ? '🌊' : '⛰️'}
                              </span>
                              <span className="font-medium text-gray-800 truncate max-w-[120px]" title={point.nearest_feature}>
                                {point.nearest_feature}
                              </span>
                            </div>
                            <div className="text-gray-600 flex items-center gap-2">
                              <span className="font-mono">{point.distance_to_feature ? Math.round(point.distance_to_feature) : '-'}m</span>
                              {point.direction_to_feature && (
                                <span className="px-1 py-0.5 bg-gray-200 text-gray-700 rounded font-semibold text-[10px]">
                                  {point.direction_to_feature}
                                </span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-sm font-mono text-right text-gray-700">
                        {point.azimuth_to_next != null ? formatDecimal(parseFloat(point.azimuth_to_next), 1) : '-'}
                      </td>
                      <td className="px-3 py-2 text-sm font-mono text-right text-gray-700">
                        {point.distance_to_next != null ? formatDecimal(parseFloat(point.distance_to_next), 1) : '-'}
                      </td>
                      {classified && (
                        <td className="px-3 py-2 text-sm font-mono text-gray-700">{point.next_point_label || '-'}</td>
                      )}
                      {classified && (
                        <td
                          className="px-3 py-2 text-xs font-mono text-gray-600"
                          data-testid="fieldbook-line"
                          title={point.lines ? Object.keys(point.lines).join(', ') : undefined}
                        >
                          {point.line_id || '-'}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="px-6 py-3 bg-blue-50 border-t border-blue-100">
            <div className="text-xs text-gray-700 flex flex-wrap gap-x-6 gap-y-2">
              <div><span className="font-semibold">V</span> = Vertex (original boundary point)</div>
              <div><span className="font-semibold">I</span> = Interpolated point</div>
              {classified && (
                <>
                  <div><span className="font-semibold">O1…</span> = outer boundary point, <span className="font-semibold">I1…</span> = internal boundary point</div>
                  <div><span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-200 text-amber-900">✦ 3</span> = junction: that many regions meet here</div>
                  <div>{t('fieldbook.linesLegend')}</div>
                </>
              )}
              <div><span className="text-green-600 font-bold text-lg">↑</span> = Elevation rise</div>
              <div><span className="text-red-600 font-bold text-lg">↓</span> = Elevation fall</div>
              <div><span className="text-gray-400 text-lg">→</span> = Flat (±1m)</div>
              <div>🌊 = River</div>
              <div>⛰️ = Ridge</div>
              <div className="w-full text-blue-700 font-medium">
                💡 Showing topographic features (nearest ridge/river) with distance and direction. Export CSV/Excel for full dataset.
              </div>
            </div>
          </div>

          {/* OP Document Variables */}
          <div className="px-6 py-3 bg-purple-50 border-t border-purple-100">
            <div className="text-xs font-semibold text-purple-800 mb-2">
              📋 OP Document Fieldbook Variables — click to copy
            </div>
            <div className="flex flex-wrap gap-1">
              <VarHint name="fieldbook_narration" />
              <VarHint name="fieldbook_total_points" />
              <VarHint name="fieldbook_vertex_count" />
              <VarHint name="fieldbook_interpolated_count" />
              <VarHint name="fieldbook_perimeter_m" />
              <VarHint name="fieldbook_avg_elevation_m" />
              <VarHint name="fieldbook_min_elevation_m" />
              <VarHint name="fieldbook_max_elevation_m" />
              <VarHint name="fieldbook_points" />
              <VarHint name="fieldbook_block_summary" />
              <VarHint name="map:fieldbook" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
