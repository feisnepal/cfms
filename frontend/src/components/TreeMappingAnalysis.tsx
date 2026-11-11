/** TreeMappingAnalysis — tree mapping analysis view with hierarchy summary sections. */
import { useState, useEffect } from 'react';
import { inventoryApi } from '../services/api';
import { HierarchySummarySection } from './TreeMappingAnalysis/HierarchySummarySection';
import { SpeciesHierarchySection } from './TreeMappingAnalysis/SpeciesHierarchySection';
import { DBHHierarchySection } from './TreeMappingAnalysis/DBHHierarchySection';
import { StandTypeSection } from './TreeMappingAnalysis/StandTypeSection';
import { CarbonHierarchySection } from './TreeMappingAnalysis/CarbonHierarchySection';
import { VolumeHierarchySection } from './TreeMappingAnalysis/VolumeHierarchySection';
import { MotherTreeCoverageSection } from './TreeMappingAnalysis/MotherTreeCoverageSection';
import { FellingAnalysisSection } from './TreeMappingAnalysis/FellingAnalysisSection';
import { useT } from '../i18n/hooks';

interface TreeMappingAnalysisProps {
  mappingId: string;
}

interface AnalysisData {
  sm_available: boolean;
  sm_total_blocks_analyzed?: number;
  sm_total_trees_analyzed?: number;
  sm_hierarchy_summary?: any[];
  sm_species_by_hierarchy?: any[];
  sm_species_diversity?: any[];
  sm_dbh_by_hierarchy?: any[];
  sm_dbh_species_by_hierarchy?: any[];
  sm_stand_type_by_hierarchy?: any[];
  sm_forest_structure_status?: any;
  sm_carbon_by_hierarchy?: any[];
  sm_total_carbon_tc?: number;
  sm_total_co2_tco2?: number;
  sm_volume_by_hierarchy?: any[];
  sm_top_species_by_volume?: any[];
  sm_mother_tree_coverage?: any;
  sm_mother_tree_by_hierarchy?: any[];
  sm_mother_tree_by_species?: any[];
  sm_felling_tree_by_species?: any[];
  sm_mother_felling_summary?: any;
  sm_hierarchy_remark_breakdown?: Record<string, any>;
  sm_species_hier_remark?: any[];
  sm_dbh_hier_remark?: any[];
  sm_felling_dbh_analysis?: any[];
  sm_felling_species_analysis?: any[];
  sm_felling_totals?: any;
}

export function TreeMappingAnalysis({ mappingId }: TreeMappingAnalysisProps) {
  const t = useT();
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const result = await inventoryApi.getInventoryAnalysis(mappingId);
        setData(result);
      } catch (err: any) {
        setError(err.message || t('treeMapping.analysisLoadFailed'));
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [mappingId]);

  const toggleSection = (key: string) => {
    setCollapsed(prev => ({ ...prev, [key]: !prev[key] }));
  };

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-8 text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-600 mx-auto mb-4"></div>
        <p className="text-gray-500">विश्लेषण लोड गर्दै... / Loading analysis...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-red-600 mb-2">{t('treeMapping.errorLoadingAnalysis')}</h3>
        <p className="text-gray-600">{error}</p>
      </div>
    );
  }

  if (!data || !data.sm_available) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">विश्लेषित ब्लक सङ्ख्या</p>
          <p className="text-2xl font-bold text-green-600">{data.sm_total_blocks_analyzed || 0}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">विश्लेषित कुल रूख सङ्ख्या</p>
          <p className="text-2xl font-bold text-green-600">{data.sm_total_trees_analyzed || 0}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">कुल कार्बन मौज्दात (tC)</p>
          <p className="text-2xl font-bold text-green-600">{data.sm_total_carbon_tc?.toFixed(2) || '0'}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">कुल CO₂ समतुल्य (tCO₂)</p>
          <p className="text-2xl font-bold text-green-600">{data.sm_total_co2_tco2?.toFixed(2) || '0'}</p>
        </div>
      </div>

      {/* Section 1: Spatial Hierarchy Summary */}
      <HierarchySummarySection
        data={data.sm_hierarchy_summary || []}
        remarkBreakdown={data.sm_hierarchy_remark_breakdown}
        collapsed={collapsed['hierarchy']}
        onToggle={() => toggleSection('hierarchy')}
      />

      {/* Section 2: Species by Spatial Level */}
      <SpeciesHierarchySection
        speciesData={data.sm_species_by_hierarchy || []}
        diversityData={data.sm_species_diversity || []}
        hierRemarkData={data.sm_species_hier_remark || []}
        collapsed={collapsed['species']}
        onToggle={() => toggleSection('species')}
      />

      {/* Section 3: DBH by Spatial Level */}
      <DBHHierarchySection
        data={data.sm_dbh_by_hierarchy || []}
        hierRemarkData={data.sm_dbh_hier_remark || []}
        collapsed={collapsed['dbh']}
        onToggle={() => toggleSection('dbh')}
      />

      {/* Section 4: Stand Type & Forest Structure */}
      <StandTypeSection
        hierarchyData={data.sm_stand_type_by_hierarchy || []}
        statusData={data.sm_forest_structure_status}
        collapsed={collapsed['stand']}
        onToggle={() => toggleSection('stand')}
      />

      {/* Section 5: Carbon Stock */}
      <CarbonHierarchySection
        data={data.sm_carbon_by_hierarchy || []}
        collapsed={collapsed['carbon']}
        onToggle={() => toggleSection('carbon')}
      />

      {/* Section 6: Volume Distribution */}
      <VolumeHierarchySection
        hierarchyData={data.sm_volume_by_hierarchy || []}
        topSpeciesData={data.sm_top_species_by_volume || []}
        collapsed={collapsed['volume']}
        onToggle={() => toggleSection('volume')}
      />

      {/* Section 7: Mother Tree Coverage & Species Analysis */}
      <MotherTreeCoverageSection
        coverageData={data.sm_mother_tree_coverage}
        hierarchyData={data.sm_mother_tree_by_hierarchy || []}
        remarkBreakdown={data.sm_hierarchy_remark_breakdown}
        motherBySpecies={data.sm_mother_tree_by_species || []}
        fellingBySpecies={data.sm_felling_tree_by_species || []}
        summary={data.sm_mother_felling_summary}
        collapsed={collapsed['mother']}
        onToggle={() => toggleSection('mother')}
      />

      {/* Section 8: Felling Tree Analysis (DBH >= 30cm) */}
      <FellingAnalysisSection
        totals={data.sm_felling_totals}
        dbhData={data.sm_felling_dbh_analysis || []}
        speciesData={data.sm_felling_species_analysis || []}
        collapsed={collapsed['felling']}
        onToggle={() => toggleSection('felling')}
      />
    </div>
  );
}
