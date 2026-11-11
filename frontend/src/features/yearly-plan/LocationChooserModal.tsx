import React, { useEffect, useState } from 'react';
import { Modal, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { yearlyActivitiesApi, yearlyPlanApi, type PlanUnit, type YearlyPlanLine } from '../../services/api';
import BlockSubAreaSelector from '../../components/YearlyActivities/BlockSubAreaSelector';
import { planSaveErrorMessage } from './planErrors';

interface Props {
  calculationId: string;
  /** the plan line whose location is being chosen; null = closed */
  line: YearlyPlanLine | null;
  onClose: () => void;
  /** the location was saved: the host re-reads the plan */
  onSaved: () => void;
}

/**
 * Where an activity applies — the whole forest, or chosen blocks / sub-areas (plan §4.4b) — for the yearly-activities
 * pages. Choosing "all blocks" also sets the line's whole-forest flag, which is what the plan table and the plan
 * check read; the older spatial assignment is kept beside it for the exports that read that.
 *
 * The drawn places of an activity are not here: they are drawn on the map.
 */
export const LocationChooserModal: React.FC<Props> = ({ calculationId, line, onClose, onSaved }) => {
  const t = useT();
  const [blocks, setBlocks] = useState<PlanUnit[]>([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [allBlocks, setAllBlocks] = useState(true);
  const [selectedBlocks, setSelectedBlocks] = useState<string[]>([]);
  const [selectedSubAreas, setSelectedSubAreas] = useState<string[]>([]);

  // when a line is given: read the forest's units and what is assigned now, then open
  useEffect(() => {
    if (!line) {
      setOpen(false);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      const [unitList, assignments] = await Promise.all([
        yearlyPlanApi.getUnits(calculationId).catch(() => [] as PlanUnit[]),
        yearlyActivitiesApi.getSpatialAssignments(line.id).catch(() => [] as any[]),
      ]);
      if (cancelled) return;
      setBlocks(unitList);
      if (line.assign_to_all_blocks || assignments.some((a: any) => a.assignment_type === 'all_blocks')) {
        setAllBlocks(true);
        setSelectedBlocks([]);
        setSelectedSubAreas([]);
      } else {
        setAllBlocks(false);
        setSelectedBlocks(assignments.filter((a: any) => a.block_id && !a.sub_area_id).map((a: any) => a.block_id));
        setSelectedSubAreas(assignments.filter((a: any) => a.sub_area_id).map((a: any) => a.sub_area_id));
      }
      setOpen(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [calculationId, line]);

  const change = (type: 'all' | 'block' | 'sub_area', id?: string, checked?: boolean) => {
    if (type === 'all') {
      setAllBlocks(Boolean(checked));
      if (checked) {
        setSelectedBlocks([]);
        setSelectedSubAreas([]);
      }
    } else if (type === 'block' && id) {
      setAllBlocks(false);
      if (checked) {
        setSelectedBlocks((prev) => (prev.includes(id) ? prev : [...prev, id]));
      } else {
        setSelectedBlocks((prev) => prev.filter((b) => b !== id));
        const inBlock = blocks.find((b) => b.block_id === id)?.sub_areas?.map((sa) => sa.id) || [];
        setSelectedSubAreas((prev) => prev.filter((saId) => !inBlock.includes(saId)));
      }
    } else if (type === 'sub_area' && id) {
      setAllBlocks(false);
      const blockId = blocks.find((b) => b.sub_areas.some((sa) => sa.id === id))?.block_id;
      if (checked) {
        if (blockId && !selectedBlocks.includes(blockId)) setSelectedBlocks((prev) => [...prev, blockId]);
        setSelectedSubAreas((prev) => (prev.includes(id) ? prev : [...prev, id]));
      } else {
        setSelectedSubAreas((prev) => prev.filter((s) => s !== id));
        if (blockId) {
          const remaining = blocks.find((b) => b.block_id === blockId)?.sub_areas?.filter((sa) => selectedSubAreas.includes(sa.id) && sa.id !== id) || [];
          if (remaining.length === 0) setSelectedBlocks((prev) => prev.filter((b) => b !== blockId));
        }
      }
    }
  };

  const save = async () => {
    if (!line) return;
    setSaving(true);
    try {
      // replace the earlier assignments with the chosen ones
      for (const existing of await yearlyActivitiesApi.getSpatialAssignments(line.id)) {
        await yearlyActivitiesApi.deleteSpatialAssignment(line.id, existing.id);
      }
      if (allBlocks) {
        await yearlyActivitiesApi.createSpatialAssignment(line.id, { assignment_type: 'all_blocks' });
      } else {
        // a block on its own only when no sub-area of it is chosen
        for (const blockId of selectedBlocks) {
          const inBlock = blocks.find((b) => b.block_id === blockId)?.sub_areas?.map((sa) => sa.id) || [];
          if (selectedSubAreas.filter((saId) => inBlock.includes(saId)).length === 0) {
            await yearlyActivitiesApi.createSpatialAssignment(line.id, { block_id: blockId, assignment_type: 'block' });
          }
        }
        for (const subAreaId of selectedSubAreas) {
          const unit = blocks.find((b) => b.sub_areas.some((sa) => sa.id === subAreaId));
          if (unit) {
            await yearlyActivitiesApi.createSpatialAssignment(line.id, {
              block_id: unit.block_id,
              sub_area_id: subAreaId,
              assignment_type: 'sub_area',
            });
          }
        }
      }
      // the whole-forest flag is what the plan table and the plan check read
      await yearlyActivitiesApi.updateProposedActivity(line.id, { assign_to_all_blocks: allBlocks });
      message.success(t('yearlyActivities.tab.msgAssignmentSaved'));
      onSaved();
      onClose();
    } catch (error) {
      message.error(planSaveErrorMessage(error, t));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t('yearlyActivities.tab.selectBlockSubArea')}
      open={open}
      onOk={() => void save()}
      onCancel={onClose}
      confirmLoading={saving}
      width={400}
      okText={t('yearlyPlan.wizard.save')}
      destroyOnHidden
    >
      <BlockSubAreaSelector
        blocks={blocks}
        selectedAllBlocks={allBlocks}
        selectedBlocks={selectedBlocks}
        selectedSubAreas={selectedSubAreas}
        onChange={change}
      />
    </Modal>
  );
};

export default LocationChooserModal;
