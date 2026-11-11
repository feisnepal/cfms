/**
 * HazardVulnParamsFields — the editable subset of the landslide-hazard +
 * household-vulnerability parameter schema as a controlled antd field group.
 * Used by the per-forest override modal and the admin profiles page.
 *
 * `value` is a *nested* sparse patch: `{ landslide: {...}, factor_of_safety:
 * {...}, household: {...} }`. A key present under its group is an override;
 * clearing it removes the key (and the group if it becomes empty) so the value
 * is inherited again (code default ▸ profile ▸ this).
 */
import React from 'react';
import { InputNumber, Select, Switch, Button, Tooltip, Divider } from 'antd';
import { CloseCircleOutlined } from '@ant-design/icons';

export type ParamPatch = Record<string, Record<string, unknown>>;

interface Props {
  value: ParamPatch;
  onChange: (next: ParamPatch) => void;
  disabled?: boolean;
}

type NumField = {
  group: string;
  key: string;
  label: string;
  hint: string;
  min: number;
  max: number;
  step?: number;
};

const NUM_FIELDS: NumField[] = [
  { group: 'landslide', key: 'prone_class_min', label: 'Prone-class minimum', hint: 'LSI class (1-based) at or above which a cell is "landslide-prone"', min: 1, max: 9 },
  { group: 'landslide', key: 'twi_high_percentile', label: 'Wet-cell TWI percentile', hint: 'TWI above this AOI percentile counts as wet-convergent (+rating)', min: 50, max: 99 },
  { group: 'factor_of_safety', key: 'depth_constant_m', label: 'Regolith depth (m)', hint: 'Assumed soil depth for the constant depth model', min: 0.1, max: 10, step: 0.1 },
  { group: 'factor_of_safety', key: 'saturation_ratio_m', label: 'Pore-pressure ratio m', hint: 'Wet-season saturation ratio for the FS scenario (0 dry .. 1 saturated)', min: 0, max: 1, step: 0.05 },
  { group: 'household', key: 'top_n', label: 'Priority households (top-N)', hint: 'How many households are flagged "priority"', min: 1, max: 1000 },
  { group: 'household', key: 'runout_buffer_m', label: 'Runout buffer (m)', hint: 'Downslope buffer below a High-LSI cell counted as exposed', min: 0, max: 2000, step: 10 },
];

