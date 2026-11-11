/** Metadata editor form for the operational plan — manages district, local body, dates, and plan identifiers. */
import React, { useState, useEffect, useCallback } from 'react';
import { Form, Input, Select, Button, message, Spin, Collapse, Divider, Alert, ConfigProvider } from 'antd';
import { operationalPlanApi } from '../../services/api';
import { useAdminLocation } from './hooks/useAdminLocation';
import { NepaliDatePicker } from './NepaliDatePicker';
import HelpTooltip from '../HelpTooltip';
import { useTranslation } from 'react-i18next';
import { LocaleInputNumber } from '../LocaleInputNumber';

interface MetadataFormProps {
  planId: string;
  visible: boolean;
  onClose: () => void;
}

/** A field that belongs to the forest: read-only here, edited once on the Forest Metadata tab. */
const FromForest: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ConfigProvider componentDisabled>{children}</ConfigProvider>
);

const MetadataForm: React.FC<MetadataFormProps> = ({ planId, visible, onClose }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const forestLoc = useAdminLocation();
  const ugLoc = useAdminLocation();

  const [ugPrepopulated, setUgPrepopulated] = useState(false);
  // Facts that belong to the forest (Forest Metadata tab): shown here, not editable, never stored in the plan.
  const [sharedKeys, setSharedKeys] = useState<string[]>([]);
  const [calcId, setCalcId] = useState<string>('');

  useEffect(() => {
    if (visible && planId) {
      loadFormData();
    }
  }, [visible, planId]);

  const copyForestToUg = useCallback(() => {
    const fv = form.getFieldsValue();
    const ugFields: Record<string, any> = {};
    if (fv.province) ugFields.ug_province = fv.province;
    if (fv.district) ugFields.ug_district = fv.district;
    if (fv.division) ugFields.ug_division = fv.division;
    if (fv.sub_division) ugFields.ug_sub_division = fv.sub_division;
    if (fv.municipality) ugFields.ug_municipality = fv.municipality;
    if (fv.forest_municipality_type) ugFields.ug_municipality_type = fv.forest_municipality_type;
    if (fv.ward) ugFields.ug_ward = fv.ward;
    form.setFieldsValue(ugFields);
    setUgPrepopulated(true);
  }, [form]);

  const loadFormData = async () => {
    setLoading(true);
    try {
      const data = await operationalPlanApi.getMetadataForm(planId);
      setSharedKeys(data.shared_keys || []);
      setCalcId(data.calculation_id || '');
      const userInputs = data.user_inputs || {};
      const formValues = { ...userInputs };
      formValues.district = formValues.forest_district;
      formValues.municipality = formValues.forest_municipality;
      formValues.ward = formValues.forest_ward;
      form.setFieldsValue({
        ...formValues,
        ...data.system_defaults,
        ...data.hybrid_overrides,
      });

      if (data.admin_locations?.provinces) {
        forestLoc.setOptions(prev => ({ ...prev, provinces: data.admin_locations.provinces }));
        ugLoc.setOptions(prev => ({ ...prev, provinces: data.admin_locations.provinces }));
      }

      const ui = userInputs;
      const DATE_FIELDS = ['registration_date', 'constitution_approved_year', 'cf_handover_date', 'op_general_assembly_date', 'kabuliyatnama_date'];
      for (const f of DATE_FIELDS) {
        if (ui[f]) form.setFieldValue(f, ui[f].replace(/-/g, '/'));
      }

      // Forest location cascading state
      if (ui.province) {
        forestLoc.setOptions(prev => ({ ...prev, province: ui.province }));
        const [districts, divisions] = await Promise.all([
          operationalPlanApi.getDistricts(ui.province),
          operationalPlanApi.getDivisions(ui.province),
        ]);
        forestLoc.setOptions(prev => ({ ...prev, districts, divisions }));
      }
      if (ui.province && ui.forest_district) {
        const muns = await operationalPlanApi.getMunicipalitiesByDistrict(ui.province, ui.forest_district);
        forestLoc.setOptions(prev => ({ ...prev, municipalities: muns }));
      }
      if (ui.province && ui.forest_district && ui.forest_municipality) {
        const wards = await operationalPlanApi.getWardsByDistrict(ui.province, ui.forest_district, ui.forest_municipality);
        forestLoc.setOptions(prev => ({ ...prev, wards }));
      }
      if (ui.province && ui.division) {
        const subDivs = await operationalPlanApi.getSubDivisions(ui.province, ui.division);
        forestLoc.setOptions(prev => ({ ...prev, subDivisions: subDivs }));
      }

      // UG location cascading state (auto-copy forest to UG on first load)
      if (!ui.ug_prepopulated && !ui.ug_province && ui.province) {
        copyForestToUg();
        ugLoc.setOptions(prev => ({ ...prev, province: ui.province }));
        if (ui.forest_district) {
          const ugMuns = await operationalPlanApi.getMunicipalitiesByDistrict(ui.province, ui.forest_district);
          ugLoc.setOptions(prev => ({ ...prev, districts: [ui.forest_district], municipalities: ugMuns }));
        } else {
          const ugDists = await operationalPlanApi.getDistricts(ui.province);
          ugLoc.setOptions(prev => ({ ...prev, districts: ugDists }));
        }
        if (ui.division) {
          const ugSubDivs = await operationalPlanApi.getSubDivisions(ui.province, ui.division);
          ugLoc.setOptions(prev => ({ ...prev, divisions: [ui.division], subDivisions: ugSubDivs }));
        }
        if (ui.forest_district && ui.forest_municipality) {
          const ugWards = await operationalPlanApi.getWardsByDistrict(ui.province, ui.forest_district, ui.forest_municipality);
          ugLoc.setOptions(prev => ({ ...prev, wards: ugWards }));
        }
      }

      if (ui.ug_province) {
        ugLoc.setOptions(prev => ({ ...prev, province: ui.ug_province }));
        Promise.all([
          operationalPlanApi.getDistricts(ui.ug_province).then(d => ugLoc.setOptions(p => ({ ...p, districts: d }))),
          operationalPlanApi.getDivisions(ui.ug_province).then(d => ugLoc.setOptions(p => ({ ...p, divisions: d }))),
        ]);
      }
      if (ui.ug_province && ui.ug_district) {
        const ugMuns = await operationalPlanApi.getMunicipalitiesByDistrict(ui.ug_province, ui.ug_district);
        ugLoc.setOptions(prev => ({ ...prev, municipalities: ugMuns }));
      }
      if (ui.ug_province && ui.ug_district && ui.ug_municipality) {
        const ugWards = await operationalPlanApi.getWardsByDistrict(ui.ug_province, ui.ug_district, ui.ug_municipality);
        ugLoc.setOptions(prev => ({ ...prev, wards: ugWards }));
      }
      if (ui.ug_province && ui.ug_division) {
        const ugSubDivs = await operationalPlanApi.getSubDivisions(ui.ug_province, ui.ug_division);
        ugLoc.setOptions(prev => ({ ...prev, subDivisions: ugSubDivs }));
      }

      const alreadyPrepopulated = !!ui.ug_prepopulated;
      setUgPrepopulated(alreadyPrepopulated);
    } catch {
      message.error(t('operationalPlan.meta.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const autoCopyToUg = async () => {
    const ugProv = form.getFieldValue('ug_province');
    const forestProv = form.getFieldValue('province');
    const forestDist = form.getFieldValue('district');
    const forestMun = form.getFieldValue('municipality');
    const forestWard = form.getFieldValue('ward');

    if (forestProv) {
      if (!ugProv) {
        form.setFieldValue('ug_province', forestProv);
        await ugLoc.cascadeOnProvinceChange(forestProv);
      }
      if (forestDist) {
        form.setFieldValue('ug_district', forestDist);
        const p = forestProv && !ugProv ? forestProv : ugProv;
        await ugLoc.cascadeOnDistrictChange(p, forestDist);
      }
      if (forestMun && forestDist) {
        form.setFieldValue('ug_municipality', forestMun);
        const p = forestProv && !ugProv ? forestProv : ugProv;
        await ugLoc.cascadeOnMunicipalityChange(p, forestDist, forestMun, false);
      }
      if (forestWard) {
        form.setFieldValue('ug_ward', forestWard);
      }
    }
    setUgPrepopulated(true);
  };

  const handleProvinceChange = async (value: string | undefined) => {
    form.setFieldsValue({
      district: undefined, division: undefined,
      sub_division: undefined, municipality: undefined, ward: undefined,
    });
    await forestLoc.cascadeOnProvinceChange(value);
    await autoCopyToUg();
  };

  const handleDistrictChange = async (value: string | undefined) => {
    const province = form.getFieldValue('province');
    form.setFieldsValue({ municipality: undefined, ward: undefined });
    await forestLoc.cascadeOnDistrictChange(province, value);
    await autoCopyToUg();
  };

  const handleDivisionChange = async (value: string | undefined) => {
    const province = form.getFieldValue('province');
    form.setFieldsValue({ sub_division: undefined });
    await forestLoc.cascadeOnDivisionChange(province, value);
  };

  const handleMunicipalityChange = async (value: string | undefined) => {
    const province = form.getFieldValue('province');
    const district = form.getFieldValue('district');
    form.setFieldsValue({ ward: undefined });
    await forestLoc.cascadeOnMunicipalityChange(province, district, value, true);

    if (value) {
      const munData = forestLoc.options.municipalities.find(m => m.name === value);
      if (munData) {
        form.setFieldValue('forest_municipality_type', munData.type);
      }
    }
    await autoCopyToUg();
  };

  const handleUgProvinceChange = async (value: string | undefined) => {
    form.setFieldsValue({
      ug_district: undefined, ug_division: undefined,
      ug_sub_division: undefined, ug_municipality: undefined, ug_ward: undefined,
    });
    await ugLoc.cascadeOnProvinceChange(value);
  };

  const handleUgDistrictChange = async (value: string | undefined) => {
    const province = form.getFieldValue('ug_province');
    form.setFieldsValue({ ug_municipality: undefined, ug_ward: undefined });
    await ugLoc.cascadeOnDistrictChange(province, value);
  };

  const handleUgDivisionChange = async (value: string | undefined) => {
    const province = form.getFieldValue('ug_province');
    form.setFieldsValue({ ug_sub_division: undefined });
    await ugLoc.cascadeOnDivisionChange(province, value);
  };

  const handleUgMunicipalityChange = async (value: string | undefined) => {
    const province = form.getFieldValue('ug_province');
    const district = form.getFieldValue('ug_district');
    form.setFieldsValue({ ug_ward: undefined });
    await ugLoc.cascadeOnMunicipalityChange(province, district, value, false);

    if (value) {
      const munData = ugLoc.options.municipalities.find(m => m.name === value);
      if (munData) {
        form.setFieldValue('ug_municipality_type', munData.type);
      }
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      const userInputKeys = [
        'cf_registration_number', 'op_preparation_year', 'sn_number', 'province_guideline_year',
        'province', 'forest_district', 'division', 'sub_division', 'sub_division_chief',
        'forest_management_section_chief', 'division_forest_officer',
        'forest_municipality', 'forest_municipality_type', 'forest_ward',
        'cf_sn_number', 'constitution_approved_year', 'user_group_reg_no',
        'op_start_fy', 'op_end_fy',
        'cf_boundary_east', 'cf_boundary_south', 'cf_boundary_west', 'cf_boundary_north',
        'physiography_zone', 'protected_area_status', 'cf_handover_date',
        'ug_prepopulated', 'ug_province', 'ug_district', 'ug_division', 'ug_sub_division',
        'ug_municipality', 'ug_municipality_type', 'ug_ward', 'ug_settlement',
        'ug_boundary_east', 'ug_boundary_south', 'ug_boundary_west', 'ug_boundary_north',
        'technical_assistance_org', 'op_general_assembly_date',
        'forest_type', 'forest_abundance', 'forest_avg_age', 'main_non_timber_fp',
        'avg_crown_density_pct',
        'cf_first_renewal_date', 'cf_history_note', 'silviculture_system',
        'rotation_years', 'regeneration_period_years', 'mother_tree_spacing_m',
        'plan_language',
      ];
      const hybridKeys = [
        'altitude_min_m', 'altitude_max_m', 'altitude_mean_m',
        'dominant_slope', 'dominant_aspect', 'dominant_soil',
        'crown_density_pct', 'trees_per_hectare',
        'growing_stock_m3_per_ha', 'biomass_t_per_ha', 'carbon_stock_tc_per_ha',
      ];

      const userInputs: Record<string, any> = {};
      const hybridOverrides: Record<string, any> = {};

      if (!sharedKeys.includes('forest_district')) userInputs.forest_district = values.district;
      if (!sharedKeys.includes('forest_municipality')) userInputs.forest_municipality = values.municipality;
      if (!sharedKeys.includes('forest_ward')) userInputs.forest_ward = values.ward;

      for (const key of userInputKeys) {
        if (sharedKeys.includes(key)) continue;
        if (values[key] !== undefined && values[key] !== null && values[key] !== '') {
          let val = values[key];
          if (['constitution_approved_year', 'cf_handover_date', 'op_general_assembly_date', 'kabuliyatnama_date'].includes(key) && typeof val === 'string') {
            val = val.replace(/-/g, '/');
          }
          userInputs[key] = val;
        }
      }
      for (const key of hybridKeys) {
        if (values[key] !== undefined && values[key] !== null && values[key] !== '') {
          hybridOverrides[key] = values[key];
        }
      }

      userInputs.ug_prepopulated = true;

      await operationalPlanApi.updateMetadataForm(planId, {
        user_inputs: userInputs,
        hybrid_overrides: hybridOverrides,
      });

      message.success(t('operationalPlan.meta.msgSaved'));
      onClose();
    } catch (err: any) {
      if (err.errorFields) return;
      if (err.response?.data?.detail) {
        const detail = err.response.data.detail;
        const msg = Array.isArray(detail)
          ? detail.map((d: any) => typeof d === 'string' ? d : d.msg || JSON.stringify(d)).join(', ')
          : typeof detail === 'string' ? detail : JSON.stringify(detail);
        message.error(msg);
      } else {
        message.error(t('operationalPlan.meta.saveFailed'));
      }
    } finally {
      setSaving(false);
    }
  };

  if (!visible) return null;

  const selectStyle = { width: '100%' };

  // Cascading civil admin fields: Province → District → Municipality → Ward
const cascadingSelects = (
    prefix: string,
    loc: typeof forestLoc,
    onProvinceChange: any,
    onDistrictChange: any,
    onMunicipalityChange: any,
  ) => (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <Form.Item label={t('operationalPlan.meta.province')} name={`${prefix}province`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Select showSearch allowClear placeholder={t('operationalPlan.meta.phProvince')} style={selectStyle} options={loc.options.provinces.map(p => ({ value: p, label: p }))} onChange={onProvinceChange} />
        </div>
      </Form.Item>
      <Form.Item label={t('operationalPlan.meta.district')} name={`${prefix}district`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Select showSearch allowClear placeholder={t('operationalPlan.meta.phDistrict')} style={selectStyle} options={loc.options.districts.map(d => ({ value: d, label: d }))} onChange={onDistrictChange} />
        </div>
      </Form.Item>
      <Form.Item label={t('operationalPlan.meta.municipality')} name={`${prefix}municipality`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Select showSearch allowClear placeholder={t('operationalPlan.meta.phMunicipality')} style={selectStyle} options={loc.options.municipalities.map(m => ({ value: m.name, label: m.name }))} onChange={onMunicipalityChange} />
        </div>
      </Form.Item>
      <Form.Item label={t('operationalPlan.meta.ward')} name={`${prefix}ward`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Select showSearch allowClear placeholder={t('operationalPlan.meta.phWard')} style={selectStyle} options={loc.options.wards.map(w => ({ value: w, label: w }))} />
        </div>
      </Form.Item>
    </div>
  );

  // Non-cascading forest dept admin fields
  const forestDeptSelects = (prefix: string, loc: typeof forestLoc, onDivisionChange?: any) => (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <Form.Item label={t('operationalPlan.meta.division')} name={`${prefix}division`}>
        <Select showSearch allowClear placeholder={t('operationalPlan.meta.phDivision')} style={selectStyle} options={loc.options.divisions.map(d => ({ value: d, label: d }))} onChange={onDivisionChange} />
      </Form.Item>
      <Form.Item label={t('operationalPlan.meta.subDivision')} name={`${prefix}sub_division`}>
        <Select showSearch allowClear placeholder={t('operationalPlan.meta.phSubDivision')} style={selectStyle} options={loc.options.subDivisions.map(s => ({ value: s, label: s }))} />
      </Form.Item>
    </div>
  );

  const forestMetadataUrl = calcId ? `/calculations/${calcId}?surface=field%2Fforestmetadata` : '';
  const forestNote = (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 12 }}
      data-testid="meta-from-forest-note"
      message={t('operationalPlan.meta.fromForestMetadata')}
      action={forestMetadataUrl ? (
        <Button size="small" type="link" href={forestMetadataUrl} data-testid="meta-edit-forest-metadata">
          {t('operationalPlan.meta.editInForestMetadata')}
        </Button>
      ) : undefined}
    />
  );

  const collapsibleSections = [
    {
      key: 'A',
      label: t('operationalPlan.meta.secA'),
      children: (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.cfRegistrationNumber')} name="cf_registration_number">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phCfRegistrationNumber')} />
              <HelpTooltip tKey="tooltips.csvUpload" />
            </div>
          </Form.Item>
          </FromForest>
          <Form.Item label={t('operationalPlan.meta.opPreparationYear')} name="op_preparation_year">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} min={2050} max={2099} placeholder={t('operationalPlan.meta.phOpPreparationYear')} />
              <HelpTooltip tKey="tooltips.opPreparationYear" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.snNumber')} name="sn_number">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phSnNumber')} />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.provinceGuidelineYear')} name="province_guideline_year" initialValue={2079}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} min={2050} max={2099} />
              <HelpTooltip tKey="validation.provinceYearRange" />
            </div>
          </Form.Item>
        </div>
      ),
    },
    {
      key: 'B',
      label: t('operationalPlan.meta.secB'),
      children: (
        <>
          {forestNote}
          <FromForest>
          {cascadingSelects('', forestLoc, handleProvinceChange, handleDistrictChange, handleMunicipalityChange)}
          <Divider plain style={{ fontSize: 12, color: '#999', margin: '8px 0' }}>
            {t('operationalPlan.meta.adminUnitDivider')}
          </Divider>
          {forestDeptSelects('', forestLoc, handleDivisionChange)}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginTop: 16 }}>
            <Form.Item label={t('operationalPlan.meta.subDivisionChief')} name="sub_division_chief">
              <Input placeholder={t('operationalPlan.meta.phSubDivisionChief')} />
            </Form.Item>
            <Form.Item label={t('operationalPlan.meta.forestManagementSectionChief')} name="forest_management_section_chief">
              <Input placeholder={t('operationalPlan.meta.phForestManagementSectionChief')} />
            </Form.Item>
            <Form.Item label={t('operationalPlan.meta.divisionForestOfficer')} name="division_forest_officer">
              <Input placeholder={t('operationalPlan.meta.phDivisionForestOfficer')} />
            </Form.Item>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Form.Item label={t('operationalPlan.meta.municipalityType')} name="forest_municipality_type">
              <Input disabled />
            </Form.Item>
          </div>
          </FromForest>
        </>
      ),
    },
    {
      key: 'C',
      label: t('operationalPlan.meta.secC'),
      children: (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.cfSnNumber')} name="cf_sn_number">
            <LocaleInputNumber style={selectStyle} min={0} />
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.constitutionApprovedYear')} name="constitution_approved_year">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <NepaliDatePicker placeholder={t('operationalPlan.meta.phBsDate')} />
              <HelpTooltip tKey="validation.dateFormat" />
            </div>
          </Form.Item>
          </FromForest>
          <Form.Item label={t('operationalPlan.meta.kabuliyatnamaDate')} name="kabuliyatnama_date">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <NepaliDatePicker placeholder={t('operationalPlan.meta.phBsDate')} />
              <HelpTooltip tKey="validation.dateFormat" />
            </div>
          </Form.Item>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.userGroupRegNo')} name="user_group_reg_no">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} min={0} />
            </div>
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.opStartFy')} name="op_start_fy">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phOpStartFy')} />
              <HelpTooltip tKey="validation.fiscalYearFormat" />
            </div>
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.opEndFy')} name="op_end_fy">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phOpEndFy')} />
              <HelpTooltip tKey="validation.fiscalYearFormat" />
            </div>
          </Form.Item>
          </FromForest>
        </div>
      ),
    },
    {
      key: 'D',
      label: t('operationalPlan.meta.secD'),
      children: (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16 }}>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.east')} name="cf_boundary_east">
            <Input placeholder={t('operationalPlan.meta.phCfBoundaryEast')} />
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.south')} name="cf_boundary_south">
            <Input placeholder={t('operationalPlan.meta.phCfBoundarySouth')} />
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.west')} name="cf_boundary_west">
            <Input placeholder={t('operationalPlan.meta.phCfBoundaryWest')} />
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.north')} name="cf_boundary_north">
            <Input placeholder={t('operationalPlan.meta.phCfBoundaryNorth')} />
          </Form.Item>
          </FromForest>
        </div>
      ),
    },
    {
      key: 'E',
      label: t('operationalPlan.meta.secE'),
      children: (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.physiographyZone')} name="physiography_zone">
            <Input placeholder={t('operationalPlan.meta.phAutoFilled')} />
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.protectedAreaStatus')} name="protected_area_status">
            <Input placeholder={t('operationalPlan.meta.phAutoFilled')} />
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.cfHandoverDate')} name="cf_handover_date">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <NepaliDatePicker />
              <HelpTooltip tKey="validation.dateFormat" />
            </div>
          </Form.Item>
          </FromForest>
        </div>
      ),
    },
    {
      key: 'F',
      label: t('operationalPlan.meta.secF'),
      children: (
        <FromForest>
          <div style={{ marginBottom: 8, color: '#888', fontSize: 12 }}>
            {ugPrepopulated ? t('operationalPlan.meta.ugAutoFilled') : t('operationalPlan.meta.ugWillAutoFill')}
          </div>
          {cascadingSelects('ug_', ugLoc, handleUgProvinceChange, handleUgDistrictChange, handleUgMunicipalityChange)}
          <Divider plain style={{ fontSize: 12, color: '#999', margin: '8px 0' }}>
            {t('operationalPlan.meta.adminUnitDivider')}
          </Divider>
          {forestDeptSelects('ug_', ugLoc, handleUgDivisionChange)}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Form.Item label={t('operationalPlan.meta.municipalityType')} name="ug_municipality_type">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Input disabled />
                <HelpTooltip tKey="validation.dateFormat" />
              </div>
            </Form.Item>
            <Form.Item label={t('operationalPlan.meta.ugSettlement')} name="ug_settlement">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Input placeholder={t('operationalPlan.meta.phUgSettlement')} />
                <HelpTooltip tKey="tooltips.subAreas" />
              </div>
            </Form.Item>
          </div>
        </FromForest>
      ),
    },
    {
      key: 'G',
      label: t('operationalPlan.meta.secG'),
      children: (
        <FromForest><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16 }}>
          <Form.Item label={t('operationalPlan.meta.east')} name="ug_boundary_east">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phUgBoundaryEast')} />
              <HelpTooltip tKey="tooltips.drawPolygon" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.south')} name="ug_boundary_south">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phUgBoundarySouth')} />
              <HelpTooltip tKey="tooltips.drawPolygon" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.west')} name="ug_boundary_west">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phUgBoundaryWest')} />
              <HelpTooltip tKey="tooltips.drawPolygon" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.north')} name="ug_boundary_north">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phUgBoundaryNorth')} />
              <HelpTooltip tKey="tooltips.drawPolygon" />
            </div>
          </Form.Item>
        </div></FromForest>
      ),
    },
    {
      key: 'H',
      label: t('operationalPlan.meta.secH'),
      children: (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.technicalAssistanceOrg')} name="technical_assistance_org" style={{ gridColumn: 'span 2' }}>
            <Input placeholder={t('operationalPlan.meta.phTechnicalAssistanceOrg')} />
          </Form.Item>
          </FromForest>
          <Form.Item label={t('operationalPlan.meta.opGeneralAssemblyDate')} name="op_general_assembly_date">
            <NepaliDatePicker />
          </Form.Item>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.forestType')} name="forest_type" initialValue="प्राकृतिक">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Select style={selectStyle}>
                <Select.Option value="प्राकृतिक">{t('operationalPlan.meta.ftNatural')}</Select.Option>
                <Select.Option value="वृक्षारोपण">{t('operationalPlan.meta.ftPlantation')}</Select.Option>
              </Select>
              <HelpTooltip tKey="validation.forestType" />
            </div>
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.forestAbundance')} name="forest_abundance" initialValue="रुख">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Select style={selectStyle}>
                <Select.Option value="रुख">{t('operationalPlan.meta.faTree')}</Select.Option>
                <Select.Option value="खाँवा">{t('operationalPlan.meta.faPole')}</Select.Option>
                <Select.Option value="पुनरोत्पादन">{t('operationalPlan.meta.faRegeneration')}</Select.Option>
              </Select>
              <HelpTooltip tKey="validation.abundance" />
            </div>
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.forestAvgAge')} name="forest_avg_age" initialValue={80}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} min={0} />
              <HelpTooltip tKey="validation.avgAge" />
            </div>
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.mainNonTimberFp')} name="main_non_timber_fp">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input placeholder={t('operationalPlan.meta.phMainNonTimberFp')} />
              <HelpTooltip tKey="tooltips.speciesSelect" />
            </div>
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.avgCrownDensityPct')} name="avg_crown_density_pct">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} min={0} max={100} />
              <HelpTooltip tKey="validation.crownDensity" />
            </div>
          </Form.Item>
          </FromForest>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.cfFirstRenewalDate')} name="cf_first_renewal_date">
            <NepaliDatePicker placeholder={t('operationalPlan.meta.phBsDate')} />
          </Form.Item>
          </FromForest>
          <Form.Item label={t('operationalPlan.meta.silvicultureSystem')} name="silviculture_system">
            <Input placeholder={t('operationalPlan.meta.phSilvicultureSystem')} />
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.rotationYears')} name="rotation_years">
            <LocaleInputNumber style={selectStyle} min={1} />
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.regenerationPeriodYears')} name="regeneration_period_years">
            <LocaleInputNumber style={selectStyle} min={1} />
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.motherTreeSpacingM')} name="mother_tree_spacing_m">
            <LocaleInputNumber style={selectStyle} min={1} />
          </Form.Item>
          <FromForest>
          <Form.Item label={t('operationalPlan.meta.cfHistoryNote')} name="cf_history_note" style={{ gridColumn: '1 / -1' }}>
            <Input.TextArea rows={3} placeholder={t('operationalPlan.meta.phCfHistoryNote')} />
          </Form.Item>
          </FromForest>
        </div>
      ),
    },
    {
      key: 'K',
      label: t('operationalPlan.meta.secK'),
      children: (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
          <Form.Item label={t('operationalPlan.meta.altitudeMinM')} name="altitude_min_m">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.altitudeMaxM')} name="altitude_max_m">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.altitudeMeanM')} name="altitude_mean_m">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.dominantSlope')} name="dominant_slope">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input />
              <HelpTooltip tKey="tooltips.dominantSlope" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.dominantAspect')} name="dominant_aspect">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input />
              <HelpTooltip tKey="tooltips.dominantAspect" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.dominantSoil')} name="dominant_soil">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Input />
              <HelpTooltip tKey="tooltips.dominantSoil" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.crownDensityPct')} name="crown_density_pct">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} min={0} max={100} />
              <HelpTooltip tKey="validation.crownDensity" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.treesPerHectare')} name="trees_per_hectare">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} />
              <HelpTooltip tKey="tooltips.treesPerHectare" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.growingStockM3PerHa')} name="growing_stock_m3_per_ha">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} />
              <HelpTooltip tKey="tooltips.growingStockPerHa" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.biomassTPerHa')} name="biomass_t_per_ha">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} />
              <HelpTooltip tKey="tooltips.biomassPerHa" />
            </div>
          </Form.Item>
          <Form.Item label={t('operationalPlan.meta.carbonStockTcPerHa')} name="carbon_stock_tc_per_ha">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LocaleInputNumber style={selectStyle} />
              <HelpTooltip tKey="tooltips.carbonPerHa" />
            </div>
          </Form.Item>
        </div>
      ),
    },
    {
      key: 'L',
      label: t('operationalPlan.meta.secL'),
      children: (
        <Form.Item label={t('operationalPlan.meta.planLanguage')} name="plan_language" initialValue="NP">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Select style={selectStyle}>
              <Select.Option value="NP">{t('operationalPlan.meta.langNepali')}</Select.Option>
              <Select.Option value="EN">{t('operationalPlan.meta.langEnglish')}</Select.Option>
            </Select>
            <HelpTooltip tKey="tooltips.planLanguage" />
          </div>
        </Form.Item>
      ),
    },
  ];

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-start justify-center overflow-y-auto" style={{ paddingTop: '20px', paddingBottom: '20px' }}>
      <div style={{ background: '#fff', borderRadius: 8, width: 900, maxWidth: '96%', padding: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>
            {t('operationalPlan.meta.title')}
          </h2>
          <Button onClick={onClose} type="text">✕</Button>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" /></div>
        ) : (
          <Form form={form} layout="vertical" onFinish={handleSave} noValidate>
            <Collapse
              defaultActiveKey={['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']}
              items={collapsibleSections}
              style={{ marginBottom: 16 }}
            />

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
              <Button onClick={onClose}>{t('common.cancel')}</Button>
              <Button type="primary" htmlType="submit" loading={saving}>{t('common.save')}</Button>
            </div>
          </Form>
        )}
      </div>
    </div>
  );
};

export default MetadataForm;
