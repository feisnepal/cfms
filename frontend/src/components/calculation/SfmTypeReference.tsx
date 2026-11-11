/**
 * The अनुसूची-१ forest-type reference: an expandable side panel (a drawer), so the user keeps their page.
 *
 * Opened by clicking any "Type N" tag (that type is highlighted and expanded) or the "Forest types reference"
 * button in the SFM tab. Names, notes and systems are shown in Nepali and English together (owner, 2026-10-06).
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Button, Drawer, Space, Table, Tag } from 'antd';
import { ExpandAltOutlined, ShrinkOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import { useSfmForestTypes } from '../../hooks/useSfmForestTypes';
import { harvestLines, orientationColor, slopeKey } from '../../lib/sfmForestTypes';
import type { SfmBranch, SfmPrescription } from '../../services/api';

interface RefApi {
  /** Open the panel; `n` highlights and expands that type. */
  open: (n?: number) => void;
}

const Ctx = createContext<RefApi | null>(null);

/** `null` outside a provider: a tag then shows its tooltip but is not clickable. */
export const useSfmTypeReference = (): RefApi | null => useContext(Ctx);

const BranchDetail: React.FC<{ keyName: string; b: SfmBranch }> = ({ keyName, b }) => {
  const t = useT();
  const lines = harvestLines(b, t);
  const rotation = Array.isArray(b.rotation_years) ? b.rotation_years.join('–') : b.rotation_years;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontWeight: 600 }}>{t(`sfm.ref.branch.${keyName}`, keyName)}</div>
      <div>
        {b.system_ne}
        <div style={{ color: '#555' }}>{b.system_en}</div>
      </div>
      <div style={{ color: '#888' }}>
        {b.regen_method_ne} / {b.regen_method_en}
        {b.felling_cycle_years != null && <> · {t('sfm.ref.fellingCycle')}: {t('sfm.ref.years', { n: b.felling_cycle_years })}</>}
        {rotation != null && <> · {t('sfm.ref.rotation')}: {t('sfm.ref.years', { n: rotation })}</>}
        {b.regeneration_period_years != null && <> · {t('sfm.ref.regenPeriod')}: {t('sfm.ref.years', { n: b.regeneration_period_years })}</>}
        {b.mother_trees_per_ha && <> · {t('sfm.ref.motherTrees')}: {b.mother_trees_per_ha.join('–')}/ha</>}
      </div>
      {lines.length > 0 && (
        <div style={{ marginTop: 2 }}>
          <span style={{ color: '#888' }}>{t('sfm.ref.harvest')}:</span>
          {lines.map((l, i) => (
            <div key={i}>• {l}</div>
          ))}
        </div>
      )}
      {(b.note_ne || b.note_en) && (
        <div style={{ color: '#555', marginTop: 2 }}>
          {b.note_ne && <div>{b.note_ne}</div>}
          {b.note_en && <div>{b.note_en}</div>}
        </div>
      )}
    </div>
  );
};

const TypeDetail: React.FC<{ p: SfmPrescription }> = ({ p }) => {
  const t = useT();
  return (
    <div style={{ padding: '4px 8px', fontSize: 12.5 }} data-testid={`sfm-ref-detail-${p.type_no}`}>
      {Object.entries(p.branches ?? {}).map(([k, b]) => (
        <BranchDetail key={k} keyName={k} b={b} />
      ))}
      {(p.notes_ne || p.notes_en) && (
        <div style={{ borderTop: '1px solid #eee', paddingTop: 6 }}>
          <span style={{ color: '#888' }}>{t('sfm.ref.notes')}:</span>
          {p.notes_ne && <div>{p.notes_ne}</div>}
          {p.notes_en && <div style={{ color: '#555' }}>{p.notes_en}</div>}
        </div>
      )}
    </div>
  );
};

