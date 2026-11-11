/** Location search component with geocoding – search by name, pin results on map. */
import React, { useState, useEffect } from 'react';
import { useT } from '../../i18n/hooks';
import { Search, MapPin, X, Eye, EyeOff } from 'lucide-react';
import axios from 'axios';

interface LocationSearchProps {
  onLocationSelected: (bounds: [number, number, number, number], geometry?: any) => void;
  onBoundaryToggle?: (show: boolean, geometry?: any) => void;
}

interface District {
  name: string;
}

interface Municipality {
  name: string;
  district: string;
}

interface Ward {
  id: number;
  ward: number;
  municipality: string;
  district: string;
  bounds?: [number, number, number, number];
}

interface SearchResult {
  id: number;
  display_name: string;
  district: string;
  municipality: string;
  ward: number;
  bounds: [number, number, number, number];
}

const LocationSearch: React.FC<LocationSearchProps> = ({
  onLocationSelected,
  onBoundaryToggle
}) => {
  const t = useT();
  // State for cascading dropdowns
  const [districts, setDistricts] = useState<District[]>([]);
  const [municipalities, setMunicipalities] = useState<Municipality[]>([]);
  const [wards, setWards] = useState<Ward[]>([]);

  // Selected values
  const [selectedDistrict, setSelectedDistrict] = useState<string>('');
  const [selectedMunicipality, setSelectedMunicipality] = useState<string>('');
  const [selectedWard, setSelectedWard] = useState<number | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showSearchResults, setShowSearchResults] = useState(false);

  // Boundary display state
  const [showBoundary, setShowBoundary] = useState(false);
  const [boundaryGeometry, setBoundaryGeometry] = useState<any>(null);

  // UI state
  const [searchMode, setSearchMode] = useState<'dropdown' | 'text'>('dropdown');

  // Load districts on mount
  useEffect(() => {
    loadDistricts();
  }, []);

  const loadDistricts = async () => {
    try {
      const response = await axios.get<District[]>('/api/location/districts');
      setDistricts(response.data);
    } catch (error) {
      console.error('Error loading districts:', error);
    }
  };

  const loadMunicipalities = async (district: string) => {
    try {
      const response = await axios.get<Municipality[]>(`/api/location/municipalities?district=${encodeURIComponent(district)}`);
      setMunicipalities(response.data);
      setWards([]);
    } catch (error) {
      console.error('Error loading municipalities:', error);
    }
  };

  const loadWards = async (municipality: string) => {
    try {
      const response = await axios.get<Ward[]>(`/api/location/wards?municipality=${encodeURIComponent(municipality)}&include_geometry=true`);
      setWards(response.data);
    } catch (error) {
      console.error('Error loading wards:', error);
    }
  };

  const handleDistrictChange = (district: string) => {
    setSelectedDistrict(district);
    setSelectedMunicipality('');
    setSelectedWard(null);
    if (district) {
      loadMunicipalities(district);
    } else {
      setMunicipalities([]);
      setWards([]);
    }
  };

  const handleMunicipalityChange = (municipality: string) => {
    setSelectedMunicipality(municipality);
    setSelectedWard(null);
    if (municipality) {
      loadWards(municipality);
    } else {
      setWards([]);
    }
  };

  const handleWardChange = async (wardId: number) => {
    setSelectedWard(wardId);
    const ward = wards.find(w => w.id === wardId);
    if (ward?.bounds) {
      // Zoom to ward bounds
      onLocationSelected(ward.bounds);

      // Load full geometry if boundary toggle is available
      if (onBoundaryToggle) {
        try {
          const response = await axios.get(`/api/location/ward/${wardId}/geometry`);
          setBoundaryGeometry(response.data.geometry);
        } catch (error) {
          console.error('Error loading ward geometry:', error);
        }
      }
    }
  };

  // Text search with debounce
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery.length >= 2) {
        performSearch();
      } else {
        setSearchResults([]);
        setShowSearchResults(false);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const performSearch = async () => {
    setSearching(true);
    try {
      const response = await axios.get<SearchResult[]>(`/api/location/search?q=${encodeURIComponent(searchQuery)}&limit=10`);
      setSearchResults(response.data);
      setShowSearchResults(true);
    } catch (error) {
      console.error('Error searching:', error);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleSearchResultClick = async (result: SearchResult) => {
    setSearchQuery(result.display_name);
    setShowSearchResults(false);

    // Zoom to result bounds
    onLocationSelected(result.bounds);

    // Load geometry for boundary display
    if (onBoundaryToggle) {
      try {
        const response = await axios.get(`/api/location/ward/${result.id}/geometry`);
        setBoundaryGeometry(response.data.geometry);
      } catch (error) {
        console.error('Error loading ward geometry:', error);
      }
    }
  };

  const toggleBoundaryDisplay = () => {
    const newShowBoundary = !showBoundary;
    setShowBoundary(newShowBoundary);
    if (onBoundaryToggle) {
      onBoundaryToggle(newShowBoundary, boundaryGeometry);
    }
  };

  const clearSelection = () => {
    setSelectedDistrict('');
    setSelectedMunicipality('');
    setSelectedWard(null);
    setSearchQuery('');
    setSearchResults([]);
    setShowSearchResults(false);
    setBoundaryGeometry(null);
    setShowBoundary(false);
    if (onBoundaryToggle) {
      onBoundaryToggle(false, null);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <MapPin className="w-5 h-5 text-blue-600" />
          {t('digitize.location.title')}
        </h3>

        {/* Mode Toggle */}
        <div className="flex gap-2">
          <button
            onClick={() => setSearchMode('dropdown')}
            className={`px-3 py-1 text-sm rounded ${
              searchMode === 'dropdown'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {t('digitize.location.browse')}
          </button>
          <button
            onClick={() => setSearchMode('text')}
            className={`px-3 py-1 text-sm rounded ${
              searchMode === 'text'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {t('digitize.location.search')}
          </button>
        </div>
      </div>

      {/* Cascading Dropdowns */}
      {searchMode === 'dropdown' && (
        <div className="space-y-3">
          {/* District */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('digitize.location.district')}
            </label>
            <select
              value={selectedDistrict}
              onChange={(e) => handleDistrictChange(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">{t('digitize.location.selectDistrict')}</option>
              {districts.map((district) => (
                <option key={district.name} value={district.name}>
                  {district.name}
                </option>
              ))}
            </select>
          </div>

          {/* Municipality */}
          {selectedDistrict && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('digitize.location.municipality')}
              </label>
              <select
                value={selectedMunicipality}
                onChange={(e) => handleMunicipalityChange(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={municipalities.length === 0}
              >
                <option value="">{t('digitize.location.selectMunicipality')}</option>
                {municipalities.map((municipality) => (
                  <option key={municipality.name} value={municipality.name}>
                    {municipality.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Ward */}
          {selectedMunicipality && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t('digitize.location.ward')}
              </label>
              <select
                value={selectedWard || ''}
                onChange={(e) => handleWardChange(parseInt(e.target.value))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={wards.length === 0}
              >
                <option value="">{t('digitize.location.selectWard')}</option>
                {wards.map((ward) => (
                  <option key={ward.id} value={ward.id}>
                    {t('digitize.location.wardN', { n: ward.ward })}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}

      {/* Text Search */}
      {searchMode === 'text' && (
        <div className="relative">
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('digitize.location.phSearch')}
              className="w-full px-4 py-2 pl-10 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <Search className="absolute left-3 top-2.5 w-5 h-5 text-gray-400" />
            {searching && (
              <div className="absolute right-3 top-2.5">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
              </div>
            )}
          </div>

          {/* Search Results Dropdown */}
          {showSearchResults && searchResults.length > 0 && (
            <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-64 overflow-y-auto">
              {searchResults.map((result) => (
                <button
                  key={result.id}
                  onClick={() => handleSearchResultClick(result)}
                  className="w-full px-4 py-2 text-left hover:bg-gray-100 border-b border-gray-100 last:border-b-0"
                >
                  <div className="text-sm font-medium text-gray-900">
                    {result.display_name}
                  </div>
                </button>
              ))}
            </div>
          )}

          {showSearchResults && searchResults.length === 0 && searchQuery.length >= 2 && !searching && (
            <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg p-4 text-center text-gray-500">
              {t('digitize.location.noResults')}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      {(selectedWard || searchQuery) && (
        <div className="mt-4 flex gap-2">
          {boundaryGeometry && onBoundaryToggle && (
            <button
              onClick={toggleBoundaryDisplay}
              className={`flex-1 px-4 py-2 rounded-md flex items-center justify-center gap-2 ${
                showBoundary
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {showBoundary ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
              {showBoundary ? t('digitize.location.hideBoundary') : t('digitize.location.showBoundary')}
            </button>
          )}

          <button
            onClick={clearSelection}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 flex items-center gap-2"
          >
            <X className="w-4 h-4" />
            {t('digitize.location.clear')}
          </button>
        </div>
      )}

      {/* Info Text */}
      <div className="mt-4 text-xs text-gray-500">
        {searchMode === 'dropdown' ? (
          <p>{t('digitize.location.hintBrowse')}</p>
        ) : (
          <p>{t('digitize.location.hintSearch')}</p>
        )}
      </div>
    </div>
  );
};

export default LocationSearch;
