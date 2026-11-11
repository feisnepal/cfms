import React, { useCallback, useEffect, useState } from 'react';
import { Button, Checkbox, Modal, Space, Spin, Tag, message } from 'antd';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { toSurfaceId } from '../lib/calcSurface';
import { attributeComponentsApi, type AttributeComponent, type AttributeRunResult } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';

const STATE_COLOUR: Record<AttributeComponent['state'], string> = {
  up_to_date: 'green',
  out_of_date: 'orange',
  never: 'blue',
  unavailable: 'default',
};

/**
 * "Update attribute" -- the one command that refreshes whatever attribute components the forest has (raster analysis, SFM,
 * hazard & erosion; inventory is reported, its file is needed to re-process). Raster analysis is the same engine as the
 * Re-run Analysis button. A component that is not available is shown as such and never blocks the others.
 */
export function UpdateAttributeDialog({ calculationId, open, onClose }: { calculationId: string; open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const ne = i18n.language?.startsWith('ne');
  const navigate = useNavigate();
  const bump = useWorkspaceStore((s) => s.bumpGeometryVersion);
  const [items, setItems] = useState<AttributeComponent[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<Record<string, AttributeRunResult>>({});

  const load = useCallback(async () => {
    setItems(null);
    try {
      const list = await attributeComponentsApi.list(calculationId);
      setItems(list);
      // Everything that can run and is not already current is ticked.
      setPicked(list.filter((c) => c.can_run && c.state !== 'up_to_date').map((c) => c.key));
    } catch {
      setItems([]);
    }
  }, [calculationId]);

  useEffect(() => {
    if (open) {
      setResults({});
      void load();
    }
  }, [open, load]);

  const run = async () => {
    setRunning(true);
    try {
      const out = await attributeComponentsApi.run(calculationId, picked);
      setResults(out.results);
      setItems(out.components);
      const failed = Object.values(out.results).some((r) => !r.ok);
      if (failed) message.warning(t('attributeUpdate.partial'));
      else message.success(t('attributeUpdate.done'));
      bump(); // the unit layers (and their tables) reload with the new values
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t('attributeUpdate.title')}
      width={560}
      footer={
        <Space>
          <Button onClick={onClose}>{t('attributeUpdate.close')}</Button>
          <Button type="primary" onClick={run} loading={running} disabled={running || picked.length === 0}>
            {running ? t('attributeUpdate.running') : t('attributeUpdate.run')}
          </Button>
        </Space>
      }
    >
      <p>{t('attributeUpdate.intro')}</p>
      {items === null ? (
        <Spin />
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }} data-testid="attribute-components">
          {items.map((c) => {
            const r = results[c.key];
            const why = ne ? c.reason_ne : c.reason_en;
            return (
              <li key={c.key} style={{ display: 'flex', gap: 10, padding: '6px 0', alignItems: 'flex-start' }}>
                <Checkbox
                  disabled={!c.can_run || running}
                  checked={picked.includes(c.key)}
                  onChange={(e) => setPicked((p) => (e.target.checked ? [...p, c.key] : p.filter((k) => k !== c.key)))}
                />
                <span style={{ flex: 1 }}>
                  <strong>{ne ? c.label_ne : c.label_en}</strong>{' '}
                  <Tag color={STATE_COLOUR[c.state]}>{t(`attributeUpdate.state.${c.state}`)}</Tag>
                  {why && <div style={{ opacity: 0.75 }}>{why}</div>}
                  {c.open_step && (
                    <Button
                      size="small"
                      type="link"
                      style={{ paddingLeft: 0 }}
                      onClick={() => {
                        onClose();
                        navigate(`/calculations/${calculationId}?surface=${toSurfaceId('field', c.open_step)}`);
                      }}
                    >
                      {t('attributeUpdate.openStep')}
                    </Button>
                  )}
                  {r && !r.ok && !r.skipped && <div style={{ color: '#cf1322' }}>{r.error}</div>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
}
