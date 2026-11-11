/** Block/sub-area selector — checkbox list for filtering which blocks/sub-areas appear on the activity map. */
import React from 'react';
import { Checkbox, List, Tooltip } from 'antd';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';

interface BlockSubAreaSelectorProps {
  blocks: Array<{
    block_id: string;
    block_name: string;
    sub_areas: Array<{
      id: string;
      name: string;
      category: string;
    }>;
  }>;
  selectedAllBlocks: boolean;
  selectedBlocks: string[];
  selectedSubAreas: string[];
  onChange: (type: 'all' | 'block' | 'sub_area', id?: string, checked?: boolean) => void;
}

const BlockSubAreaSelector: React.FC<BlockSubAreaSelectorProps> = ({
  blocks,
  selectedAllBlocks,
  selectedBlocks,
  selectedSubAreas,
  onChange,
}) => {
  const t = useT();

  const handleAllBlocksChange = (checked: boolean) => {
    onChange('all', undefined, checked);
  };

  const handleBlockChange = (blockId: string, checked: boolean) => {
    if (checked) {
      onChange('block', blockId, true);
    } else {
      const block = blocks.find(b => b.block_id === blockId);
      if (block?.sub_areas?.length) {
        const subAreaIdsInBlock = block.sub_areas.map(sa => sa.id);
        const otherSubAreasChecked = selectedSubAreas.filter(
          saId => !subAreaIdsInBlock.includes(saId)
        );
        if (otherSubAreasChecked.length > 0) {
          onChange('block', blockId, false);
        } else {
          onChange('all', undefined, true);
        }
      } else {
        onChange('all', undefined, true);
      }
    }
  };

  const handleSubAreaChange = (blockId: string, subAreaId: string, checked: boolean) => {
    if (checked) {
      onChange('sub_area', subAreaId, true);
    } else {
      onChange('sub_area', subAreaId, false);
    }
  };

  const isBlockChecked = (blockId: string) => {
    const block = blocks.find(b => b.block_id === blockId);
    if (!block) return false;
    
    const subAreasInBlock = block.sub_areas?.map(sa => sa.id) || [];
    const checkedSubAreasInBlock = selectedSubAreas.filter(saId => subAreasInBlock.includes(saId));
    
    return selectedBlocks.includes(blockId) || checkedSubAreasInBlock.length > 0;
  };

  if (!blocks.length) {
    return <span style={{ color: '#999' }}>{t('yearlyActivities.selector.noBlocks')}</span>;
  }

  return (
    <div style={{ maxHeight: '250px', overflowY: 'auto', minWidth: '280px' }}>
      <Checkbox
        checked={selectedAllBlocks}
        onChange={(e) => handleAllBlocksChange(e.target.checked)}
        style={{ marginBottom: '12px', display: 'block' }}
      >
        <strong>{t('yearlyActivities.selector.allBlocks')}</strong>
      </Checkbox>

      {!selectedAllBlocks && (
        <List
          size="small"
          dataSource={blocks}
          renderItem={(block) => {
            const blockIsChecked = isBlockChecked(block.block_id);
            const subAreasInBlock = block.sub_areas || [];
            const checkedSubAreasInBlock = subAreasInBlock.filter(
              sa => selectedSubAreas.includes(sa.id)
            );
            
            return (
              <List.Item style={{ padding: '4px 0', display: 'block' }}>
                <Checkbox
                  checked={blockIsChecked}
                  onChange={(e) => handleBlockChange(block.block_id, e.target.checked)}
                  style={{ marginBottom: subAreasInBlock.length > 0 ? '4px' : '0' }}
                >
                  <strong>{block.block_name}</strong>
                </Checkbox>

                {subAreasInBlock.length > 0 && (
                  <List
                    size="small"
                    style={{ marginLeft: '20px' }}
                    dataSource={subAreasInBlock}
                    renderItem={(subArea) => {
                      const isChecked = selectedSubAreas.includes(subArea.id);
                      return (
                        <List.Item style={{ padding: '2px 0' }}>
                          <Checkbox
                            checked={isChecked}
                            onChange={(e) => handleSubAreaChange(block.block_id, subArea.id, e.target.checked)}
                          >
                            <span>
                              {subArea.name}{' '}
                              <Tooltip title={t('yearlyActivities.selector.locatedIn', { block: block.block_name })}>
                                <span style={{ color: '#888', fontSize: '11px' }}>
                                  ({block.block_name})
                                </span>
                              </Tooltip>
                            </span>
                          </Checkbox>
                        </List.Item>
                      );
                    }}
                  />
                )}
                
                {checkedSubAreasInBlock.length > 0 && (
                  <div style={{ marginLeft: '20px', fontSize: '11px', color: '#1890ff', marginTop: '2px' }}>
                    ✓ {t('yearlyActivities.selector.subAreasSelected', { count: formatNumber(checkedSubAreasInBlock.length) })}
                  </div>
                )}
              </List.Item>
            );
          }}
        />
      )}
    </div>
  );
};

export default BlockSubAreaSelector;