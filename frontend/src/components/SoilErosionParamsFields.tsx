/**
 * SoilErosionParamsFields — the editable subset of the RUSLE parameter schema
 * as a controlled antd field group. Used by the per-forest override modal and
 * the admin profiles page. `value` is a sparse patch: a key present here is an
 * override; clearing a field removes the key so the value is inherited again
 * (code default ▸ profile ▸ this).
 */
import React from 'react';
import { InputNumber, Select, Switch, Input, Button, Tooltip } from 'antd';
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
  { key: 'slope_length_cap_m', label: 'Slope-length cap (m)', hint: 'LS: hillslope length used by the classic L', min: 10, max: 305 },
  { key: 'ls_cap', label: 'LS cap', hint: 'Upper clamp on LS (Desmet–Govers spikes in channels)', min: 1, max: 500 },
  { key: 'tolerable_soil_loss', label: 'Tolerable soil loss (t/ha/yr)', hint: 'Threshold for the narration and the % over-tolerable', min: 0.1, max: 100, step: 0.5 },
  { key: 'k_ceiling', label: 'K ceiling', hint: 'Upper clamp on soil erodibility', min: 0.005, max: 0.2, step: 0.005 },
  { key: 'c_disturbance_bump', label: 'Disturbance C multiplier', hint: '×C on cells with recent forest loss; 1.0 = off', min: 1, max: 5, step: 0.1 },
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

export const SoilErosionParamsFields: React.FC<Props> = ({ value, onChange, disabled }) => {
  const setKey = (k: string, v: unknown) => {
    const next = { ...value };
    if (v === undefined || v === null || v === '') delete next[k];
    else next[k] = v;
    onChange(next);
  };

  const breaks = Array.isArray(value.severity_breaks)
    ? (value.severity_breaks as number[]).join(', ')
    : '';

  return (
    <div>
      <Row label="R-factor method" hint="MFI (Arnoldus) or the annual-precip regression" set={'r_method' in value} onClear={() => setKey('r_method', undefined)}>
        <Select
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          value={(value.r_method as string) ?? undefined}
          placeholder="inherited"
          onChange={(v) => setKey('r_method', v)}
          options={[
            { value: 'mfi', label: 'MFI — Arnoldus 1980' },
            { value: 'annual_regression', label: 'Annual-precip regression' },
          ]}
        />
      </Row>

      <Row label="LS method" hint="Moore & Burch (capped length) or Desmet–Govers (D8 flow accumulation)" set={'ls_method' in value} onClear={() => setKey('ls_method', undefined)}>
        <Select
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          value={(value.ls_method as string) ?? undefined}
          placeholder="inherited"
          onChange={(v) => setKey('ls_method', v)}
          options={[
            { value: 'moore_burch', label: 'Moore & Burch (v1)' },
            { value: 'desmet_govers', label: 'Desmet–Govers (D8)' },
          ]}
        />
      </Row>

      {NUM_FIELDS.map((f) => (
        <Row key={f.key} label={f.label} hint={f.hint} set={f.key in value} onClear={() => setKey(f.key, undefined)}>
          <InputNumber
            size="small"
            style={{ width: 140 }}
            disabled={disabled}
            min={f.min}
            max={f.max}
            step={f.step ?? 1}
            placeholder="inherited"
            value={(value[f.key] as number) ?? null}
            onChange={(v) => setKey(f.key, v ?? undefined)}
          />
        </Row>
      ))}

      <Row label="Severity class breaks" hint="Comma-separated t/ha/yr, strictly increasing (e.g. 5, 10, 20, 40, 80)" set={'severity_breaks' in value} onClear={() => setKey('severity_breaks', undefined)}>
        <Input
          size="small"
          style={{ width: 200 }}
          disabled={disabled}
          placeholder="inherited"
          value={breaks}
          onChange={(e) => {
            const raw = e.target.value.trim();
            if (!raw) return setKey('severity_breaks', undefined);
            const nums = raw
              .split(',')
              .map((s) => Number(s.trim()))
              .filter((n) => Number.isFinite(n));
            setKey('severity_breaks', nums);
          }}
        />
      </Row>

      <Row label="Sediment delivery (SDR)" hint="Compute the fraction of gross soil loss delivered to streams" set={'sdr_enabled' in value} onClear={() => setKey('sdr_enabled', undefined)}>
        <Switch
          size="small"
          disabled={disabled}
          checked={value.sdr_enabled === true}
          onChange={(v) => setKey('sdr_enabled', v)}
        />
      </Row>
    </div>
  );
};

export default SoilErosionParamsFields;
