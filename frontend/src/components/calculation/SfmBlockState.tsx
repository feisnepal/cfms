/**
 * What a block is before (or instead of) a forest type (owner, 2026-10-06):
 *  - classified          forest land, 5+ sample plots: shows the type
 *  - provisional         forest land, 1-4 plots: the type, marked provisional
 *  - inventory_missing   forest land, no plots: NO type; the plan cannot be accepted
 *  - non_forest          grassland / rangeland / river / water / snow: no type, no plots expected
 */
import React from 'react';
import { Tag } from 'antd';
import { useT } from '../../i18n/hooks';
import type { SfmBlock } from '../../services/api';
import { SfmTypeTag, type SfmTypeBlockContext } from './SfmTypeTag';

type Props = Pick<SfmBlock, 'state' | 'plot_count' | 'land_class' | 'estimate_type_no'> & {
  typeNo: number | null;
  block?: SfmTypeBlockContext;
};

export const SfmBlockState: React.FC<Props> = ({ state, plot_count, land_class, estimate_type_no, typeNo, block }) => {
  const t = useT();
  if (state === 'non_forest') {
    return (
      <Tag data-testid="sfm-state-non-forest">
        {t('sfm.state.nonForest')} · {t(`sfm.landClass.${land_class}`, land_class)}
      </Tag>
    );
  }
  if (state === 'inventory_missing' || typeNo == null) {
    return (
      <span data-testid="sfm-state-missing">
        <Tag color="red">{t('sfm.state.inventoryMissing')}</Tag>
        {estimate_type_no != null && (
          <span style={{ color: '#888', fontSize: 11 }}>
            {t('sfm.state.estimate')}: {t('sfm.typeNo', { n: estimate_type_no })}
          </span>
        )}
      </span>
    );
  }
  return (
    <span>
      <SfmTypeTag n={typeNo} block={block} />
      {state === 'provisional' && (
        <Tag color="orange" style={{ marginInlineStart: 6 }} data-testid="sfm-state-provisional">
          {t('sfm.state.provisional', { n: plot_count })}
        </Tag>
      )}
    </span>
  );
};

export default SfmBlockState;
