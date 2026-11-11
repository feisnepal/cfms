/** Hook that fetches and cascades Nepal's administrative locations (province → district → local body) for the operational plan metadata form. */
import { useState, useCallback } from 'react';
import { operationalPlanApi } from '../../../services/api';

export interface LocationState {
  province: string | undefined;
  district: string | undefined;
  division: string | undefined;
  subDivision: string | undefined;
  municipality: string | undefined;
  ward: string | undefined;
}

export interface AdminLocationOptions {
  provinces: string[];
  districts: string[];
  divisions: string[];
  subDivisions: string[];
  municipalities: { name: string; type: string }[];
  wards: string[];
  physiographyZone: string;
  protectedAreaStatus: string;
}

export function useAdminLocation() {
  const [options, setOptions] = useState<AdminLocationOptions>({
    provinces: [],
    districts: [],
    divisions: [],
    subDivisions: [],
    municipalities: [],
    wards: [],
    physiographyZone: '',
    protectedAreaStatus: '',
  });
  const [loading, setLoading] = useState(false);

  const loadProvinces = useCallback(async () => {
    try {
      const provinces = await operationalPlanApi.getProvinces();
      setOptions(prev => ({ ...prev, provinces }));
    } catch { /* ignore */ }
  }, []);

  const loadDistricts = useCallback(async (province?: string) => {
    if (!province) { setOptions(prev => ({ ...prev, districts: [], municipalities: [], wards: [] })); return; }
    try {
      const districts = await operationalPlanApi.getDistricts(province);
      setOptions(prev => ({ ...prev, districts, municipalities: [], wards: [] }));
    } catch { /* ignore */ }
  }, []);

  const loadDivisions = useCallback(async (province?: string) => {
    if (!province) { setOptions(prev => ({ ...prev, divisions: [], subDivisions: [] })); return; }
    try {
      const divisions = await operationalPlanApi.getDivisions(province);
      setOptions(prev => ({ ...prev, divisions, subDivisions: [] }));
    } catch { /* ignore */ }
  }, []);

  const loadSubDivisions = useCallback(async (province?: string, division?: string) => {
    if (!province || !division) { setOptions(prev => ({ ...prev, subDivisions: [] })); return; }
    try {
      const subDivisions = await operationalPlanApi.getSubDivisions(province, division);
      setOptions(prev => ({ ...prev, subDivisions }));
    } catch { /* ignore */ }
  }, []);

  const loadMunicipalitiesByDistrict = useCallback(async (province?: string, district?: string) => {
    if (!province || !district) { setOptions(prev => ({ ...prev, municipalities: [], wards: [] })); return; }
    try {
      const municipalities = await operationalPlanApi.getMunicipalitiesByDistrict(province, district);
      setOptions(prev => ({ ...prev, municipalities, wards: [] }));
    } catch { /* ignore */ }
  }, []);

  const loadWardsByDistrict = useCallback(async (province?: string, district?: string, municipality?: string) => {
    if (!province || !district || !municipality) { setOptions(prev => ({ ...prev, wards: [] })); return; }
    try {
      const wards = await operationalPlanApi.getWardsByDistrict(province, district, municipality);
      setOptions(prev => ({ ...prev, wards }));
    } catch { /* ignore */ }
  }, []);

  const loadPhysiographyByDistrict = useCallback(async (province?: string, district?: string, municipality?: string) => {
    if (!province || !district || !municipality) return;
    try {
      const result = await operationalPlanApi.getPhysiographyByDistrict(province, district, municipality);
      setOptions(prev => ({ ...prev, physiographyZone: result.physiography_zone, protectedAreaStatus: result.protected_area_status }));
    } catch { /* ignore */ }
  }, []);

  const cascadeOnProvinceChange = useCallback(async (province: string | undefined) => {
    setLoading(true);
    setOptions(prev => ({
      ...prev, province,
      districts: [], divisions: [], subDivisions: [],
      municipalities: [], wards: [],
      physiographyZone: '', protectedAreaStatus: '',
    }));
    if (province) {
      await Promise.all([
        loadDistricts(province),
        loadDivisions(province),
      ]);
    }
    setLoading(false);
  }, [loadDistricts, loadDivisions]);

  const cascadeOnDistrictChange = useCallback(async (province: string | undefined, district: string | undefined) => {
    setLoading(true);
    setOptions(prev => ({
      ...prev, district,
      municipalities: [], wards: [],
      physiographyZone: '', protectedAreaStatus: '',
    }));
    if (province && district) {
      await loadMunicipalitiesByDistrict(province, district);
    }
    setLoading(false);
  }, [loadMunicipalitiesByDistrict]);

  const cascadeOnDivisionChange = useCallback(async (province: string | undefined, division: string | undefined) => {
    setLoading(true);
    setOptions(prev => ({
      ...prev, division, subDivisions: [],
    }));
    if (province && division) {
      await loadSubDivisions(province, division);
    }
    setLoading(false);
  }, [loadSubDivisions]);

  const cascadeOnMunicipalityChange = useCallback(async (
    province: string | undefined,
    district: string | undefined,
    municipality: string | undefined,
    fetchPhysiography: boolean = true,
  ) => {
    setLoading(true);
    setOptions(prev => ({ ...prev, municipality, wards: [] }));
    if (province && district && municipality) {
      await loadWardsByDistrict(province, district, municipality);
      if (fetchPhysiography) {
        await loadPhysiographyByDistrict(province, district, municipality);
      }
    }
    setLoading(false);
  }, [loadWardsByDistrict, loadPhysiographyByDistrict]);

  return {
    options,
    loading,
    loadProvinces,
    cascadeOnProvinceChange,
    cascadeOnDistrictChange,
    cascadeOnDivisionChange,
    cascadeOnMunicipalityChange,
    setOptions,
  };
}
