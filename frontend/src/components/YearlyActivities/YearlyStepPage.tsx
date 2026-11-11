/**
 * Workflow step 13 — Yearly Activities (owner, 2026-10-15). The yearly plan itself, with the question that decides whether the
 * step is finished: it is "done" only when the owner says so, because the list is long and is not completed in one sitting.
 * Adding or editing an activity afterwards reopens it (the server does that).
 */
import React from 'react';
import YearlyActivitiesTab from '../YearlyActivitiesTab';
import { YearlyDoneBar } from './YearlyDoneBar';

const YearlyStepPage: React.FC<{ calculationId: string }> = ({ calculationId }) => (
  <div>
    <YearlyDoneBar calculationId={calculationId} />
    <div id="yearly-plan-grid">
      <YearlyActivitiesTab calculationId={calculationId} gridMode />
    </div>
  </div>
);

export default YearlyStepPage;