const Row: React.FC<{
  label: string;
  hint: string;
  set: boolean;
  onClear: () => void;
  children: React.ReactNode;
}> = ({ label, hint, set, onClear, children }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
    <Tooltip title={hint}>
      <span style={{ width: 220, fontSize: 13, color: set ? undefined : '#999' }}>{label}</span>
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

export const HazardVulnParamsFields: React.FC<Props> = ({ value, onChange, disabled }) => {
  const get = (group: string, key: string): unknown =>
    (value[group] || {})[key];
  const has = (group: string, key: string): boolean =>
    Object.prototype.hasOwnProperty.call(value[group] || {}, key);

  const setKey = (group: string, key: string, v: unknown) => {
    const next: ParamPatch = { ...value, [group]: { ...(value[group] || {}) } };
    if (v === undefined || v === null || v === '') {
      delete next[group][key];
      if (Object.keys(next[group]).length === 0) delete next[group];
    } else {
      next[group][key] = v;
    }
    onChange(next);
  };

  return (
    <div>
      <Divider titlePlacement="start" style={{ fontSize: 12, margin: '4px 0 12px' }}>
        Landslide susceptibility
      </Divider>
      <Row label="Overlay method" hint="Weighted overlay, or weights from the AHP pairwise matrix" set={has('landslide', 'method')} onClear={() => setKey('landslide', 'method', undefined)}>
        <Select
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          value={(get('landslide', 'method') as string) ?? undefined}
          placeholder="inherited"
          onChange={(v) => setKey('landslide', 'method', v)}
          options={[
            { value: 'weighted_overlay', label: 'Weighted overlay' },
            { value: 'ahp', label: 'AHP eigenvector' },
          ]}
        />
      </Row>
      <Row label="Class method" hint="How the LSI score is cut into classes" set={has('landslide', 'class_method')} onClear={() => setKey('landslide', 'class_method', undefined)}>
        <Select
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          value={(get('landslide', 'class_method') as string) ?? undefined}
          placeholder="inherited"
          onChange={(v) => setKey('landslide', 'class_method', v)}
          options={[
            { value: 'quantile', label: 'Quantile (self-relative)' },
            { value: 'equal', label: 'Equal interval' },
            { value: 'fixed', label: 'Fixed breaks' },
          ]}
        />
      </Row>
      <Row label="Seismic factor" hint="Epicentral-density surface from the earthquake catalogue (off by default — not PGA)" set={has('landslide', 'seismic_enabled')} onClear={() => setKey('landslide', 'seismic_enabled', undefined)}>
        <Switch
          size="small"
          disabled={disabled}
          checked={get('landslide', 'seismic_enabled') === true}
          onChange={(v) => setKey('landslide', 'seismic_enabled', v)}
        />
      </Row>

      <Divider titlePlacement="start" style={{ fontSize: 12, margin: '12px 0' }}>
        Slope stability (Factor of Safety)
      </Divider>
      <Row label="FS map included" hint="Compute and render the infinite-slope Factor-of-Safety scenario" set={has('factor_of_safety', 'enabled')} onClear={() => setKey('factor_of_safety', 'enabled', undefined)}>
        <Switch
          size="small"
          disabled={disabled}
          checked={get('factor_of_safety', 'enabled') !== false}
          onChange={(v) => setKey('factor_of_safety', 'enabled', v)}
        />
      </Row>
      <Row label="Soil-depth model" hint="Constant sheet, or a slope-thinning linear model (the one assumed parameter)" set={has('factor_of_safety', 'soil_depth_model')} onClear={() => setKey('factor_of_safety', 'soil_depth_model', undefined)}>
        <Select
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          value={(get('factor_of_safety', 'soil_depth_model') as string) ?? undefined}
          placeholder="inherited"
          onChange={(v) => setKey('factor_of_safety', 'soil_depth_model', v)}
          options={[
            { value: 'constant', label: 'Constant' },
            { value: 'slope_linear', label: 'Slope-linear (thins on steep ground)' },
          ]}
        />
      </Row>
      <Row label="TWI-varied m" hint="Raise the pore-pressure ratio in topographically-wet cells" set={has('factor_of_safety', 'saturation_twi_varied')} onClear={() => setKey('factor_of_safety', 'saturation_twi_varied', undefined)}>
        <Switch
          size="small"
          disabled={disabled}
          checked={get('factor_of_safety', 'saturation_twi_varied') !== false}
          onChange={(v) => setKey('factor_of_safety', 'saturation_twi_varied', v)}
        />
      </Row>
      <Row label="Instability index" hint="1/FS, or the SINMAP stability-index form" set={has('factor_of_safety', 'instability_index')} onClear={() => setKey('factor_of_safety', 'instability_index', undefined)}>
        <Select
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          value={(get('factor_of_safety', 'instability_index') as string) ?? undefined}
          placeholder="inherited"
          onChange={(v) => setKey('factor_of_safety', 'instability_index', v)}
          options={[
            { value: 'inv_fs', label: '1 / FS' },
            { value: 'sinmap_si', label: 'SINMAP SI' },
          ]}
        />
      </Row>

      <Divider titlePlacement="start" style={{ fontSize: 12, margin: '12px 0' }}>
        Household vulnerability
      </Divider>
      <Row label="Score normalisation" hint="Min-max, or rank-based (outlier-robust)" set={has('household', 'normalisation')} onClear={() => setKey('household', 'normalisation', undefined)}>
        <Select
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          value={(get('household', 'normalisation') as string) ?? undefined}
          placeholder="inherited"
          onChange={(v) => setKey('household', 'normalisation', v)}
          options={[
            { value: 'minmax', label: 'Min–max' },
            { value: 'quantile', label: 'Quantile (rank)' },
          ]}
        />
      </Row>

      {NUM_FIELDS.map((f) => (
        <Row
          key={`${f.group}.${f.key}`}
          label={f.label}
          hint={f.hint}
          set={has(f.group, f.key)}
          onClear={() => setKey(f.group, f.key, undefined)}
        >
          <InputNumber
            size="small"
            style={{ width: 140 }}
            disabled={disabled}
            min={f.min}
            max={f.max}
            step={f.step ?? 1}
            placeholder="inherited"
            value={(get(f.group, f.key) as number) ?? null}
            onChange={(v) => setKey(f.group, f.key, v ?? undefined)}
          />
        </Row>
      ))}
    </div>
  );
};

export default HazardVulnParamsFields;
