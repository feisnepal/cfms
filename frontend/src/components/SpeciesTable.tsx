/** SpeciesTable — detailed species list with search, filter, and export capabilities. */
import React, { useState, useMemo } from 'react';
import { RARITY_STATUS_KEY, statusLabel } from '../lib/statusLabels';
import api from '../services/api';
import { downloadBlob } from '../utils/download';
import { useT } from '../i18n/hooks';

interface Species {
  scientific_name: string;
  local_name: string;
  role: string;
  availability_rank: number;
  economic_value: string;
  confirmed?: boolean;
  manually_added?: boolean;
  growth_rate?: string;
  min_altitude_m?: number;
  max_altitude_m?: number;
  main_uses?: string;
  nitrogen_fixing?: boolean;
  rarity_status?: string;
  family?: string;
  forest_types?: string[];
}

interface SpeciesTableProps {
  species: Species[];
  calculationId: string;
  forestName?: string;
  removedSpecies?: string[];
  onSpeciesToggle?: (speciesName: string, enabled: boolean) => void;
  onAddSpecies?: () => void;
  onSpeciesRemoved?: () => void;
  onExport?: (format: 'csv' | 'excel') => void;
}

const FOREST_TYPE_COLORS: string[] = [
  'bg-green-100 border-green-400',
  'bg-blue-100 border-blue-400',
  'bg-purple-100 border-purple-400',
  'bg-amber-100 border-amber-400',
  'bg-rose-100 border-rose-400',
  'bg-cyan-100 border-cyan-400',
  'bg-orange-100 border-orange-400',
  'bg-teal-100 border-teal-400',
  'bg-indigo-100 border-indigo-400',
  'bg-lime-100 border-lime-400',
];

const getRoleBadge = (role: string) => {
  const colors: { [key: string]: string } = {
    'Dominant': 'bg-green-100 text-green-800 font-bold',
    'Co-dominant': 'bg-blue-100 text-blue-800 font-bold',
    'Associate': 'bg-gray-100 text-gray-700',
    'Occasional': 'bg-yellow-50 text-yellow-700',
    'Rare': 'bg-orange-100 text-orange-700'
  };
  return colors[role] || colors['Associate'];
};

const getValueBadge = (value: string) => {
  const colors: { [key: string]: string } = {
    'Very High': 'bg-green-200 text-green-900',
    'High': 'bg-green-100 text-green-800',
    'Moderate': 'bg-yellow-100 text-yellow-800',
    'Medium': 'bg-yellow-100 text-yellow-800',
    'Low': 'bg-gray-100 text-gray-600'
  };
  return colors[value] || colors['Medium'];
};


/** Display-label keys for persisted role / economic-value data values. */
const ROLE_LABEL_KEY: Record<string, string> = {
  'Dominant': 'species.role.dominant',
  'Co-dominant': 'species.role.coDominant',
  'Associate': 'species.role.associate',
  'Occasional': 'species.role.occasional',
  'Rare': 'species.role.rare',
};
const VALUE_LABEL_KEY: Record<string, string> = {
  'Very High': 'species.value.veryHigh',
  'High': 'species.value.high',
  'Moderate': 'species.value.moderate',
  'Medium': 'species.value.medium',
  'Low': 'species.value.low',
};

