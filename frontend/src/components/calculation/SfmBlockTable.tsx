/**
 * SfmBlockTable — one row per leaf block / compartment
 * (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4).
 *
 * Zone · Inner-Terai tag · slope band · dominant species (+ share) · regen
 * branch (क / ख / —) · proposed type (tooltip = reasons + confidence, amber dot
 * when needs_review) · override <Select> (14) · crown-density <InputNumber>
 * (save on blur) · prescription one-liner · felling series · working-circle
 * proposal tag (click accepts it). There is deliberately NO per-block harvest
 * column — yield is regulated per felling series, not per block.
 */
import React, { useEffect, useState } from 'react';
import { Table, Tag, Select, InputNumber, Tooltip, Badge, Button } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import { SFM_LAND_CLASSES, type SfmBlock, type SfmBlockPatch, type SfmLandClass, type SfmZone } from '../../services/api';
import { SfmTypeTag } from './SfmTypeTag';
import { SfmBlockState } from './SfmBlockState';
import { useSfmForestTypes } from '../../hooks/useSfmForestTypes';
import { orientationColor } from '../../lib/sfmForestTypes';
import { SfmVarChip } from './SfmVarChip';
import { SlopeBandBar } from './SfmSlopeHelperPanel';

interface Props {
  blocks: SfmBlock[];
  zoneByBlock: Record<string, SfmZone>;
  selectedBlock: string | null;
  patchingBlock: string | null;
  lang: string;
  onSelect: (blockName: string) => void;
  onPatch: (blockName: string, patch: SfmBlockPatch) => void;
}

const SLOPE_BAND_LABEL: Record<number, string> = {
  1: '< 19°',
  2: '19–31°',
  3: '31–45°',
  4: '> 45°',
};

/** One row of the override list: "Type 7", the name in both languages and the orientation colour. */
const SfmTypeOption: React.FC<{ n: number }> = ({ n }) => {
  const t = useT();
  const { types } = useSfmForestTypes();
  const p = types?.[n];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6, whiteSpace: 'normal' }}>
      <strong>{t('sfm.typeNo', { n })}</strong>
      {p && (
        <span style={{ fontSize: 11, color: '#555' }}>
          <span style={{ color: orientationColor(p.orientation) }}>●</span> {p.name_ne} · {p.name_en}
        </span>
      )}
    </span>
  );
};

const TYPE_OPTIONS = Array.from({ length: 14 }, (_, i) => i + 1);

/** Crown-density cell — local state so a blur commits, re-key on prop change. */
const CrownCell: React.FC<{
  block: SfmBlock;
  disabled: boolean;
  onCommit: (v: number | null) => void;
}> = ({ block, disabled, onCommit }) => {
  const effective =
    block.override_crown_density_pct ?? block.inputs.crown_density_pct ?? null;
  const [val, setVal] = useState<number | null>(effective);
  useEffect(() => setVal(effective), [effective]);
  return (
    <InputNumber
      size="small"
      min={0}
      max={100}
      value={val}
      disabled={disabled}
      style={{ width: 70 }}
      onChange={(v) => setVal(typeof v === 'number' ? v : null)}
      onBlur={() => {
        if (val !== effective && typeof val === 'number') onCommit(val);
      }}
    />
  );
};

