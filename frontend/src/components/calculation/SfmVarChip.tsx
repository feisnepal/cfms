/**
 * SfmVarChip — the in-context "grab this variable" affordance for the
 * Sustainable Forest Management tab (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P8).
 *
 * A small `{ }` ghost button next to a number / table / narration / map on the
 * SFM analysis page. Click copies `{{key}}`. Only template designers / super
 * admins see it — a CFUG viewer sees nothing extra, no layout shift.
 */
import React from 'react';
import { Button, Dropdown, message, Tooltip } from 'antd';
import { CodeOutlined, DownOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useCanDesignTemplates } from './HazardVarChip';

export { useCanDesignTemplates };

const copyToken = (
  key: string,
  t: (k: string, o?: Record<string, unknown>) => string,
): void => {
  navigator.clipboard.writeText(`{{${key}}}`).then(
    () => message.success(t('sfm.varChip.copied', { key })),
    () => message.error(t('sfm.varChip.copyFailed')),
  );
};

interface ChipProps {
  /** the variable key WITHOUT braces, e.g. "sfm_total_annual_harvest_m3" */
  tokenKey: string;
  size?: 'small' | 'middle';
}

/** Single copy-token chip. Renders nothing for non-designers. */
export const SfmVarChip: React.FC<ChipProps> = ({ tokenKey, size = 'small' }) => {
  const { t } = useTranslation();
  if (!useCanDesignTemplates()) return null;
  return (
    <Tooltip title={`{{${tokenKey}}}`}>
      <Button
        size={size}
        type="text"
        icon={<CodeOutlined />}
        onClick={(e) => {
          e.stopPropagation();
          copyToken(tokenKey, t);
        }}
        aria-label={t('sfm.varChip.copy', { key: tokenKey })}
        style={{ color: '#8c8c8c', padding: '0 4px', height: 20 }}
      />
    </Tooltip>
  );
};

interface MenuProps {
  /** ordered groups of keys — { labelKey, keys } */
  groups: { labelKey: string; keys: string[] }[];
}

/** "Copy variables ▾" — bulk-copies an ordered token block per group. */
export const SfmVarCopyMenu: React.FC<MenuProps> = ({ groups }) => {
  const { t } = useTranslation();
  if (!useCanDesignTemplates()) return null;

  const block = (keys: string[]) => keys.map((k) => `{{${k}}}`).join('\n');
  const all = groups.flatMap((g) => g.keys);

  const items = [
    {
      key: 'all',
      label: t('sfm.varChip.copyAll'),
      onClick: () => {
        navigator.clipboard.writeText(block(all));
        message.success(t('sfm.varChip.copiedN', { n: all.length }));
      },
    },
    { type: 'divider' as const },
    ...groups.map((g) => ({
      key: g.labelKey,
      label: t(g.labelKey),
      onClick: () => {
        navigator.clipboard.writeText(block(g.keys));
        message.success(t('sfm.varChip.copiedN', { n: g.keys.length }));
      },
    })),
  ];

  return (
    <Dropdown menu={{ items }} trigger={['click']}>
      <Button size="small" icon={<CodeOutlined />}>
        {t('sfm.varChip.menu')} <DownOutlined />
      </Button>
    </Dropdown>
  );
};

export default SfmVarChip;
