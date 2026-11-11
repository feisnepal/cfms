/**
 * SfmParamsFields — the editable subset of the SfmParams schema as a controlled
 * antd field group (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P7). Used by the
 * per-forest override panel (`SfmParamsPanel`) and the admin profiles page.
 *
 * `value` is a *sparse* patch: a key present here is an override; clearing a
 * field removes the key so the value is inherited again (code default ▸
 * physiography profile ▸ this).
 */
import React from 'react';
import { InputNumber, Select, Button, Tooltip } from 'antd';
import { CloseCircleOutlined } from '@ant-design/icons';

export type ParamPatch = Record<string, unknown>;

interface Props {
  value: ParamPatch;
  onChange: (next: ParamPatch) => void;
  disabled?: boolean;
}

const NUM_FIELDS: Array<{
  key: string;
  label: string;
  hint: string;
  min: number;
  max: number;
  step?: number;
}> = [
  { key: 'seedling_threshold', label: 'Seedling threshold (विरुवा / ha)', hint: 'Above this the regeneration branch is क (adequate)', min: 0, max: 100000, step: 500 },
  { key: 'sapling_threshold', label: 'Sapling threshold (लाथ्रा / ha)', hint: 'Second regeneration-adequacy gate', min: 0, max: 100000, step: 500 },
  { key: 'crown_density_default', label: 'Crown density default (%)', hint: 'Used when a block has no measured crown density; < 20 % trips सि.नं. 6', min: 0, max: 100 },
  { key: 'harvestable_dbh_min_cm', label: 'Harvestable DBH min (cm)', hint: 'Trees below this are advance growth and never counted for yield', min: 1, max: 200, step: 1 },
  { key: 'riparian_buffer_m', label: 'Riparian buffer (m)', hint: 'Buffer around river84 that triggers सि.नं. 5 (riverine)', min: 0, max: 1000, step: 5 },
  { key: 'protection_slope_band', label: 'Protection slope band', hint: '1–4; band 4 (> 45°) makes the hill/conifer types salvage-only', min: 1, max: 4 },
  { key: 'mother_tree_target_min', label: 'Mother trees / ha — min', hint: 'Shelterwood retention lower bound', min: 0, max: 500 },
  { key: 'mother_tree_target_max', label: 'Mother trees / ha — max', hint: 'Shelterwood retention upper bound', min: 0, max: 500 },
  { key: 'mean_mother_tree_vol_m3', label: 'Mean mother-tree volume (m³)', hint: 'Subtracted from the shelterwood periodic-block harvest', min: 0.1, max: 50, step: 0.1 },
  { key: 'slope_vector_sliver_m2', label: 'Slope-class sliver floor (m²)', hint: 'P11 helper — polygons smaller than this are absorbed', min: 1, max: 1000000, step: 100 },
];

const INTENSITY = [
  { k: 'production', label: 'Production %' },
  { k: 'conservation', label: 'Conservation %' },
  { k: 'protection', label: 'Protection %' },
] as const;

const Row: React.FC<{
  label: string;
  hint: string;
  set: boolean;
  onClear: () => void;
  children: React.ReactNode;
}> = ({ label, hint, set, onClear, children }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
    <Tooltip title={hint}>
      <span style={{ width: 240, fontSize: 13, color: set ? undefined : '#999' }}>{label}</span>
    </Tooltip>
    {children}
    {set && (
      <Button
        type="text"
        size="small"
        icon={<CloseCircleOutlined />}
        onClick={onClear}
        title="Clear this override"
      />
    )}
  </div>
);

export const SfmParamsFields: React.FC<Props> = ({ value, onChange, disabled }) => {
  const setKey = (k: string, v: unknown) => {
    const next = { ...value };
    if (v === undefined || v === null || v === '') delete next[k];
    else next[k] = v;
    onChange(next);
  };

  const intensity = (value.sampling_intensity_pct as Record<string, number>) || undefined;
  const setIntensity = (k: string, v: number | null) => {
    const cur = { ...(intensity || {}) };
    if (v === null || v === undefined) delete cur[k];
    else cur[k] = v;
    const next = { ...value };
    if (Object.keys(cur).length === 0) delete next.sampling_intensity_pct;
    else next.sampling_intensity_pct = cur;
    onChange(next);
  };

  return (
    <div>
      {NUM_FIELDS.map((f) => (
        <Row
          key={f.key}
          label={f.label}
          hint={f.hint}
          set={value[f.key] !== undefined}
          onClear={() => setKey(f.key, undefined)}
        >
          <InputNumber
            size="small"
            min={f.min}
            max={f.max}
            step={f.step}
            disabled={disabled}
            style={{ width: 120 }}
            value={value[f.key] as number | undefined}
            onChange={(v) => setKey(f.key, v)}
          />
        </Row>
      ))}

      <Row
        label="Crown-density estimate source"
        hint="When a block has no measured crown density: canopy raster / ESA tree-cover / just the default"
        set={value.crown_density_estimate_source !== undefined}
        onClear={() => setKey('crown_density_estimate_source', undefined)}
      >
        <Select
          size="small"
          style={{ width: 160 }}
          disabled={disabled}
          value={value.crown_density_estimate_source as string | undefined}
          placeholder="none (default)"
          onChange={(v) => setKey('crown_density_estimate_source', v)}
          options={[
            { value: 'none', label: 'none (use default)' },
            { value: 'canopy', label: 'canopy raster' },
            { value: 'esa', label: 'ESA tree cover' },
          ]}
        />
      </Row>

      <div style={{ fontSize: 12, color: '#888', margin: '4px 0' }}>
        Sampling intensity floors (§16) — advisory
      </div>
      {INTENSITY.map(({ k, label }) => (
        <Row
          key={k}
          label={label}
          hint="Overrides the §16 minimum for this stratum"
          set={intensity?.[k] !== undefined}
          onClear={() => setIntensity(k, null)}
        >
          <InputNumber
            size="small"
            min={0}
            max={100}
            step={0.5}
            disabled={disabled}
            style={{ width: 120 }}
            value={intensity?.[k]}
            onChange={(v) => setIntensity(k, typeof v === 'number' ? v : null)}
          />
        </Row>
      ))}
    </div>
  );
};

export default SfmParamsFields;
