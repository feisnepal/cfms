/** SpeciesSummaryTable — summary table of species-wise statistics (count, volume, area). */
import React, { useState } from 'react';
import { useT } from '../i18n/hooks';

interface SpeciesData {
  scientific_name: string;
  local_name: string;
  family?: string;
  economic_value?: string;
  roles: string[];
  blocks: string[];
  block_indices: number[];
  present_in_blocks: number;
  total_blocks: number;
  coverage_percentage: number;
  confirmed: boolean;
  confirmed_in_blocks: number;
  unconfirmed_in_blocks: number;
}

interface SpeciesSummaryTableProps {
  speciesData: SpeciesData[];
}

const SpeciesSummaryTable: React.FC<SpeciesSummaryTableProps> = ({ speciesData }) => {
  const t = useT();
  const [sortField, setSortField] = useState<'coverage_percentage' | 'local_name' | 'confirmed'>('coverage_percentage');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [filterRole, setFilterRole] = useState<string>('all');
  const [filterConfirmed, setFilterConfirmed] = useState<string>('all');

  // Get unique roles
  const uniqueRoles = Array.from(new Set(speciesData.flatMap(s => s.roles))).sort();

  // Sorting function
  const handleSort = (field: 'coverage_percentage' | 'local_name' | 'confirmed') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  // Filter and sort data
  const filteredAndSortedData = speciesData
    .filter(species => {
      if (filterRole !== 'all' && !species.roles.includes(filterRole)) {
        return false;
      }
      if (filterConfirmed === 'confirmed' && !species.confirmed) {
        return false;
      }
      if (filterConfirmed === 'unconfirmed' && species.confirmed) {
        return false;
      }
      return true;
    })
    .sort((a, b) => {
      let aVal: any;
      let bVal: any;

      if (sortField === 'coverage_percentage') {
        aVal = a.coverage_percentage;
        bVal = b.coverage_percentage;
      } else if (sortField === 'local_name') {
        aVal = a.local_name || a.scientific_name;
        bVal = b.local_name || b.scientific_name;
      } else if (sortField === 'confirmed') {
        aVal = a.confirmed ? 1 : 0;
        bVal = b.confirmed ? 1 : 0;
      }

      if (sortDirection === 'asc') {
        return aVal > bVal ? 1 : -1;
      } else {
        return aVal < bVal ? 1 : -1;
      }
    });

  const SortIcon = ({ field }: { field: string }) => {
    if (sortField !== field) {
      return <span className="text-gray-400 ml-1">↕</span>;
    }
    return <span className="text-green-600 ml-1">{sortDirection === 'asc' ? '↑' : '↓'}</span>;
  };

  return (
    <div className="w-full">
      <h3 className="text-lg font-semibold mb-4 text-gray-900">
        {t('species.table.title')}
      </h3>

      {/* Filters */}
      <div className="mb-4 flex gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-gray-700">{t('species.filter.role')}</label>
          <select
            value={filterRole}
            onChange={(e) => setFilterRole(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1 text-sm"
          >
            <option value="all">{t('species.filter.allRoles')}</option>
            {uniqueRoles.map(role => (
              <option key={role} value={role}>{role}</option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-gray-700">{t('species.filter.status')}</label>
          <select
            value={filterConfirmed}
            onChange={(e) => setFilterConfirmed(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1 text-sm"
          >
            <option value="all">{t('species.filter.all')}</option>
            <option value="confirmed">{t('species.filter.confirmedOnly')}</option>
            <option value="unconfirmed">{t('species.filter.unconfirmedOnly')}</option>
          </select>
        </div>

        <div className="text-sm text-gray-600 flex items-center">
          Showing {filteredAndSortedData.length} of {speciesData.length} species
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto border border-gray-200 rounded-lg">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th
                className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('local_name')}
              >
                {t('species.col.species')} <SortIcon field="local_name" />
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                {t('species.col.scientificName')}
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                {t('species.col.roles')}
              </th>
              <th
                className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('coverage_percentage')}
              >
                {t('species.col.coverage')} <SortIcon field="coverage_percentage" />
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                {t('species.col.blocksPresent')}
              </th>
              <th
                className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('confirmed')}
              >
                {t('species.col.status')} <SortIcon field="confirmed" />
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {filteredAndSortedData.map((species, idx) => (
              <tr key={idx} className="hover:bg-gray-50">
                <td className="px-4 py-3 whitespace-nowrap">
                  <div className="text-sm font-medium text-gray-900">
                    {species.local_name || species.scientific_name}
                  </div>
                  {species.economic_value && (
                    <div className="text-xs text-gray-500">
                      Value: {species.economic_value}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <div className="text-sm text-gray-700 italic">
                    {species.scientific_name}
                  </div>
                  {species.family && (
                    <div className="text-xs text-gray-500">
                      {species.family}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <div className="flex flex-wrap gap-1">
                    {species.roles.map((role, roleIdx) => (
                      <span
                        key={roleIdx}
                        className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800"
                      >
                        {role}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <div className="flex items-center">
                    <div className="w-full bg-gray-200 rounded-full h-2 mr-2" style={{ width: '100px' }}>
                      <div
                        className="bg-green-500 h-2 rounded-full"
                        style={{ width: `${species.coverage_percentage}%` }}
                      ></div>
                    </div>
                    <span className="text-sm font-medium text-gray-900">
                      {species.coverage_percentage}%
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    {species.present_in_blocks} / {species.total_blocks} blocks
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="text-xs text-gray-600 max-w-xs">
                    {species.blocks.join(', ')}
                  </div>
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      species.confirmed
                        ? 'bg-green-100 text-green-800'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {species.confirmed ? t('species.status.confirmed') : t('species.status.unconfirmed')}
                  </span>
                  <div className="text-xs text-gray-500 mt-1">
                    {species.confirmed_in_blocks} confirmed, {species.unconfirmed_in_blocks} pending
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filteredAndSortedData.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          {t('species.empty.noMatch')}
        </div>
      )}
    </div>
  );
};

export default SpeciesSummaryTable;
