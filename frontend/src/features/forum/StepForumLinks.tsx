/** StepForumLinks - "Ask about this step" and the number already asked, shown in the workflow header. Opens the forum in a new tab so the workspace (and its map) stays as it is. */
import React from 'react';
import { MessageCircleQuestion } from 'lucide-react';
import { useT } from '../../i18n/hooks';
import { useStepCounts } from './useStepCounts';

const StepForumLinks: React.FC<{ stepId: string }> = ({ stepId }) => {
  const t = useT();
  const counts = useStepCounts();
  const asked = counts[stepId]?.questions ?? 0;
  const id = encodeURIComponent(stepId);
  return (
    <span className="inline-flex items-center gap-2 text-[11px] whitespace-nowrap">
      <a href={`/forum/ask?step=${id}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-green-700 hover:underline" title={t('forum.askAboutStepHint')}>
        <MessageCircleQuestion size={12} aria-hidden="true" />
        {t('forum.askAboutStep')}
      </a>
      {asked > 0 && (
        <a href={`/forum?step=${id}`} target="_blank" rel="noopener noreferrer" className="text-gray-500 hover:underline">
          {t('forum.askedCount', { count: asked })}
        </a>
      )}
    </span>
  );
};

export default StepForumLinks;
