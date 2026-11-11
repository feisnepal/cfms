/** RasterLayerControl — control for toggling raster tile layer visibility on the map. */
import React, { useState, useMemo } from 'react';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';
import { TileLayer } from 'react-leaflet';
import { API_BASE_URL } from '../services/api';
import { useTileToken, withTileToken } from '../hooks/useTileToken';
import {
  STATIC_LEGENDS,
  generateDynamicElevationLegend,
  generateDynamicCanopyLegend,
  generateDynamicTemperatureLegend,
  generateDynamicPrecipitationLegend,
  generateDynamicBiomassLegend,
  generateDynamicSlopeLegend,
  generateDynamicMinTempColdestLegend,
  generateDynamicLandcoverLegend,
  generateDynamicNasaForestLegend,
  generateDynamicAspectLegend,
  generateDynamicForestHealthLegend,
  generateDynamicForestTypeLegend,
  generateDynamicFireLossLegend,
  type LegendItem,
} from '../lib/rasterLegends';

interface RasterLayer {
  id: string;
  /** i18n keys: the array is module scope, so these resolve at render (rule 4). */
  nameKey: string;
  descriptionKey: string;
  legend: LegendItem[];
  source?: string;  // Data source citation
  resolution?: string;  // Spatial resolution
  year?: string;  // Data year
}

