/**
 * HazardVarChip — the in-context "grab this variable" affordance
 * (HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P4).
 *
 * A small `{ }` ghost button rendered next to a map / table / chart / narration
 * / number on the Hazard & Erosion analysis page. Hover shows the descriptive
 * token; click copies `{{key}}` to the clipboard. Only template designers /
 * super admins see it — a CFUG viewer sees nothing extra, no layout shift.
 */
import React, { useContext } from 'react';
import { Button, Dropdown, message, Tooltip } from 'antd';
import { CodeOutlined, DownOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { AuthContext } from '../../contexts/AuthContext';

/** True only for template designers / super admins. Safe outside an
 *  AuthProvider (returns false) so the chip never crashes a preview/export. */
export const useCanDesignTemplates = (): boolean => {
  const ctx = useContext(AuthContext);
  const role = ctx?.user?.role;
  return role === 'super_admin' || role === 'template_designer';
};

const copyToken = (key: string, t: (k: string, o?: Record<string, unknown>) => string): void => {
  navigator.clipboard.writeText(`{{${key}}}`).then(
    () => message.success(t('hazardErosion.varChip.copied', { key })),
    () => message.error(t('hazardErosion.varChip.copyFailed')),
  );
};

interface ChipProps {
  /** the variable key WITHOUT braces, e.g. "hazard_landslide_prone_area_pct" */
  tokenKey: string;
  size?: 'small' | 'middle';
}

/** Single copy-token chip. Renders nothing for non-designers. */
export const HazardVarChip: React.FC<ChipProps> = ({ tokenKey, size = 'small' }) => {
  const { t } = useTranslation();
  const canDesign = useCanDesignTemplates();
  if (!canDesign) return null;
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
        aria-label={t('hazardErosion.varChip.copy', { key: tokenKey })}
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
export const HazardVarCopyMenu: React.FC<MenuProps> = ({ groups }) => {
  const { t } = useTranslation();
  const canDesign = useCanDesignTemplates();
  if (!canDesign) return null;

  const block = (keys: string[]) => keys.map((k) => `{{${k}}}`).join('\n');
  const all = groups.flatMap((g) => g.keys);

  const items = [
    {
      key: 'all',
      label: t('hazardErosion.varChip.copyAll'),
      onClick: () => {
        navigator.clipboard.writeText(block(all));
        message.success(t('hazardErosion.varChip.copiedN', { n: all.length }));
      },
    },
    { type: 'divider' as const },
    ...groups.map((g) => ({
      key: g.labelKey,
      label: t(g.labelKey),
      onClick: () => {
        navigator.clipboard.writeText(block(g.keys));
        message.success(t('hazardErosion.varChip.copiedN', { n: g.keys.length }));
      },
    })),
  ];

  return (
    <Dropdown menu={{ items }} trigger={['click']}>
      <Button size="small" icon={<CodeOutlined />}>
        {t('hazardErosion.varChip.menu')} <DownOutlined />
      </Button>
    </Dropdown>
  );
};

export default HazardVarChip;
