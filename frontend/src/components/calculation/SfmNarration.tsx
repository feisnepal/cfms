/**
 * SfmNarration — the adaptive NE/EN methodology / findings / prescription prose
 * for the SFM section (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4).
 *
 * Three Collapse panels, NE by default with an EN toggle.
 */
import React, { useState } from 'react';
import { Collapse, Radio } from 'antd';
import { useT } from '../../i18n/hooks';
import type { SfmNarrationBlock } from '../../services/api';
import { SfmVarChip } from './SfmVarChip';

const PANEL_TOKEN: Record<string, string> = {
  methodology: 'sfm_methodology',
  findings: 'sfm_findings',
  prescription: 'sfm_prescription',
};

interface Props {
  narration: SfmNarrationBlock | null;
  lang: string;
}

export const SfmNarration: React.FC<Props> = ({ narration, lang }) => {
  const t = useT();
  const [show, setShow] = useState<'ne' | 'en'>(lang.startsWith('ne') ? 'ne' : 'en');

  if (!narration) {
    return null;
  }

  const pick = (b: { ne: string; en: string }): string => (show === 'ne' ? b.ne : b.en);

  const items = [
    { key: 'methodology', label: t('sfm.narration.methodology'), text: pick(narration.methodology) },
    { key: 'findings', label: t('sfm.narration.findings'), text: pick(narration.findings) },
    { key: 'prescription', label: t('sfm.narration.prescription'), text: pick(narration.prescription) },
  ].map((it) => ({
    ...it,
    label: (
      <span>
        {it.label}
        <SfmVarChip tokenKey={PANEL_TOKEN[it.key]} />
      </span>
    ),
  }));

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <b>{t('sfm.narration.heading')}</b>
        <Radio.Group
          size="small"
          value={show}
          onChange={(e) => setShow(e.target.value)}
        >
          <Radio.Button value="ne">नेपाली</Radio.Button>
          <Radio.Button value="en">EN</Radio.Button>
        </Radio.Group>
      </div>
      <Collapse
        defaultActiveKey={['methodology', 'findings', 'prescription']}
        items={items.map((it) => ({
          key: it.key,
          label: it.label,
          children: <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{it.text}</p>,
        }))}
      />
    </div>
  );
};

export default SfmNarration;
