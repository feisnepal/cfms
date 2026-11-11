/** AddSpeciesModal — modal form for adding a new species record. */
import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { useErrorHandler } from '../hooks/useErrorHandler';
import { useT } from '../i18n/hooks';

interface Species {
  id: number;
  scientific_name: string;
  local_name: string;
  family?: string;
  growth_rate?: string;
  min_altitude_m?: number;
  max_altitude_m?: number;
  economic_value?: string;
  main_uses?: string;
  nitrogen_fixing?: boolean;
  rarity_status?: string;
}

interface AddSpeciesModalProps {
  isOpen: boolean;
  onClose: () => void;
  calculationId: string;
  onSpeciesAdded: () => void;
}

const AddSpeciesModal: React.FC<AddSpeciesModalProps> = ({
  isOpen,
  onClose,
  calculationId,
  onSpeciesAdded
}) => {
  const t = useT();
  const [searchQuery, setSearchQuery] = useState('');
  const [species, setSpecies] = useState<Species[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedSpecies, setSelectedSpecies] = useState<Species | null>(null);
  const [role, setRole] = useState('Associate');
  const [availabilityRank, setAvailabilityRank] = useState(3);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');
  const { handleError } = useErrorHandler();

  // Search species when query changes
  useEffect(() => {
    const searchSpecies = async () => {
      if (searchQuery.length < 2) {
        setSpecies([]);
        return;
      }

      setLoading(true);
      setError('');

      try {
        const response = await api.get(`/api/species/search?q=${encodeURIComponent(searchQuery)}&limit=20`);
        setSpecies(response.data.species || []);
      } catch (err: any) {
        console.error('Error searching species:', err);
        setError(handleError(err, 'generalErrors.serverError'));
      } finally {
        setLoading(false);
      }
    };

    const debounceTimer = setTimeout(searchSpecies, 300);
    return () => clearTimeout(debounceTimer);
  }, [searchQuery]);

  // Update availability_rank when role changes
  useEffect(() => {
    const rankMap: { [key: string]: number } = {
      'Dominant': 1,
      'Co-dominant': 2,
      'Associate': 3,
      'Occasional': 4,
      'Rare': 4
    };
    setAvailabilityRank(rankMap[role] || 3);
  }, [role]);

  const handleAddSpecies = async () => {
    if (!selectedSpecies) return;

    setAdding(true);
    setError('');

    try {
      await api.post(`/api/forests/calculations/${calculationId}/add-species`, {
        species_id: selectedSpecies.id,
        role: role,
        availability_rank: availabilityRank
      });

      // Success! Close modal and notify parent
      onSpeciesAdded();
      handleClose();
    } catch (err: any) {
      console.error('Error adding species:', err);
      setError(handleError(err, 'generalErrors.serverError'));
    } finally {
      setAdding(false);
    }
  };

  const handleClose = () => {
    setSearchQuery('');
    setSpecies([]);
    setSelectedSpecies(null);
    setRole('Associate');
    setAvailabilityRank(3);
    setError('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h2 className="text-xl font-semibold text-gray-800">{t('species.add.title')}</h2>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 overflow-y-auto max-h-[calc(90vh-200px)]">
          {/* Search Input */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('species.add.searchLabel')}
            </label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('species.add.searchPlaceholder')}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
              autoFocus
            />
            <p className="mt-1 text-xs text-gray-500">
              Examples: "Shorea robusta", "Sal", "Dipterocarpaceae"
            </p>
          </div>

          {/* Loading State */}
          {loading && (
            <div className="text-center py-4 text-gray-500">
              <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-green-600"></div>
              <p className="mt-2">{t('species.add.searching')}</p>
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
              <p className="text-sm text-red-600">{error}</p>
            </div>
          )}

          {/* Species Search Results */}
          {!loading && species.length > 0 && !selectedSpecies && (
            <div className="mb-4">
              <p className="text-sm font-medium text-gray-700 mb-2">
                {species.length} species found
              </p>
              <div className="space-y-2 max-h-64 overflow-y-auto border border-gray-200 rounded-md">
                {species.map((sp) => (
                  <div
                    key={sp.id}
                    onClick={() => setSelectedSpecies(sp)}
                    className="p-3 hover:bg-green-50 cursor-pointer border-b border-gray-100 last:border-b-0"
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <p className="font-medium text-gray-900">{sp.local_name}</p>
                        <p className="text-sm text-gray-600 italic">{sp.scientific_name}</p>
                        {sp.family && (
                          <p className="text-xs text-gray-500">Family: {sp.family}</p>
                        )}
                      </div>
                      <div className="text-right ml-4">
                        {sp.economic_value && (
                          <span className={`inline-block text-xs px-2 py-1 rounded ${
                            sp.economic_value === 'High' || sp.economic_value === 'Very High'
                              ? 'bg-green-100 text-green-800'
                              : sp.economic_value === 'Moderate' || sp.economic_value === 'Medium'
                              ? 'bg-yellow-100 text-yellow-800'
                              : 'bg-gray-100 text-gray-600'
                          }`}>
                            {sp.economic_value}
                          </span>
                        )}
                        {sp.nitrogen_fixing && (
                          <span className="ml-1 text-sm">🌱</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* No Results */}
          {!loading && searchQuery.length >= 2 && species.length === 0 && (
            <div className="text-center py-8 text-gray-500">
              <p>No species found for "{searchQuery}"</p>
              <p className="text-sm mt-1">{t('species.add.tryDifferent')}</p>
            </div>
          )}

          {/* Selected Species Details & Role Selection */}
          {selectedSpecies && (
            <div className="space-y-4">
              <div className="bg-green-50 border border-green-200 rounded-md p-4">
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <h3 className="font-semibold text-lg text-gray-900">
                      {selectedSpecies.local_name}
                    </h3>
                    <p className="text-sm text-gray-600 italic">
                      {selectedSpecies.scientific_name}
                    </p>
                  </div>
                  <button
                    onClick={() => setSelectedSpecies(null)}
                    className="text-sm text-green-600 hover:text-green-800"
                  >
                    {t('species.add.change')}
                  </button>
                </div>

                {/* Species Characteristics */}
                <div className="grid grid-cols-2 gap-2 text-sm">
                  {selectedSpecies.family && (
                    <div>
                      <span className="text-gray-600">{t('species.add.family')}</span>
                      <span className="ml-1 text-gray-900">{selectedSpecies.family}</span>
                    </div>
                  )}
                  {selectedSpecies.growth_rate && (
                    <div>
                      <span className="text-gray-600">{t('species.add.growthRate')}</span>
                      <span className="ml-1 text-gray-900">{selectedSpecies.growth_rate}</span>
                    </div>
                  )}
                  {(selectedSpecies.min_altitude_m || selectedSpecies.max_altitude_m) && (
                    <div>
                      <span className="text-gray-600">{t('species.add.altitude')}</span>
                      <span className="ml-1 text-gray-900">
                        {selectedSpecies.min_altitude_m || '?'}-{selectedSpecies.max_altitude_m || '?'}m
                      </span>
                    </div>
                  )}
                  {selectedSpecies.economic_value && (
                    <div>
                      <span className="text-gray-600">{t('species.add.economicValue')}</span>
                      <span className="ml-1 text-gray-900">{selectedSpecies.economic_value}</span>
                    </div>
                  )}
                </div>

                {selectedSpecies.main_uses && (
                  <div className="mt-2 text-sm">
                    <span className="text-gray-600">{t('species.add.mainUses')}</span>
                    <p className="mt-1 text-gray-900">{selectedSpecies.main_uses}</p>
                  </div>
                )}
              </div>

              {/* Role Selection */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('species.add.roleLabel')}
                </label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
                >
                  <option value="Dominant">{t('species.role.dominantSpecies')}</option>
                  <option value="Co-dominant">{t('species.role.coDominantSpecies')}</option>
                  <option value="Associate">{t('species.role.associateSpecies')}</option>
                  <option value="Occasional">{t('species.role.occasionalSpecies')}</option>
                  <option value="Rare">{t('species.role.rareSpecies')}</option>
                </select>
                <p className="mt-1 text-xs text-gray-500">
                  {t('species.add.roleHint')}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-gray-700 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
            disabled={adding}
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleAddSpecies}
            disabled={!selectedSpecies || adding}
            className={`px-4 py-2 rounded transition-colors ${
              !selectedSpecies || adding
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-green-600 text-white hover:bg-green-700'
            }`}
          >
            {adding ? t('species.adding') : t('species.addSpecies')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AddSpeciesModal;