export const SfmBlockTable: React.FC<Props> = ({
  blocks,
  zoneByBlock,
  selectedBlock,
  patchingBlock,
  lang,
  onSelect,
  onPatch,
}) => {
  const t = useT();
  const ne = lang.startsWith('ne');

  const columns: ColumnsType<SfmBlock> = [
    {
      title: t('sfm.block.name'),
      dataIndex: 'block_name',
      key: 'block_name',
      fixed: 'left',
      width: 120,
      render: (name: string) => <b>{name}</b>,
    },
    {
      title: t('sfm.block.zone'),
      key: 'zone',
      width: 150,
      render: (_: unknown, r: SfmBlock) => {
        const z = zoneByBlock[r.block_name];
        if (!z) return '—';
        return (
          <span>
            {t(`sfm.zone.${z.sfm_zone}`, z.sfm_zone)}
            {z.inner_terai && (
              <Tag color="gold" style={{ marginInlineStart: 4 }}>
                {t('sfm.block.innerTerai')}
              </Tag>
            )}
          </span>
        );
      },
    },
    {
      title: t('sfm.block.slopeBand'),
      key: 'slope_band',
      width: 140,
      render: (_: unknown, r: SfmBlock) => {
        const z = zoneByBlock[r.block_name];
        const b = z?.slope_band;
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span>{b ? SLOPE_BAND_LABEL[b] ?? String(b) : '—'}</span>
            {z?.slope_band_area_pct && (
              <SlopeBandBar pctByBand={z.slope_band_area_pct} width={64} />
            )}
          </span>
        );
      },
    },
    {
      title: t('sfm.block.species'),
      key: 'species',
      width: 170,
      render: (_: unknown, r: SfmBlock) => {
        const dom = r.inputs.dominant_species?.[0];
        if (!dom) return r.inputs.dominant_group ?? '—';
        return (
          <Tooltip
            title={(r.inputs.dominant_species || [])
              .map((s) => `${s.local || s.scientific} ${s.share_pct.toFixed(0)}%`)
              .join(', ')}
          >
            <span>
              {dom.local || dom.scientific}{' '}
              <span style={{ color: '#999' }}>{dom.share_pct.toFixed(0)}%</span>
              {r.inputs.dominant_group && (
                <Tag style={{ marginInlineStart: 4 }}>{r.inputs.dominant_group}</Tag>
              )}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: t('sfm.block.regen'),
      key: 'regen',
      width: 80,
      align: 'center',
      render: (_: unknown, r: SfmBlock) => {
        const v = r.inputs.regen_adequate;
        if (v === true) return <Tag color="green">{t('sfm.block.regenAdequate')}</Tag>;
        if (v === false) return <Tag color="orange">{t('sfm.block.regenInadequate')}</Tag>;
        return <span style={{ color: '#bbb' }}>—</span>;
      },
    },
    {
      title: t('sfm.block.proposedType'),
      key: 'proposed_type_no',
      width: 110,
      render: (_: unknown, r: SfmBlock) => {
        // the classifier emits one " · "-joined string per language
        const reasons = String((ne ? r.reasons_ne : r.reasons_en) || '')
          .split(' · ')
          .map((s) => s.trim())
          .filter(Boolean);
        return (
          <span>
            {r.needs_review && <Badge status="warning" style={{ marginInlineEnd: 4 }} />}
            <SfmBlockState
              state={r.state}
              plot_count={r.plot_count}
              land_class={r.land_class}
              estimate_type_no={r.estimate_type_no}
              typeNo={r.proposed_type_no}
              block={{ reasons, confidence: r.confidence, needsReview: r.needs_review }}
            />
          </span>
        );
      },
    },
    {
      title: t('sfm.block.landClass'),
      key: 'land_class',
      width: 150,
      render: (_: unknown, r: SfmBlock) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Select<SfmLandClass>
            size="small"
            style={{ width: 130 }}
            value={r.land_class}
            disabled={patchingBlock === r.block_name}
            loading={patchingBlock === r.block_name}
            // choosing what ESA already suggests clears the override (back to "from ESA")
            onChange={(v) => onPatch(r.block_name, { land_class: v === r.land_class_suggestion ? null : v })}
            options={SFM_LAND_CLASSES.map((c) => ({ value: c, label: t(`sfm.landClass.${c}`, c) }))}
          />
          <div style={{ fontSize: 10, color: '#888' }}>
            {r.land_class_source === 'user'
              ? t('sfm.block.landClassUser', { esa: t(`sfm.landClass.${r.land_class_suggestion}`, r.land_class_suggestion) })
              : t('sfm.block.landClassEsa')}
          </div>
        </span>
      ),
    },
    {
      title: t('sfm.block.override'),
      key: 'override_type_no',
      width: 130,
      render: (_: unknown, r: SfmBlock) => (
        <Select<number | null>
          size="small"
          allowClear
          style={{ width: 110 }}
          value={r.override_type_no ?? undefined}
          placeholder={t('sfm.block.overridePlaceholder')}
          disabled={patchingBlock === r.block_name || r.state === 'non_forest'}
          loading={patchingBlock === r.block_name}
          onClick={(e) => e.stopPropagation()}
          onChange={(v) =>
            onPatch(r.block_name, { override_type_no: v ?? null })
          }
          popupMatchSelectWidth={false}
          options={TYPE_OPTIONS.map((n) => ({
            value: n,
            label: t('sfm.typeNo', { n }),
          }))}
          optionRender={(o) => <SfmTypeOption n={Number(o.value)} />}
        />
      ),
    },
    {
      title: t('sfm.block.crown'),
      key: 'crown',
      width: 90,
      render: (_: unknown, r: SfmBlock) => (
        <span onClick={(e) => e.stopPropagation()}>
          <CrownCell
            block={r}
            disabled={patchingBlock === r.block_name}
            onCommit={(v) => onPatch(r.block_name, { crown_density_pct: v })}
          />
        </span>
      ),
    },
    {
      title: t('sfm.block.prescription'),
      key: 'prescription',
      width: 180,
      render: (_: unknown, r: SfmBlock) => {
        const p = r.prescription;
        if (!p) return '—';
        return <span>{ne ? p.system_ne : p.system_en}</span>;
      },
    },
    {
      title: t('sfm.block.series'),
      key: 'felling_series_id',
      width: 90,
      align: 'center',
      render: (_: unknown, r: SfmBlock) =>
        r.felling_series_id != null
          ? <SfmTypeTag n={r.felling_series_id} />
          : <span style={{ color: '#bbb' }}>—</span>,
    },
    {
      title: t('sfm.block.orientation'),
      key: 'orientation',
      width: 150,
      render: (_: unknown, r: SfmBlock) => {
        const wc = r.working_circle_proposal;
        return (
          <span onClick={(e) => e.stopPropagation()}>
            <Tag>{r.orientation ? t(`sfm.orientation.${r.orientation}`, r.orientation) : '—'}</Tag>
            {wc && !r.wc_accept && (
              <Tooltip title={ne ? wc.justification_ne : wc.justification_en}>
                <Button
                  size="small"
                  type="link"
                  style={{ padding: '0 4px' }}
                  loading={patchingBlock === r.block_name}
                  onClick={() =>
                    onPatch(r.block_name, { accept_working_circle: true })
                  }
                >
                  {t('sfm.block.acceptWc')}
                </Button>
              </Tooltip>
            )}
            {wc && r.wc_accept && <Tag color="green">✓</Tag>}
          </span>
        );
      },
    },
  ];

  return (
    <Table<SfmBlock>
      size="small"
      rowKey="block_name"
      dataSource={blocks}
      columns={columns}
      pagination={false}
      scroll={{ x: 1450 }}
      title={() => (
        <b>
          {t('sfm.block.heading')}
          <SfmVarChip tokenKey="sfm_block_prescription_table" />
        </b>
      )}
      rowClassName={(r) =>
        r.block_name === selectedBlock ? 'ant-table-row-selected' : ''
      }
      onRow={(r) => ({
        onClick: () => onSelect(r.block_name),
        style: { cursor: 'pointer' },
      })}
    />
  );
};

export default SfmBlockTable;