// Layer definitions with predefined color legends (static legends live in lib/rasterLegends)
const RASTER_LAYERS: RasterLayer[] = [
  {
    id: 'slope',
    nameKey: 'raster.layer.slopeName',
    descriptionKey: 'raster.layer.slopeDesc',
    source: 'Derived from SRTM DEM',
    resolution: '30m',
    legend: [] // Will be populated dynamically based on which slope codes are present
  },
  {
    id: 'aspect',
    nameKey: 'raster.layer.aspectName',
    descriptionKey: 'raster.layer.aspectDesc',
    source: 'Derived from SRTM DEM',
    resolution: '30m',
    legend: STATIC_LEGENDS.aspect
  },
  {
    id: 'dem',
    nameKey: 'raster.layer.demName',
    descriptionKey: 'raster.layer.demDesc',
    source: 'SRTM 1 Arc-Second Global',
    resolution: '30m',
    year: '2000',
    legend: [] // Will be populated dynamically based on actual min/max elevation
  },
  {
    id: 'canopy',
    nameKey: 'raster.layer.canopyName',
    descriptionKey: 'raster.layer.canopyDesc',
    source: 'ETH Zurich / GEDI',
    resolution: '30m',
    year: '2020',
    legend: [] // Will be populated dynamically based on actual min/max canopy height
  },
  {
    id: 'biomass',
    nameKey: 'raster.layer.biomassName',
    descriptionKey: 'raster.layer.biomassDesc',
    source: 'ESA CCI AGB V6',
    resolution: '100m',
    year: '2022',
    legend: [] // Will be populated dynamically based on actual min/max biomass
  },
  {
    id: 'temperature',
    nameKey: 'raster.layer.temperatureName',
    descriptionKey: 'raster.layer.temperatureDesc',
    source: 'WorldClim 2.1',
    resolution: '1km',
    year: '1970-2000',
    legend: [] // Will be populated dynamically based on actual min/max temperature
  },
  {
    id: 'precipitation',
    nameKey: 'raster.layer.precipitationName',
    descriptionKey: 'raster.layer.precipitationDesc',
    source: 'WorldClim 2.1',
    resolution: '1km',
    year: '1970-2000',
    legend: [] // Will be populated dynamically based on actual min/max precipitation
  },
  {
    id: 'forest_health',
    nameKey: 'raster.layer.forestHealthName',
    descriptionKey: 'raster.layer.forestHealthDesc',
    source: 'Sentinel-2/Landsat NDVI',
    resolution: '10-30m',
    year: '2023',
    legend: STATIC_LEGENDS.forest_health
  },
  {
    id: 'min_temp_coldest',
    nameKey: 'raster.layer.minTempColdestName',
    descriptionKey: 'raster.layer.minTempColdestDesc',
    source: 'WorldClim 2.1',
    resolution: '1km',
    year: '1970-2000',
    legend: [] // Will be populated dynamically based on actual min/max values
  },
  {
    id: 'nasa_forest_2020',
    nameKey: 'raster.layer.nasaForest2020Name',
    descriptionKey: 'raster.layer.nasaForest2020Desc',
    source: 'NASA/ORNL DAAC',
    resolution: '30m',
    year: '2020',
    legend: STATIC_LEGENDS.nasa_forest_2020
  },
  {
    id: 'forest_type',
    nameKey: 'raster.layer.forestTypeName',
    descriptionKey: 'raster.layer.forestTypeDesc',
    source: 'Nepal FRTC',
    resolution: '30m',
    year: '2015',
    legend: [] // Will be populated dynamically based on forest_type_percentages
  },
  {
    id: 'landcover',
    nameKey: 'raster.layer.landcoverName',
    descriptionKey: 'raster.layer.landcoverDesc',
    source: 'ESA WorldCover',
    resolution: '10m',
    year: '2021',
    legend: STATIC_LEGENDS.landcover
  },
  {
    id: 'forest_loss',
    nameKey: 'raster.layer.forestLossName',
    descriptionKey: 'raster.layer.forestLossDesc',
    source: 'Hansen Global Forest Change',
    resolution: '30m',
    year: '2001-2024',
    legend: STATIC_LEGENDS.forest_loss
  },
  {
    id: 'forest_gain',
    nameKey: 'raster.layer.forestGainName',
    descriptionKey: 'raster.layer.forestGainDesc',
    source: 'Hansen Global Forest Change',
    resolution: '30m',
    year: '2000-2012',
    legend: STATIC_LEGENDS.forest_gain
  },
  {
    id: 'fire',
    nameKey: 'raster.layer.fireName',
    descriptionKey: 'raster.layer.fireDesc',
    source: 'Hansen Global Forest Change',
    resolution: '30m',
    year: '2001-2024',
    legend: STATIC_LEGENDS.fire
  },
  {
    id: 'soil_ph',
    nameKey: 'raster.layer.soilPhName',
    descriptionKey: 'raster.layer.soilPhDesc',
    source: 'SoilGrids 2.0 (ISRIC)',
    resolution: '250m',
    year: '2020',
    legend: STATIC_LEGENDS.soil_ph
  },
  {
    id: 'soil_texture',
    nameKey: 'raster.layer.soilTextureName',
    descriptionKey: 'raster.layer.soilTextureDesc',
    source: 'SoilGrids 2.0 (ISRIC)',
    resolution: '250m',
    year: '2020',
    legend: STATIC_LEGENDS.soil_texture
  },
  {
    id: 'soil_carbon',
    nameKey: 'raster.layer.soilCarbonName',
    descriptionKey: 'raster.layer.soilCarbonDesc',
    source: 'SoilGrids 2.0 (ISRIC)',
    resolution: '250m',
    year: '2020',
    legend: STATIC_LEGENDS.soil_carbon
  },
  {
    id: 'soil_fertility',
    nameKey: 'raster.layer.soilFertilityName',
    descriptionKey: 'raster.layer.soilFertilityDesc',
    source: 'SoilGrids 2.0 (ISRIC)',
    resolution: '250m',
    year: '2020',
    legend: STATIC_LEGENDS.soil_fertility
  },
  {
    id: 'soil_density',
    nameKey: 'raster.layer.soilDensityName',
    descriptionKey: 'raster.layer.soilDensityDesc',
    source: 'SoilGrids 2.0 (ISRIC)',
    resolution: '250m',
    year: '2020',
    legend: STATIC_LEGENDS.soil_density
  }
];

interface RasterLayerControlProps {
  calculationId: string | number;
  calculation: {
    result_data?: Record<string, any>;
  } | null;
}

