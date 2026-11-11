/** BiodiversityTab — tab for biodiversity assessment data, species richness, and diversity indices. */
import React, { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import { formatNumber } from '../i18n/numberFormat';
import { useT } from '../i18n/hooks';

interface BiodiversitySpecies {
  id: string;
  category: string;
  sub_category: string | null;
  nepali_name: string;
  english_name: string;
  scientific_name: string;
  primary_use: string | null;
  secondary_uses: string | null;
  iucn_status: string | null;
  cites_appendix: string | null;
  distribution: string | null;
  notes: string | null;
  is_invasive: boolean;
  is_protected: boolean;
}

interface SelectedSpecies {
  id: string;
  species_id: string;
  calculation_id: string;
  presence_status: string;
  recorded_at: string;
  species: BiodiversitySpecies;
  abundance?: string;
}

interface BiodiversityTabProps {
  calculationId: string;
  /**
   * Which pane of the step's Data / Results split to render. The step's host
   * mounts only the active pane, so this is the split point, not a prop both
   * copies receive.
   *
   * Data is choosing the species and recording what is present. Results is the
   * OP document variables derived from that choice — the preview, the value
   * cards, the sub-category breakdown and the counts. So the split falls exactly
   * on the boundary the page already had: nothing above line 465 can be derived
   * from a species list that does not exist yet.
   */
  view?: 'data' | 'results';
  /** Called after the recorded species changed, so the shell re-reads readiness and unlocks (or re-locks) the Results tab. */
  onStepDataChanged?: () => void;
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
}

function VarCopyBtn({ varKey, label }: { varKey: string; label?: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const template = `{{${varKey}}}`;
  const handleClick = () => {
    copyToClipboard(template);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <button
      onClick={handleClick}
      title={t('biodiversity.copyTemplate', { name: template })}
      className="group relative inline-flex items-center gap-1 text-xs text-gray-600 hover:text-emerald-700 cursor-pointer transition-colors"
    >
      {label || varKey}
      <span className={`text-[10px] ${copied ? 'text-emerald-600' : 'text-gray-300 group-hover:text-emerald-400'}`}>
        {copied ? `✓ ${t('biodiversity.copied')}` : '📋'}
      </span>
    </button>
  );
}

const IUCN_LABEL_KEY: Record<string, string> = {
  CR: 'biodiversity.iucn.cr', EN: 'biodiversity.iucn.en', VU: 'biodiversity.iucn.vu',
  NT: 'biodiversity.iucn.nt', LC: 'biodiversity.iucn.lc', DD: 'biodiversity.iucn.dd',
};

const SUB_CATEGORY_KEY: Record<string, string> = {
  Tree: 'biodiversity.subCat.tree', Shrub: 'biodiversity.subCat.shrub',
  Bamboo: 'biodiversity.subCat.bamboo', Grass: 'biodiversity.subCat.grass',
  Herb: 'biodiversity.subCat.herb', Climber: 'biodiversity.subCat.climber',
  Mammal: 'biodiversity.subCat.mammal', Bird: 'biodiversity.subCat.bird',
  Reptile: 'biodiversity.subCat.reptile', Amphibian: 'biodiversity.subCat.amphibian',
  Fish: 'biodiversity.subCat.fish', Insect: 'biodiversity.subCat.insect',
  Fungus: 'biodiversity.subCat.fungus', Other: 'biodiversity.subCat.other',
};

  const BiodiversityTab: React.FC<BiodiversityTabProps> = ({ calculationId, view, onStepDataChanged }) => {
  const t = useT();
  const [activeCategory, setActiveCategory] = useState<'vegetation' | 'animal'>('vegetation');
  const [availableSpecies, setAvailableSpecies] = useState<BiodiversitySpecies[]>([]);
  const [selectedSpecies, setSelectedSpecies] = useState<SelectedSpecies[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterSubCategory, setFilterSubCategory] = useState<string>('');
  const [filterIUCN, setFilterIUCN] = useState<string>('');
  const [filterInvasive, setFilterInvasive] = useState<boolean | null>(null);
  const [categories, setCategories] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [opVariables, setOpVariables] = useState<any[]>([]);
  const [opSummary, setOpSummary] = useState<string>('');
  const [showOpVars, setShowOpVars] = useState(false);

  useEffect(() => {
    loadCategories();
  }, []);

  useEffect(() => {
    loadAvailableSpecies();
  }, [activeCategory, filterSubCategory, searchTerm, filterIUCN, filterInvasive]);

  // The field inventory's unique tree species are listed here automatically (no confirmation): once per processed inventory,
  // so a species removed afterwards stays removed. Covers inventories uploaded before this existed; processing a new one does the
  // same on the server. A forest with no inventory (or one already listed) answers `up_to_date` and nothing changes.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await api.post(`/api/biodiversity/calculations/${calculationId}/species/sync-from-inventory`);
        if (live && res?.data?.added) {
          await loadSelectedSpecies();
          onStepDataChanged?.();
        }
      } catch (err) {
        // Best effort: the list still works without it. Logged, never shown as an error on the page.
        console.warn('Biodiversity: could not list the inventory species:', err);
      }
      if (live) await loadSelectedSpecies();
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId]);

  // Load OP variable catalog for biodiversity variables
  const loadOpVariables = useCallback(async () => {
    try {
      const res = await api.get(`/api/operational-plans/${calculationId}/variable-catalog`, {
        params: { category: 'A' }
      });
      const bioTableKeys = ['table:biodiversity', 'table:iucn_status', 'table:protected_species', 'table:invasive_species', 'table:vegetation_species', 'table:animal_species'];
      const vars = (res.data.variables || []).filter(
        (v: any) => v.key.startsWith('bio_') || v.key === 'section:biodiversity' || bioTableKeys.includes(v.key)
      );
      setOpVariables(vars);
      const sectionVar = vars.find((v: any) => v.key === 'section:biodiversity');
      if (sectionVar && sectionVar.sample_value) {
        setOpSummary(typeof sectionVar.sample_value === 'string' ? sectionVar.sample_value : '');
      } else {
        setOpSummary('');
      }
    } catch {
      // Variable catalog not yet available
    }
  }, [calculationId]);

  useEffect(() => {
    if (selectedSpecies.length > 0) {
      loadOpVariables();
    }
  }, [selectedSpecies.length, loadOpVariables]);

  const loadCategories = async () => {
    try {
      const response = await api.get('/api/biodiversity/categories');
      setCategories(response.data);
    } catch (error) {
      console.error('Error loading categories:', error);
    }
  };

  const loadAvailableSpecies = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('category', activeCategory);
      params.append('page_size', '500');

      if (filterSubCategory) params.append('sub_category', filterSubCategory);
      if (searchTerm) params.append('search', searchTerm);
      if (filterIUCN) params.append('iucn_status', filterIUCN);
      if (filterInvasive !== null) params.append('is_invasive', filterInvasive.toString());

      const response = await api.get(`/api/biodiversity/species?${params.toString()}`);
      setAvailableSpecies(response.data.items);
    } catch (error) {
      console.error('Error loading species:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadSelectedSpecies = async () => {
    try {
      const response = await api.get(`/api/biodiversity/calculations/${calculationId}/species`);
      setSelectedSpecies(response.data.species);
    } catch (error) {
      console.error('Error loading selected species:', error);
    }
  };

  const handleAddSpecies = async (speciesId: string) => {
    setSaving(true);
    try {
      await api.post(`/api/biodiversity/calculations/${calculationId}/species/bulk`, {
        species_ids: [speciesId],
        presence_status: 'present'
      });
      await loadSelectedSpecies();
      onStepDataChanged?.();
    } catch (error: any) {
      console.error('Error adding species:', error);
      if (error.response?.status === 400) {
        alert(t('biodiversity.msgAlreadyAdded'));
      }
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveSpecies = async (speciesId: string) => {
    if (!confirm(t('biodiversity.confirmRemove'))) return;

    setSaving(true);
    try {
      await api.delete(`/api/biodiversity/calculations/${calculationId}/species/${speciesId}`);
      await loadSelectedSpecies();
      onStepDataChanged?.();
    } catch (error) {
      console.error('Error removing species:', error);
    } finally {
      setSaving(false);
    }
  };

  const getIUCNBadgeColor = (status: string | null) => {
    if (!status) return 'bg-gray-100 text-gray-600';
    switch (status) {
      case 'CR': return 'bg-red-600 text-white';
      case 'EN': return 'bg-orange-500 text-white';
      case 'VU': return 'bg-yellow-500 text-white';
      case 'NT': return 'bg-yellow-300 text-gray-800';
      case 'LC': return 'bg-green-100 text-green-700';
      default: return 'bg-gray-100 text-gray-600';
    }
  };

  const isSpeciesSelected = (speciesId: string) => {
    return selectedSpecies.some(s => s.species.id === speciesId);
  };

  const selectedInCategory = selectedSpecies.filter(s => s.species.category === activeCategory);
  const subCategories = categories[activeCategory]?.sub_categories || {};

  const vegCount = selectedSpecies.filter(s => s.species.category === 'vegetation').length;
  const animalCount = selectedSpecies.filter(s => s.species.category === 'animal').length;
  const protectedCount = selectedSpecies.filter(s =>
    s.species.is_protected || ['CR', 'EN', 'VU'].includes(s.species.iucn_status || '')
  ).length;
  const invasiveCount = selectedSpecies.filter(s => s.species.is_invasive).length;

  // IUCN breakdown from selected species
  const iucnCounts: Record<string, number> = {};
  selectedSpecies.forEach(item => {
    const s = item.species.iucn_status || 'DD';
    iucnCounts[s] = (iucnCounts[s] || 0) + 1;
  });
  const iucnOrder = ['CR', 'EN', 'VU', 'NT', 'LC', 'DD'];

  // Get variable by key from catalog
  const getVarValue = (key: string) => {
    const v = opVariables.find(x => x.key === key);
    if (!v || v.data_status === 'empty') return null;
    return v.sample_value;
  };

  return (
    <div className="space-y-4">
      {view !== 'results' && (
        <>
      {/* Category Tabs */}
      <div className="border-b border-gray-200">
        <div className="flex space-x-4">
          <button
            onClick={() => setActiveCategory('vegetation')}
            className={`px-6 py-3 border-b-2 font-medium text-sm ${
              activeCategory === 'vegetation'
                ? 'border-green-500 text-green-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Vegetation ({vegCount})
          </button>
          <button
            onClick={() => setActiveCategory('animal')}
            className={`px-6 py-3 border-b-2 font-medium text-sm ${
              activeCategory === 'animal'
                ? 'border-green-500 text-green-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Animals ({animalCount})
          </button>
        </div>
      </div>

      {/* Two-panel layout */}
      <div className="grid grid-cols-2 gap-4">
        {/* Left Panel: Available Species */}
        <div className="border rounded-lg p-4 bg-white">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-semibold text-lg">{t('biodiversity.availableSpecies')}</h3>
            <span className="text-sm text-gray-500">{availableSpecies.length} species</span>
          </div>

          <div className="mb-4">
            <input
              type="text"
              placeholder={t('biodiversity.searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500"
            />
          </div>

          <div className="space-y-2 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('biodiversity.subCategory')}</label>
              <select
                value={filterSubCategory}
                onChange={(e) => setFilterSubCategory(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500"
              >
                <option value="">{t('biodiversity.all')}</option>
                {Object.keys(subCategories).map(subCat => (
                  <option key={subCat} value={subCat}>
                    {subCat} ({subCategories[subCat]})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('biodiversity.iucnStatus')}</label>
              <select
                value={filterIUCN}
                onChange={(e) => setFilterIUCN(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-green-500"
              >
                <option value="">{t('biodiversity.all')}</option>
                <option value="CR">{t('biodiversity.iucn.crFull')}</option>
                <option value="EN">{t('biodiversity.iucn.enFull')}</option>
                <option value="VU">{t('biodiversity.iucn.vuFull')}</option>
                <option value="NT">{t('biodiversity.iucn.ntFull')}</option>
                <option value="LC">{t('biodiversity.iucn.lcFull')}</option>
              </select>
            </div>

            <div className="flex items-center">
              <input
                type="checkbox"
                checked={filterInvasive === true}
                onChange={(e) => setFilterInvasive(e.target.checked ? true : null)}
                className="mr-2"
              />
              <label className="text-sm text-gray-700">{t('biodiversity.invasiveOnly')}</label>
            </div>
          </div>

          <div className="space-y-2 max-h-[600px] overflow-y-auto">
            {loading ? (
              <div className="text-center py-8 text-gray-500">{t('biodiversity.loadingSpecies')}</div>
            ) : availableSpecies.length === 0 ? (
              <div className="text-center py-8 text-gray-500">{t('biodiversity.noSpeciesFound')}</div>
            ) : (
              availableSpecies.map(species => (
                <div
                  key={species.id}
                  className={`border rounded-lg p-3 ${
                    isSpeciesSelected(species.id)
                      ? 'bg-green-50 border-green-300'
                      : 'hover:bg-gray-50 cursor-pointer'
                  }`}
                  onClick={() => !isSpeciesSelected(species.id) && handleAddSpecies(species.id)}
                >
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <div className="font-semibold text-gray-900">{species.nepali_name}</div>
                      <div className="text-sm text-gray-600">{species.english_name}</div>
                      <div className="text-xs italic text-gray-500">{species.scientific_name}</div>
                    </div>
                    {isSpeciesSelected(species.id) && (
                      <span className="text-green-600 text-sm">✓ Selected</span>
                    )}
                  </div>

                  <div className="flex gap-2 mt-2 flex-wrap">
                    {species.iucn_status && (
                      <span className={`text-xs px-2 py-1 rounded ${getIUCNBadgeColor(species.iucn_status)}`}>
                        {species.iucn_status}
                      </span>
                    )}
                    {species.is_invasive && (
                      <span className="text-xs px-2 py-1 rounded bg-red-100 text-red-700">
                        {t('biodiversity.invasive')}
                      </span>
                    )}
                    {species.cites_appendix && species.cites_appendix !== 'Not listed' && (
                      <span className="text-xs px-2 py-1 rounded bg-blue-100 text-blue-700">
                        CITES
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Panel: Selected Species */}
        <div className="border rounded-lg p-4 bg-white">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-semibold text-lg">{t('biodiversity.selectedSpecies')}</h3>
            <span className="text-sm text-gray-500">{selectedInCategory.length} selected</span>
          </div>

          {selectedInCategory.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              {t('biodiversity.noneSelected')}
            </div>
          ) : (
            <div className="overflow-x-auto max-h-[700px] overflow-y-auto">
              <table className="w-full text-xs whitespace-nowrap">
                <thead className="bg-gray-50 sticky top-0 z-10">
                  <tr className="text-left text-gray-600 border-b">
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.name')}</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.scientificName')}</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.subCategory')}</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.mainUses')}</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.iucnStatus')}</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.protected')}</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.invasive')}</th>
                    <th className="py-2 pr-2 font-medium">CITES</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.abundance')}</th>
                    <th className="py-2 pr-2 font-medium">{t('biodiversity.col.presence')}</th>
                    <th className="py-2 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {selectedInCategory.map(item => (
                    <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-2 pr-2">
                        <div className="font-semibold text-gray-900">{item.species.nepali_name}</div>
                        <div className="text-gray-500">{item.species.english_name}</div>
                      </td>
                      <td className="py-2 pr-2 italic text-gray-600">{item.species.scientific_name}</td>
                      <td className="py-2 pr-2">{item.species.sub_category || '—'}</td>
                      <td className="py-2 pr-2">{item.species.primary_use || '—'}</td>
                      <td className="py-2 pr-2">
                        {item.species.iucn_status ? (
                          <span className={`inline-block px-1.5 py-0.5 rounded text-xs ${getIUCNBadgeColor(item.species.iucn_status)}`}>
                            {item.species.iucn_status}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="py-2 pr-2">{item.species.is_protected ? '✓' : '—'}</td>
                      <td className="py-2 pr-2">{item.species.is_invasive ? '✓' : '—'}</td>
                      <td className="py-2 pr-2">{item.species.cites_appendix && item.species.cites_appendix !== 'Not listed' ? item.species.cites_appendix : '—'}</td>
                      <td className="py-2 pr-2">{item.abundance ?? '—'}</td>
                      <td className="py-2 pr-2">{item.presence_status || '—'}</td>
                      <td className="py-2">
                        <button
                          onClick={() => handleRemoveSpecies(item.species.id)}
                          disabled={saving}
                          className="text-red-600 hover:text-red-800 text-xs"
                        >
                          {t('biodiversity.col.remove')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
          </>
        )}

      {view !== 'data' && (
        <>
      {/* OP Document Variables Preview */}
      {selectedSpecies.length > 0 && (
        <div className="bg-white border border-emerald-200 rounded-lg p-4">
          <div className="flex justify-between items-center mb-3">
            <h4 className="font-semibold text-emerald-800">
              {t('biodiversity.opVarsTitle')}
              <span className="text-sm font-normal text-gray-500 ml-2">{t('biodiversity.opVarsSubtitle')}</span>
            </h4>
            <button
              onClick={() => setShowOpVars(!showOpVars)}
              className="text-sm text-emerald-600 hover:text-emerald-800"
            >
              {showOpVars ? t('biodiversity.hideDetails') : t('biodiversity.showDetails')}
            </button>
          </div>

          {/* Variable Value Cards — all bio_* variables clickable */}
          <div className="grid grid-cols-5 gap-3 mb-3">
            <div className="bg-blue-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-blue-700">{formatNumber(selectedSpecies.length)}</div>
              <VarCopyBtn varKey="bio_total_species" label="bio_total_species" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.totalSpecies')}</div>
            </div>
            <div className="bg-green-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-green-700">{formatNumber(vegCount)}</div>
              <VarCopyBtn varKey="bio_vegetation_count" label="bio_vegetation_count" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.vegetation')}</div>
            </div>
            <div className="bg-orange-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-orange-700">{formatNumber(animalCount)}</div>
              <VarCopyBtn varKey="bio_animal_count" label="bio_animal_count" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.animals')}</div>
            </div>
            <div className="bg-purple-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-purple-700">{formatNumber(protectedCount)}</div>
              <VarCopyBtn varKey="bio_protected_count" label="bio_protected_count" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.col.protected')}</div>
            </div>
            <div className="bg-red-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-red-700">{formatNumber(invasiveCount)}</div>
              <VarCopyBtn varKey="bio_invasive_count" label="bio_invasive_count" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.col.invasive')}</div>
            </div>
            <div className="bg-red-100 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-red-800">{formatNumber(iucnCounts.CR || 0)}</div>
              <VarCopyBtn varKey="bio_iucn_cr" label="bio_iucn_cr" />
              <div className="text-[10px] text-gray-600">{t('biodiversity.stat.cr')}</div>
            </div>
            <div className="bg-orange-100 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-orange-800">{formatNumber(iucnCounts.EN || 0)}</div>
              <VarCopyBtn varKey="bio_iucn_en" label="bio_iucn_en" />
              <div className="text-[10px] text-gray-600">{t('biodiversity.stat.en')}</div>
            </div>
            <div className="bg-yellow-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-yellow-700">{formatNumber(iucnCounts.VU || 0)}</div>
              <VarCopyBtn varKey="bio_iucn_vu" label="bio_iucn_vu" />
              <div className="text-[10px] text-gray-600">{t('biodiversity.stat.vu')}</div>
            </div>
            <div className="bg-teal-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-teal-700">{formatNumber(vegCount)}</div>
              <VarCopyBtn varKey="bio_vegetation" label="bio_vegetation" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.vegList')}</div>
            </div>
            <div className="bg-cyan-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-cyan-700">{formatNumber(animalCount)}</div>
              <VarCopyBtn varKey="bio_animals" label="bio_animals" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.animalList')}</div>
            </div>
          </div>

          {/* Sub-category breakdown — copyable badges */}
          {(() => {
            const subCats = Object.entries(
              selectedSpecies.reduce((acc: Record<string, number>, item) => {
                const sc = item.species.sub_category || 'Other';
                acc[sc] = (acc[sc] || 0) + 1;
                return acc;
              }, {} as Record<string, number>)
            ).sort((a, b) => b[1] - a[1]);
            if (subCats.length === 0) return null;
            return (
              <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
                <span className="font-medium text-gray-600 mr-1">
                  <VarCopyBtn varKey="bio_sub_category_breakdown" label="sub_category:" />
                </span>
                {subCats.map(([cat, cnt]) => (
                  <span key={cat} className="inline-flex items-center gap-1 bg-gray-100 text-gray-700 px-2 py-0.5 rounded">
                    <span className="font-medium">{SUB_CATEGORY_KEY[cat] ? t(SUB_CATEGORY_KEY[cat]) : cat}</span>
                    <span>{formatNumber(cnt)}</span>
                  </span>
                ))}
              </div>
            );
          })()}

          {/* Biodiversity Table Variables — copyable table references */}
          <div className="grid grid-cols-5 gap-3 mb-3">
            <div className="bg-emerald-50 rounded-lg p-3 text-center border border-emerald-200">
              <div className="text-lg font-bold text-emerald-700">{formatNumber(selectedSpecies.length)}</div>
              <VarCopyBtn varKey="table:biodiversity" label="table:biodiversity" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.biodiversity')}</div>
            </div>
            <div className="bg-indigo-50 rounded-lg p-3 text-center border border-indigo-200">
              <div className="text-lg font-bold text-indigo-700">{formatNumber(iucnOrder.filter(c => (iucnCounts[c] || 0) > 0).length)}</div>
              <VarCopyBtn varKey="table:iucn_status" label="table:iucn_status" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.conservationStatus')}</div>
            </div>
            <div className="bg-lime-50 rounded-lg p-3 text-center border border-lime-200">
              <div className="text-lg font-bold text-lime-700">{formatNumber(vegCount)}</div>
              <VarCopyBtn varKey="table:vegetation_species" label="table:vegetation_species" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.vegList')}</div>
            </div>
            <div className="bg-sky-50 rounded-lg p-3 text-center border border-sky-200">
              <div className="text-lg font-bold text-sky-700">{formatNumber(animalCount)}</div>
              <VarCopyBtn varKey="table:animal_species" label="table:animal_species" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.animalList')}</div>
            </div>
            <div className="bg-violet-50 rounded-lg p-3 text-center border border-violet-200">
              <div className="text-lg font-bold text-violet-700">{formatNumber(protectedCount)}</div>
              <VarCopyBtn varKey="table:protected_species" label="table:protected_species" />
              <div className="text-[10px] text-gray-500">{t('biodiversity.stat.protectedList')}</div>
            </div>
          </div>

          {/* section:biodiversity — full-width Nepali summary */}
          {opSummary && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3">
              <div className="flex items-center justify-between mb-1">
                <VarCopyBtn varKey="section:biodiversity" label="section:biodiversity" />
                <button
                  onClick={() => copyToClipboard(opSummary)}
                  className="text-xs text-emerald-600 hover:text-emerald-800 border border-emerald-300 px-2 py-0.5 rounded"
                >
                  {t('biodiversity.copyText')}
                </button>
              </div>
              <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-line">
                {opSummary}
              </p>
            </div>
          )}

          {/* Expanded Variable Detail Table */}
          {showOpVars && opVariables.length > 0 && (
            <div className="mt-3 border-t border-emerald-100 pt-3">
              <div className="flex justify-end mb-2">
                <button
                  onClick={() => {
                    const all = opVariables.filter(v => v.data_status === 'available').map(v => `{{${v.key}}}`).join(' ');
                    copyToClipboard(all);
                    alert(t('biodiversity.msgAllCopied'));
                  }}
                  className="text-xs text-emerald-600 hover:text-emerald-800 border border-emerald-300 px-2 py-1 rounded"
                >
                  {t('biodiversity.copyAll')}
                </button>
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-gray-500 border-b">
                    <th className="pb-1 pr-2">{t('biodiversity.varCol.variable')}</th>
                    <th className="pb-1 pr-2">{t('biodiversity.varCol.nepaliName')}</th>
                    <th className="pb-1 pr-2">{t('biodiversity.varCol.value')}</th>
                    <th className="pb-1">{t('biodiversity.varCol.status')}</th>
                  </tr>
                </thead>
                <tbody>
                  {opVariables.map(v => (
                    <tr key={v.key} className="border-b border-gray-100">
                      <td className="py-1 pr-2">
                        <VarCopyBtn varKey={v.key} />
                      </td>
                      <td className="py-1 pr-2 text-gray-600">{v.label_ne}</td>
                      <td className="py-1 pr-2 text-gray-800">
                        {v.data_status === 'available'
                          ? typeof v.sample_value === 'object'
                            ? JSON.stringify(v.sample_value).substring(0, 60) + '...'
                            : String(v.sample_value)
                          : '—'}
                      </td>
                      <td className="py-1">
                        <span className={`inline-block px-1.5 py-0.5 rounded ${
                          v.data_status === 'available'
                            ? 'bg-green-100 text-green-700'
                            : 'bg-gray-100 text-gray-500'
                        }`}>
                          {v.data_status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Summary Stats */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h4 className="font-semibold mb-2">{t('biodiversity.summaryTitle')}</h4>
        <div className="grid grid-cols-5 gap-4 text-sm">
          <div>
            <div className="text-gray-600">{t('biodiversity.totalSpecies')}</div>
            <div className="text-2xl font-bold text-blue-600">{selectedSpecies.length}</div>
          </div>
          <div>
            <div className="text-gray-600">{t('biodiversity.vegetation')}</div>
            <div className="text-2xl font-bold text-green-600">{vegCount}</div>
          </div>
          <div>
            <div className="text-gray-600">{t('biodiversity.animals')}</div>
            <div className="text-2xl font-bold text-orange-600">{animalCount}</div>
          </div>
          <div>
            <div className="text-gray-600">{t('biodiversity.protected')}</div>
            <div className="text-2xl font-bold text-red-600">{protectedCount}</div>
          </div>
          <div>
            <div className="text-gray-600">{t('biodiversity.invasive')}</div>
            <div className="text-2xl font-bold text-rose-600">{invasiveCount}</div>
          </div>
        </div>
      </div>
          </>
        )}
    </div>
  );
};

export default BiodiversityTab;