export const SfmTypeReferenceProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const t = useT();
  const { types, failed } = useSfmForestTypes();
  const [isOpen, setIsOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);
  const [openRows, setOpenRows] = useState<number[]>([]);

  const open = useCallback((n?: number) => {
    setIsOpen(true);
    if (n != null) {
      setFocus(n);
      setOpenRows((rows) => (rows.includes(n) ? rows : [...rows, n]));
    }
  }, []);

  // bring the focused row into view once the drawer has rendered it
  useEffect(() => {
    if (!isOpen || focus == null) return;
    const id = window.setTimeout(() => {
      document.getElementById(`sfm-ref-row-${focus}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, 250);
    return () => window.clearTimeout(id);
  }, [isOpen, focus]);

  const rows = useMemo(() => (types ? Object.values(types).sort((a, b) => a.type_no - b.type_no) : []), [types]);

  const columns: ColumnsType<SfmPrescription> = [
    { title: t('sfm.ref.col.no'), dataIndex: 'type_no', key: 'no', width: 56, align: 'center' },
    {
      title: t('sfm.ref.col.forest'),
      key: 'forest',
      render: (_: unknown, p) => (
        <div id={`sfm-ref-row-${p.type_no}`}>
          <div>{p.name_ne}</div>
          <div style={{ color: '#555' }}>{p.name_en}</div>
        </div>
      ),
    },
    {
      title: t('sfm.ref.col.orientation'),
      key: 'orientation',
      width: 130,
      render: (_: unknown, p) => (
        <Tag color={orientationColor(p.orientation)}>{t(`sfm.orientation.${p.orientation}`, p.orientation)}</Tag>
      ),
    },
    {
      title: t('sfm.ref.zone'),
      key: 'zone',
      width: 110,
      render: (_: unknown, p) => (p.zone_triggers ?? []).map((z) => t(`sfm.zone.${z}`, z)).join(', ') || '—',
    },
    {
      title: t('sfm.ref.species'),
      key: 'species',
      width: 130,
      render: (_: unknown, p) => (p.species_groups ?? []).map((g) => t(`sfm.ref.group.${g}`, g)).join(', ') || '—',
    },
    { title: t('sfm.ref.slope'), key: 'slope', width: 100, render: (_: unknown, p) => t(slopeKey(p)) },
    {
      title: t('sfm.ref.origin'),
      key: 'origin',
      width: 100,
      render: (_: unknown, p) => (p.origin ? t(`sfm.ref.originValue.${p.origin}`, p.origin) : '—'),
    },
  ];

  const api = useMemo<RefApi>(() => ({ open }), [open]);

  return (
    <Ctx.Provider value={api}>
      {children}
      <Drawer
        open={isOpen}
        onClose={() => setIsOpen(false)}
        width={expanded ? '92vw' : 560}
        mask={false}
        title={
          <Space>
            <span>{t('sfm.ref.title')}</span>
            <Button
              size="small"
              type="text"
              aria-label={expanded ? t('sfm.ref.collapse') : t('sfm.ref.expand')}
              icon={expanded ? <ShrinkOutlined /> : <ExpandAltOutlined />}
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded ? t('sfm.ref.collapse') : t('sfm.ref.expand')}
            </Button>
          </Space>
        }
        destroyOnHidden
      >
        <p style={{ fontSize: 12, color: '#666', marginTop: 0 }}>{t('sfm.ref.intro')}</p>
        {failed ? (
          <div style={{ color: '#cf1322' }}>{t('sfm.ref.loadFailed')}</div>
        ) : (
          <Table<SfmPrescription>
            size="small"
            rowKey="type_no"
            dataSource={rows}
            columns={columns}
            pagination={false}
            loading={!types}
            rowClassName={(p) => (p.type_no === focus ? 'sfm-ref-row-focus' : '')}
            onRow={(p) => ({ style: p.type_no === focus ? { background: '#e6f4ff' } : undefined })}
            expandable={{
              expandedRowRender: (p) => <TypeDetail p={p} />,
              expandedRowKeys: openRows,
              onExpand: (isExp, p) =>
                setOpenRows((r) => (isExp ? [...r, p.type_no] : r.filter((x) => x !== p.type_no))),
            }}
          />
        )}
      </Drawer>
    </Ctx.Provider>
  );
};

/** The header button: opens the panel without a focused type. */
export const SfmTypeReferenceButton: React.FC = () => {
  const t = useT();
  const ref = useSfmTypeReference();
  if (!ref) return null;
  return (
    <Button size="small" onClick={() => ref.open()}>
      {t('sfm.ref.open')}
    </Button>
  );
};