export const RasterLayerControl: React.FC<RasterLayerControlProps> = ({ calculationId, calculation }) => {
  const t = useT();
  const tileToken = useTileToken(String(calculationId));
  const [activeLayers, setActiveLayers] = useState<Set<string>>(new Set());
  const [selectedLayer, setSelectedLayer] = useState<string | null>(null);
  const [isPanelMinimized, setIsPanelMinimized] = useState(false);
  const [layerOpacity, setLayerOpacity] = useState<number>(0.5); // Default 50% opacity

  // Generate dynamic legends based on calculation data
  const dynamicRasterLayers = useMemo(() => {
    const layers = [...RASTER_LAYERS];

    // Update DEM layer with dynamic elevation legend
    const demLayerIndex = layers.findIndex(l => l.id === 'dem');
    if (demLayerIndex !== -1 && calculation?.result_data) {
      const { elevation_min_m, elevation_max_m } = calculation.result_data;

      // Only use dynamic legend if we have valid elevation data
      if (elevation_min_m !== undefined && elevation_max_m !== undefined &&
          elevation_min_m > -32000 && elevation_max_m > -32000) {
        layers[demLayerIndex] = {
          ...layers[demLayerIndex],
          legend: generateDynamicElevationLegend(elevation_min_m, elevation_max_m)
        };
      } else {
        // Fallback to default static legend if no data available
        layers[demLayerIndex] = {
          ...layers[demLayerIndex],
          legend: [
            { color: '#8B4513', label: t('raster.legend.low'), range: '< 500m' },
            { color: '#FFA500', label: t('raster.legend.medium'), range: '500-1500m' },
            { color: '#7FFF00', label: t('raster.legend.high'), range: '1500-3000m' },
            { color: '#87CEEB', label: t('raster.legend.veryHigh'), range: '> 3000m' }
          ]
        };
      }
    }

    // Update Canopy layer with dynamic canopy legend (absolute ecological thresholds)
    const canopyLayerIndex = layers.findIndex(l => l.id === 'canopy');
    if (canopyLayerIndex !== -1 && calculation?.result_data) {
      const { canopy_min_m, canopy_max_m } = calculation.result_data;

      // Only use dynamic legend if we have valid canopy data
      if (canopy_min_m !== undefined && canopy_max_m !== undefined &&
          canopy_min_m >= 0 && canopy_max_m >= 0) {
        layers[canopyLayerIndex] = {
          ...layers[canopyLayerIndex],
          legend: generateDynamicCanopyLegend(canopy_min_m, canopy_max_m)
        };
      } else {
        // Fallback to default static legend if no data available
        layers[canopyLayerIndex] = {
          ...layers[canopyLayerIndex],
          legend: [
            { color: '#DC143C', label: t('raster.legend.sparseRegen'), range: '0-5m' },
            { color: '#FF8C00', label: t('raster.legend.youngForest'), range: '5-15m' },
            { color: '#90EE90', label: t('raster.legend.matureForest'), range: '15-30m' },
            { color: '#228B22', label: t('raster.legend.oldGrowth'), range: '>30m' }
          ]
        };
      }
    }

    // Update Temperature layer with dynamic temperature legend
    const temperatureLayerIndex = layers.findIndex(l => l.id === 'temperature');
    if (temperatureLayerIndex !== -1 && calculation?.result_data) {
      const { temperature_min_c, temperature_max_c } = calculation.result_data;

      // Only use dynamic legend if we have valid temperature data
      if (temperature_min_c !== undefined && temperature_max_c !== undefined &&
          temperature_min_c > -100 && temperature_max_c < 100) {
        layers[temperatureLayerIndex] = {
          ...layers[temperatureLayerIndex],
          legend: generateDynamicTemperatureLegend(temperature_min_c, temperature_max_c)
        };
      } else {
        // Fallback to default static legend if no data available
        layers[temperatureLayerIndex] = {
          ...layers[temperatureLayerIndex],
          legend: [
            { color: '#0000FF', label: t('raster.legend.veryCold'), range: '< 0°C' },
            { color: '#00BFFF', label: t('raster.legend.cold'), range: '0-10°C' },
            { color: '#90EE90', label: t('raster.legend.moderate'), range: '10-20°C' },
            { color: '#FFD700', label: t('raster.legend.warm'), range: '20-25°C' },
            { color: '#FF4500', label: t('raster.legend.hot'), range: '> 25°C' }
          ]
        };
      }
    }

    // Update Precipitation layer with dynamic precipitation legend
    const precipitationLayerIndex = layers.findIndex(l => l.id === 'precipitation');
    if (precipitationLayerIndex !== -1 && calculation?.result_data) {
      const { precipitation_min_mm, precipitation_max_mm } = calculation.result_data;

      // Only use dynamic legend if we have valid precipitation data
      if (precipitation_min_mm !== undefined && precipitation_max_mm !== undefined &&
          precipitation_min_mm >= 0 && precipitation_max_mm >= 0) {
        layers[precipitationLayerIndex] = {
          ...layers[precipitationLayerIndex],
          legend: generateDynamicPrecipitationLegend(precipitation_min_mm, precipitation_max_mm)
        };
      } else {
        // Fallback to default static legend if no data available
        layers[precipitationLayerIndex] = {
          ...layers[precipitationLayerIndex],
          legend: [
            { color: '#8B4513', label: t('raster.legend.veryDry'), range: '< 500mm' },
            { color: '#D2B48C', label: t('raster.legend.dry'), range: '500-1000mm' },
            { color: '#90EE90', label: t('raster.legend.moderate'), range: '1000-2000mm' },
            { color: '#4169E1', label: t('raster.legend.wet'), range: '2000-3000mm' },
            { color: '#0000CD', label: t('raster.legend.veryWet'), range: '> 3000mm' }
          ]
        };
      }
    }

    // Update Biomass layer with dynamic biomass legend
    const biomassLayerIndex = layers.findIndex(l => l.id === 'biomass');
    if (biomassLayerIndex !== -1 && calculation?.result_data) {
      const { agb_min_mg_ha, agb_max_mg_ha } = calculation.result_data;

      // Only use dynamic legend if we have valid biomass data
      if (agb_min_mg_ha !== undefined && agb_max_mg_ha !== undefined &&
          agb_min_mg_ha >= 0 && agb_max_mg_ha >= 0) {
        layers[biomassLayerIndex] = {
          ...layers[biomassLayerIndex],
          legend: generateDynamicBiomassLegend(agb_min_mg_ha, agb_max_mg_ha)
        };
      } else {
        // Fallback to default static legend if no data available
        layers[biomassLayerIndex] = {
          ...layers[biomassLayerIndex],
          legend: [
            { color: '#DC143C', label: t('raster.legend.veryLow'), range: '0-50 Mg/ha' },
            { color: '#FFD700', label: t('raster.legend.low'), range: '50-100 Mg/ha' },
            { color: '#90EE90', label: t('raster.legend.medium'), range: '100-200 Mg/ha' },
            { color: '#228B22', label: t('raster.legend.high'), range: '200-300 Mg/ha' },
            { color: '#1E90FF', label: t('raster.legend.veryHigh'), range: '>300 Mg/ha' }
          ]
        };
      }
    }

    // Update Slope layer with dynamic slope legend
    const slopeLayerIndex = layers.findIndex(l => l.id === 'slope');
    if (slopeLayerIndex !== -1 && calculation?.result_data) {
      const { slope_min_code, slope_max_code } = calculation.result_data;

      // Only use dynamic legend if we have valid slope code data
      if (slope_min_code !== undefined && slope_max_code !== undefined &&
          slope_min_code >= 1 && slope_max_code <= 4) {
        layers[slopeLayerIndex] = {
          ...layers[slopeLayerIndex],
          legend: generateDynamicSlopeLegend(slope_min_code, slope_max_code)
        };
      } else {
        // Fallback to default static legend if no data available
        layers[slopeLayerIndex] = {
          ...layers[slopeLayerIndex],
          legend: [
            { color: '#2ECC71', label: t('raster.legend.gentle'), range: '<19°' },
            { color: '#F1C40F', label: t('raster.legend.moderate'), range: '19-31°' },
            { color: '#E67E22', label: t('raster.legend.steep'), range: '31-45°' },
            { color: '#E74C3C', label: t('raster.legend.verySteep'), range: '>45°' }
          ]
        };
      }
    }

    // Update Min Temperature (Coldest Month) layer with dynamic legend
    const minTempColdestLayerIndex = layers.findIndex(l => l.id === 'min_temp_coldest');
    if (minTempColdestLayerIndex !== -1 && calculation?.result_data) {
      const { min_temp_coldest_min_c, min_temp_coldest_max_c } = calculation.result_data;

      // Only use dynamic legend if we have valid min temp coldest data
      if (min_temp_coldest_min_c !== undefined && min_temp_coldest_max_c !== undefined &&
          min_temp_coldest_min_c > -100 && min_temp_coldest_max_c < 100) {
        layers[minTempColdestLayerIndex] = {
          ...layers[minTempColdestLayerIndex],
          legend: generateDynamicMinTempColdestLegend(min_temp_coldest_min_c, min_temp_coldest_max_c)
        };
      } else {
        // Fallback to default static legend if no data available
        layers[minTempColdestLayerIndex] = {
          ...layers[minTempColdestLayerIndex],
          legend: [
            { color: '#0000CD', label: t('raster.legend.extremeCold'), range: '< -10°C' },
            { color: '#4169E1', label: t('raster.legend.veryCold'), range: '-10 to 0°C' },
            { color: '#87CEEB', label: t('raster.legend.cold'), range: '0 to 5°C' },
            { color: '#90EE90', label: t('raster.legend.cool'), range: '5 to 10°C' },
            { color: '#FFD700', label: t('raster.legend.mild'), range: '10 to 15°C' },
            { color: '#FF8C00', label: t('raster.legend.warm'), range: '> 15°C' }
          ]
        };
      }
    }

    // Update Land Cover layer with dynamic legend - only show classes present in data
    const landcoverLayerIndex = layers.findIndex(l => l.id === 'landcover');
    if (landcoverLayerIndex !== -1 && calculation?.result_data) {
      const { landcover_percentages } = calculation.result_data;

      if (landcover_percentages && Object.keys(landcover_percentages).length > 0) {
        layers[landcoverLayerIndex] = {
          ...layers[landcoverLayerIndex],
          legend: generateDynamicLandcoverLegend(landcover_percentages)
        };
      }
    }

    // Update NASA Forest 2020 layer with dynamic legend - only show classes present
    const nasaForestLayerIndex = layers.findIndex(l => l.id === 'nasa_forest_2020');
    if (nasaForestLayerIndex !== -1 && calculation?.result_data) {
      // Check both whole forest and block-level percentages
      const nasaPercentages = calculation.result_data.whole_nasa_forest_2020_percentages ||
                              calculation.result_data.nasa_forest_2020_percentages;

      if (nasaPercentages && Object.keys(nasaPercentages).length > 0) {
        layers[nasaForestLayerIndex] = {
          ...layers[nasaForestLayerIndex],
          legend: generateDynamicNasaForestLegend(nasaPercentages)
        };
      }
    }

    // Update Aspect layer with dynamic legend - only show directions present
    const aspectLayerIndex = layers.findIndex(l => l.id === 'aspect');
    if (aspectLayerIndex !== -1 && calculation?.result_data) {
      const { aspect_percentages } = calculation.result_data;

      if (aspect_percentages && Object.keys(aspect_percentages).length > 0) {
        layers[aspectLayerIndex] = {
          ...layers[aspectLayerIndex],
          legend: generateDynamicAspectLegend(aspect_percentages)
        };
      }
    }

    // Update Forest Health layer with dynamic legend - only show health classes present
    const forestHealthLayerIndex = layers.findIndex(l => l.id === 'forest_health');
    if (forestHealthLayerIndex !== -1 && calculation?.result_data) {
      const { forest_health_percentages } = calculation.result_data;

      if (forest_health_percentages && Object.keys(forest_health_percentages).length > 0) {
        layers[forestHealthLayerIndex] = {
          ...layers[forestHealthLayerIndex],
          legend: generateDynamicForestHealthLegend(forest_health_percentages)
        };
      }
    }

    // Update Forest Type layer with dynamic legend - only show types present in data
    const forestTypeLayerIndex = layers.findIndex(l => l.id === 'forest_type');
    if (forestTypeLayerIndex !== -1 && calculation?.result_data) {
      const { forest_type_percentages } = calculation.result_data;

      if (forest_type_percentages && Object.keys(forest_type_percentages).length > 0) {
        layers[forestTypeLayerIndex] = {
          ...layers[forestTypeLayerIndex],
          legend: generateDynamicForestTypeLegend(forest_type_percentages)
        };
      }
    }

    // Update Fire Loss layer with dynamic legend - show fire activity by time period
    const fireLayerIndex = layers.findIndex(l => l.id === 'fire');
    if (fireLayerIndex !== -1 && calculation?.result_data) {
      const { fire_loss_by_year } = calculation.result_data;

      if (fire_loss_by_year && Object.keys(fire_loss_by_year).length > 0) {
        layers[fireLayerIndex] = {
          ...layers[fireLayerIndex],
          legend: generateDynamicFireLossLegend(fire_loss_by_year)
        };
      }
    }

    // Soil layers: Use static legends showing all categories
    // (Map tiles show actual raster data with full range of values,
    //  so legends should show all possible categories, not just the dominant one)

    return layers;
  }, [calculation]);

  const toggleLayer = (layerId: string) => {
    setActiveLayers(prev => {
      const newSet = new Set(prev);
      if (newSet.has(layerId)) {
        newSet.delete(layerId);
      } else {
        newSet.add(layerId);
      }
      return newSet;
    });
  };

  const showLegend = (layerId: string) => {
    setSelectedLayer(layerId);
  };

  const currentLegend = selectedLayer
    ? dynamicRasterLayers.find(l => l.id === selectedLayer)?.legend || []
    : [];

  const currentLayerName = selectedLayer
    ? (() => {
        const found = dynamicRasterLayers.find(l => l.id === selectedLayer);
        return found ? t(found.nameKey) : '';
      })()
    : '';

  return (
    <>
      {/* Compact Layer Toggle Panel */}
      <div style={{
        position: 'absolute',
        top: '80px',
        right: '10px',
        backgroundColor: 'white',
        padding: isPanelMinimized ? '8px' : '12px',
        borderRadius: '8px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        zIndex: 1000,
        minWidth: isPanelMinimized ? 'auto' : '200px',
        maxHeight: '600px',
        overflowY: 'auto'
      }}>
        {/* Header */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: isPanelMinimized ? '0' : '8px'
        }}>
          <h3 style={{
            margin: 0,
            fontSize: '14px',
            fontWeight: 'bold',
            display: isPanelMinimized ? 'none' : 'block'
          }}>
            {t('raster.title')}
          </h3>
          <button
            onClick={() => setIsPanelMinimized(!isPanelMinimized)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: '16px',
              padding: '2px 4px'
            }}
            title={isPanelMinimized ? t('raster.expand') : t('raster.minimize')}
          >
            {isPanelMinimized ? '📍' : '─'}
          </button>
        </div>

        {/* Layer checkboxes */}
        {!isPanelMinimized && (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {dynamicRasterLayers.map(layer => (
                <div key={layer.id} style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '4px 6px',
                  borderRadius: '4px',
                  backgroundColor: activeLayers.has(layer.id) ? '#e8f5e9' : 'transparent',
                  border: activeLayers.has(layer.id) ? '1px solid #4caf50' : '1px solid transparent'
                }}>
                  <label style={{
                    display: 'flex',
                    alignItems: 'center',
                    cursor: 'pointer',
                    flex: 1,
                    fontSize: '13px'
                  }}>
                    <input
                      type="checkbox"
                      checked={activeLayers.has(layer.id)}
                      onChange={() => toggleLayer(layer.id)}
                      style={{ marginRight: '6px', cursor: 'pointer', width: '14px', height: '14px' }}
                    />
                    <span>{t(layer.nameKey)}</span>
                  </label>
                  <button
                    onClick={() => showLegend(layer.id)}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '14px',
                      padding: '2px 4px',
                      opacity: 0.6
                    }}
                    title="Show legend"
                  >
                    🗺️
                  </button>
                </div>
              ))}
            </div>

            {/* Opacity Slider - Only show when at least one layer is active */}
            {activeLayers.size > 0 && (
              <div style={{
                marginTop: '12px',
                padding: '8px',
                backgroundColor: '#f0f0f0',
                borderRadius: '6px',
                border: '1px solid #ddd'
              }}>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: '6px'
                }}>
                  <label style={{
                    fontSize: '12px',
                    fontWeight: '600',
                    color: '#333'
                  }}>{t('raster.opacity')}</label>
                  <span style={{
                    fontSize: '12px',
                    fontWeight: 'bold',
                    color: '#4caf50'
                  }}>
                    {Math.round(layerOpacity * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={layerOpacity * 100}
                  onChange={(e) => setLayerOpacity(Number(e.target.value) / 100)}
                  style={{
                    width: '100%',
                    cursor: 'pointer'
                  }}
                  title={t('raster.opacityValue', { pct: formatNumber(Math.round(layerOpacity * 100)) })}
                />
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '10px',
                  color: '#666',
                  marginTop: '2px'
                }}>
                  <span>{t('raster.transparent')}</span>
                  <span>{t('raster.opaque')}</span>
                </div>
              </div>
            )}
          </>
        )}

        {/* Active layer count when minimized */}
        {isPanelMinimized && activeLayers.size > 0 && (
          <div style={{
            fontSize: '11px',
            color: '#4caf50',
            fontWeight: 'bold',
            textAlign: 'center',
            marginTop: '4px'
          }}>
            {activeLayers.size}
          </div>
        )}
      </div>

      {/* Separate Floating Legend Panel */}
      {selectedLayer && (
        <div style={{
          position: 'absolute',
          bottom: '20px',
          left: '20px',
          backgroundColor: 'white',
          padding: '12px',
          borderRadius: '8px',
          boxShadow: '0 2px 10px rgba(0,0,0,0.2)',
          zIndex: 1000,
          maxWidth: '280px',
          border: '2px solid #4caf50'
        }}>
          {/* Legend Header */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '10px',
            borderBottom: '2px solid #4caf50',
            paddingBottom: '6px'
          }}>
            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 'bold', color: '#333' }}>
              {currentLayerName}
            </h4>
            <button
              onClick={() => setSelectedLayer(null)}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: '18px',
                padding: '0 4px',
                color: '#666'
              }}
              title="Close legend"
            >
              ✕
            </button>
          </div>

          {/* Legend Items */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {currentLegend.map((item, idx) => (
              <div key={idx} style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}>
                <div style={{
                  width: '20px',
                  height: '20px',
                  backgroundColor: item.color,
                  border: '1px solid #999',
                  borderRadius: '3px',
                  opacity: 0.6,
                  flexShrink: 0
                }} />
                <span style={{ fontSize: '12px', flex: 1 }}>
                  <strong>{item.label}</strong>
                  {item.range && (
                    <span style={{ color: '#666', marginLeft: '4px', fontSize: '11px' }}>
                      {item.range}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>

          {/* Data Source Attribution */}
          {(() => {
            const currentLayerData = dynamicRasterLayers.find(l => l.id === selectedLayer);
            if (currentLayerData && (currentLayerData.source || currentLayerData.resolution || currentLayerData.year)) {
              return (
                <div style={{
                  marginTop: '12px',
                  paddingTop: '8px',
                  borderTop: '1px solid #ddd',
                  fontSize: '10px',
                  color: '#666'
                }}>
                  {currentLayerData.source && (
                    <div><strong>{t('raster.source')}</strong> {currentLayerData.source}</div>
                  )}
                  {currentLayerData.resolution && (
                    <div><strong>{t('raster.resolution')}</strong> {currentLayerData.resolution}</div>
                  )}
                  {currentLayerData.year && (
                    <div><strong>{t('raster.year')}</strong> {currentLayerData.year}</div>
                  )}
                </div>
              );
            }
            return null;
          })()}
        </div>
      )}

      {/* Render active tile layers */}
      {tileToken && Array.from(activeLayers).map(layerId => (
        <TileLayer
          key={layerId}
          url={withTileToken(`${API_BASE_URL}/api/calculations/${calculationId}/tiles/${layerId}/{z}/{x}/{y}.png?alpha=${Math.round(layerOpacity * 255)}&cb=${Date.now()}`, tileToken)!}
          opacity={layerOpacity}  // User-controlled opacity
          zIndex={500}   // Above base map, below markers
          maxZoom={18}
          minZoom={10}
        />
      ))}
    </>
  );
};
