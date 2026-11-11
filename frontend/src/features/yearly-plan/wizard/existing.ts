import type { YearlyPlanLine } from '../../../services/api';
import type { ExistingLine } from './wizardMachine';

/** A plan line, as the wizard needs it: its id and version, the years it is planned in, whole-forest or not. */
export const lineToExisting = (line: YearlyPlanLine): ExistingLine => ({
  id: line.id,
  version: line.version,
  years: line.planned_years,
  wholeForest: line.assign_to_all_blocks,
});