const SpeciesTable: React.FC<SpeciesTableProps> = ({
  species,
  calculationId,
  forestName = 'Forest',
  removedSpecies = [],
  onSpeciesToggle,
  onAddSpecies,
  onSpeciesRemoved,
  onExport,
}) => {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [enabledSpecies, setEnabledSpecies] = useState<Set<string>>(
    new Set(species.map(s => s.scientific_name))
  );
  const [sortBy, setSortBy] = useState<string>('role');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [filterRole, setFilterRole] = useState<string>('all');
  const [filterValue, setFilterValue] = useState<string>('all');
  const [showNFixersOnly, setShowNFixersOnly] = useState(false);

  // Group species by forest type
  const speciesByForestType = useMemo(() => {
    const groups: { [key: string]: Species[] } = {};
    const typeOrder: string[] = [];

    species.forEach(s => {
      if (removedSpecies.includes(s.scientific_name)) return;
      const types = s.forest_types && s.forest_types.length > 0
        ? s.forest_types
        : ['Unclassified'];
      types.forEach(ft => {
        if (!groups[ft]) {
          groups[ft] = [];
          typeOrder.push(ft);
        }
        // Avoid duplicates (same species in same forest type)
        if (!groups[ft].find(existing => existing.scientific_name === s.scientific_name)) {
          groups[ft].push(s);
        }
      });
    });

    // Return in the order forest types were encountered
    return typeOrder.map(ft => ({ forestType: ft, species: groups[ft] }));
  }, [species, removedSpecies]);

  // Get color for a forest type index
  const getForestTypeColor = (idx: number) =>
    FOREST_TYPE_COLORS[idx % FOREST_TYPE_COLORS.length];

  // Remove (hide) species
  const handleRemoveSpecies = async (scientificName: string, localName: string) => {
    if (!window.confirm(`Remove "${localName}" (${scientificName}) from species list?`)) return;
    try {
      await api.delete(`/api/forests/calculations/${calculationId}/remove-species/${encodeURIComponent(scientificName)}`);
      if (onSpeciesRemoved) onSpeciesRemoved();
    } catch (err: any) {
      console.error('Error removing species:', err);
      alert('Failed to remove species: ' + (err.response?.data?.detail || err.message));
    }
  };

  // Toggle species checkbox
  const handleToggle = (scientificName: string) => {
    const newEnabled = new Set(enabledSpecies);
    if (newEnabled.has(scientificName)) newEnabled.delete(scientificName);
    else newEnabled.add(scientificName);
    setEnabledSpecies(newEnabled);
    if (onSpeciesToggle) onSpeciesToggle(scientificName, newEnabled.has(scientificName));
  };

  // Filter and sort for the detailed table
  const filteredAndSortedSpecies = useMemo(() => {
    let filtered = species.filter(s => !removedSpecies.includes(s.scientific_name));
    if (filterRole !== 'all') filtered = filtered.filter(s => s.role === filterRole);
    if (filterValue !== 'all') filtered = filtered.filter(s => s.economic_value === filterValue);
    if (showNFixersOnly) filtered = filtered.filter(s => s.nitrogen_fixing === true);

    filtered.sort((a, b) => {
      let aVal, bVal;
      switch (sortBy) {
        case 'role':
          const roleOrder = ['Dominant', 'Co-dominant', 'Associate', 'Occasional', 'Rare'];
          aVal = roleOrder.indexOf(a.role || 'Associate');
          bVal = roleOrder.indexOf(b.role || 'Associate');
          break;
        case 'local_name':
          aVal = a.local_name || '';
          bVal = b.local_name || '';
          break;
        case 'economic_value':
          const valueOrder = ['Very High', 'High', 'Moderate', 'Medium', 'Low'];
          aVal = valueOrder.indexOf(a.economic_value || 'Medium');
          bVal = valueOrder.indexOf(b.economic_value || 'Medium');
          break;
        case 'altitude':
          aVal = a.min_altitude_m || 0;
          bVal = b.min_altitude_m || 0;
          break;
        default:
          return 0;
      }
      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
      return 0;
    });
    return filtered;
  }, [species, sortBy, sortOrder, filterRole, filterValue, showNFixersOnly, removedSpecies]);

  const formatAltitude = (min?: number, max?: number) => {
    if (!min && !max) return 'N/A';
    if (!max) return `${min}m+`;
    if (!min) return `up to ${max}m`;
    return `${min}-${max}m`;
  };

  const truncate = (text: string, maxLength: number) => {
    if (!text || text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  const handleExportCSV = async () => {
    const csvContent = [
      ['Local Name', 'Scientific Name', 'Role', 'Economic Value', 'Altitude Range', 'Growth Rate', 'Main Uses', 'Forest Types', 'N-Fixing', 'Family', 'Rarity Status'].join(','),
      ...species.map(s => [
        s.local_name,
        s.scientific_name,
        s.role,
        s.economic_value,
        formatAltitude(s.min_altitude_m, s.max_altitude_m),
        s.growth_rate || '',
        (s.main_uses || '').replace(/,/g, ';'),
        (s.forest_types || []).join('; '),
        s.nitrogen_fixing ? 'Yes' : 'No',
        s.family || '',
        s.rarity_status || ''
      ].map(v => `"${v}"`).join(','))
    ].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const dateStr = new Date().toISOString().split('T')[0].replace(/-/g, '');
    const name = forestName.replace(/\s+/g, '_');
    downloadBlob(blob, `${name}_Species_List_${dateStr}.csv`);
  };

  return (
    <div className="space-y-4">
      {/* Card View - Grouped by Forest Type */}
      <div>
        <h4 className="text-md font-semibold text-gray-900 mb-3">
          Potential Species by Forest Type ({species.filter(s => !removedSpecies.includes(s.scientific_name)).length} species)
        </h4>

        {speciesByForestType.map((group, ftIdx) => (
          <div key={group.forestType} className="mb-5">
            <p className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
              <span className={`inline-block w-3 h-3 rounded-full ${getForestTypeColor(ftIdx).split(' ')[0]}`} />
              {group.forestType}
              <span className="text-gray-400 font-normal">({group.species.length})</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {group.species.map((sp, idx) => (
                <div
                  key={`${sp.scientific_name}-${ftIdx}`}
                  className={`relative rounded-lg px-4 py-3 pr-8 text-sm border-2 ${getForestTypeColor(ftIdx)}`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-gray-900">{sp.local_name}</span>
                    <span className="text-gray-500 italic text-xs">({sp.scientific_name})</span>
                    {sp.economic_value && (
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${getValueBadge(sp.economic_value)}`}>
                        {t(VALUE_LABEL_KEY[sp.economic_value || 'Medium'] ?? 'species.value.medium')}
                      </span>
                    )}
                    {sp.role && (
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${getRoleBadge(sp.role)}`}>
                        {sp.role}
                      </span>
                    )}
                  </div>
                  {sp.main_uses && (
                    <p className="text-xs text-gray-500 mt-1 leading-tight">{sp.main_uses}</p>
                  )}
                  <div className="flex gap-3 mt-1 text-xs text-gray-400">
                    {sp.growth_rate && <span>{sp.growth_rate}</span>}
                    {sp.min_altitude_m && <span>{formatAltitude(sp.min_altitude_m, sp.max_altitude_m)}</span>}
                    {sp.nitrogen_fixing && <span className="text-green-600 font-medium">N-fixer</span>}
                  </div>
                  <button
                    onClick={() => handleRemoveSpecies(sp.scientific_name, sp.local_name)}
                    className="absolute top-1.5 right-1.5 w-5 h-5 flex items-center justify-center text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-full transition-colors"
                    title={t('species.action.remove')}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}

        {speciesByForestType.length === 0 && (
          <p className="text-sm text-gray-500">{t('species.table.noData')}</p>
        )}
      </div>

      {/* Expandable Detailed Table */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full bg-gray-50 hover:bg-gray-100 px-4 py-3 text-left flex items-center justify-between transition-colors"
        >
          <span className="text-sm font-medium text-gray-700">
            {expanded ? '▼' : '▶'} Show All Species with Detailed Characteristics
          </span>
          <span className="text-xs text-gray-500">
            {filteredAndSortedSpecies.length} species
          </span>
        </button>

        {expanded && (
          <div className="bg-white">
            {/* Filters and Actions */}
            <div className="p-4 bg-gray-50 border-b border-gray-200 flex flex-wrap gap-3 items-center justify-between">
              <div className="flex flex-wrap gap-3 items-center">
                <select
                  value={filterRole}
                  onChange={(e) => setFilterRole(e.target.value)}
                  className="text-sm border border-gray-300 rounded px-3 py-1.5"
                >
                  <option value="all">{t('species.filter.allRoles')}</option>
                  <option value="Dominant">{t('species.role.dominant')}</option>
                  <option value="Co-dominant">{t('species.role.coDominant')}</option>
                  <option value="Associate">{t('species.role.associate')}</option>
                  <option value="Occasional">{t('species.role.occasional')}</option>
                  <option value="Rare">{t('species.role.rare')}</option>
                </select>
                <select
                  value={filterValue}
                  onChange={(e) => setFilterValue(e.target.value)}
                  className="text-sm border border-gray-300 rounded px-3 py-1.5"
                >
                  <option value="all">{t('species.value.allValues')}</option>
                  <option value="Very High">{t('species.value.veryHigh')}</option>
                  <option value="High">{t('species.value.high')}</option>
                  <option value="Moderate">{t('species.value.moderate')}</option>
                  <option value="Medium">{t('species.value.medium')}</option>
                  <option value="Low">{t('species.value.low')}</option>
                </select>
                <label className="flex items-center text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={showNFixersOnly}
                    onChange={(e) => setShowNFixersOnly(e.target.checked)}
                    className="mr-2"
                  />
                  {t('species.filter.nFixersOnly')}
                </label>
              </div>
              <div className="flex gap-2">
                {onAddSpecies && (
                  <button
                    onClick={onAddSpecies}
                    className="text-sm px-3 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
                  >
                    + Add Species
                  </button>
                )}
                <button
                  onClick={handleExportCSV}
                  className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
                >
                  📥 Export CSV
                </button>
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-100">
                  <tr>
                    {onSpeciesToggle && (
                      <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">☑</th>
                    )}
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-200"
                      onClick={() => { if (sortBy === 'local_name') setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc'); else { setSortBy('local_name'); setSortOrder('asc'); }}}>
                      Local Name {sortBy === 'local_name' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('species.col.scientificName')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-200"
                      onClick={() => { if (sortBy === 'role') setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc'); else { setSortBy('role'); setSortOrder('asc'); }}}>
                      Role {sortBy === 'role' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-200"
                      onClick={() => { if (sortBy === 'economic_value') setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc'); else { setSortBy('economic_value'); setSortOrder('asc'); }}}>
                      Value {sortBy === 'economic_value' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-200"
                      onClick={() => { if (sortBy === 'altitude') setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc'); else { setSortBy('altitude'); setSortOrder('asc'); }}}>
                      Altitude {sortBy === 'altitude' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('species.col.growth')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('species.col.forestTypes')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('species.col.mainUses')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('species.col.nFix')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('species.col.status')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {filteredAndSortedSpecies.map((sp, idx) => (
                    <tr key={idx} className={`hover:bg-gray-50 ${!enabledSpecies.has(sp.scientific_name) ? 'opacity-50' : ''}`}>
                      {onSpeciesToggle && (
                        <td className="px-3 py-3 whitespace-nowrap">
                          <input type="checkbox" checked={enabledSpecies.has(sp.scientific_name)}
                            onChange={() => handleToggle(sp.scientific_name)}
                            className="h-4 w-4 text-green-600 focus:ring-green-500 border-gray-300 rounded" />
                        </td>
                      )}
                      <td className="px-4 py-3 whitespace-nowrap font-semibold text-gray-900">{sp.local_name}</td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm italic text-gray-600">{sp.scientific_name}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className={`px-2 py-1 text-xs rounded ${getRoleBadge(sp.role || 'Associate')}`}>{t(ROLE_LABEL_KEY[sp.role || 'Associate'] ?? 'species.role.associate')}</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className={`px-2 py-1 text-xs rounded ${getValueBadge(sp.economic_value || 'Medium')}`}>{t(VALUE_LABEL_KEY[sp.economic_value || 'Medium'] ?? 'species.value.medium')}</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">{formatAltitude(sp.min_altitude_m, sp.max_altitude_m)}</td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">{sp.growth_rate || 'N/A'}</td>
                      <td className="px-4 py-3 text-sm text-gray-600 max-w-xs">
                        <span title={(sp.forest_types || []).join(', ')}>{(sp.forest_types || ['N/A']).join(', ')}</span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600 max-w-xs">
                        <span title={sp.main_uses || ''}>{truncate(sp.main_uses || 'N/A', 50)}</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-center">
                        {sp.nitrogen_fixing ? <span className="text-green-600 font-bold" title={t('species.tooltip.nitrogenFixing')}>🌱</span> : <span className="text-gray-400">-</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm">
                        <span className={`${sp.rarity_status?.includes('ENDANGERED') || sp.rarity_status?.includes('RARE') ? 'text-orange-600 font-semibold' : 'text-gray-600'}`}>
                          {statusLabel(RARITY_STATUS_KEY, sp.rarity_status || 'Common', t)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {filteredAndSortedSpecies.length === 0 && (
              <div className="p-8 text-center text-gray-500">{t('species.table.noMatch')}</div>
            )}

            <div className="p-4 bg-yellow-50 border-t border-yellow-200">
              <p className="text-sm text-yellow-800">
                ⚠️ <strong>{t('species.note.label')}</strong> {t('species.note.uncheckHint')}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SpeciesTable;
