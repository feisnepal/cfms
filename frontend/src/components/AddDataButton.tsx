/**
 * The persistent "+ Add data" trigger (UNIFIED_UPLOAD_PLAN.md §4.6).
 *
 * Drop this anywhere a user should be able to add forest data — the workspace
 * toolbar, an empty-forest state, a data tab. It owns the open/closed state and
 * renders {@link AddDataDialog}, which runs the imports and shows their report
 * in place (UP-4.3).
 */

import { useCallback, useEffect, useState } from 'react';
import { Button } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useT } from '../i18n/hooks';
import AddDataDialog from './AddDataDialog';

interface AddDataButtonProps {
  calculationId: string;
  hasBoundary: boolean;
  /** antd Button type — default `primary`. */
  buttonType?: 'primary' | 'default' | 'dashed' | 'text' | 'link';
  size?: 'small' | 'middle' | 'large';
  block?: boolean;
}

export default function AddDataButton({
  calculationId,
  hasBoundary,
  buttonType = 'primary',
  size = 'middle',
  block = false,
}: AddDataButtonProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [dropped, setDropped] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);

  // Dropping files anywhere on the workspace opens "Add data" with them already in it: nobody should have to open the dialog first.
  // Ignored while a dialog is open, and when something else (a layer panel drop zone) already took the drop.
  const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
  const dialogOpen = useCallback(() => open || !!document.querySelector('.ant-modal-wrap:not([style*="display: none"])'), [open]);
  useEffect(() => {
    let depth = 0;
    const onEnter = (e: DragEvent) => {
      if (!hasFiles(e) || dialogOpen()) return;
      depth += 1;
      setDragging(true);
    };
    const onLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const onOver = (e: DragEvent) => {
      if (hasFiles(e) && !dialogOpen()) e.preventDefault(); // allow the drop
    };
    const onDrop = (e: DragEvent) => {
      depth = 0;
      setDragging(false);
      if (!hasFiles(e) || e.defaultPrevented) return; // not files, or a drop zone of its own already took them
      if (dialogOpen()) return;
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (!files.length) return;
      e.preventDefault();
      setDropped(files);
      setOpen(true);
    };
    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('dragover', onOver);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('drop', onDrop);
    };
  }, [dialogOpen]);

  // A file picked elsewhere (the sample plots layer's "Import sample plots") enters Add data the same way a dropped one does.
  useEffect(() => {
    const onFiles = (e: Event) => {
      const files = (e as CustomEvent<{ files?: File[] }>).detail?.files ?? [];
      if (!files.length) return;
      setDropped(files);
      setOpen(true);
    };
    window.addEventListener('add-data-files', onFiles);
    return () => window.removeEventListener('add-data-files', onFiles);
  }, []);

  return (
    <>
      <Button
        type={buttonType}
        size={size}
        block={block}
        icon={<PlusOutlined />}
        onClick={() => setOpen(true)}
      >
        {t('addData.button')}
      </Button>
      <AddDataDialog
        open={open}
        calculationId={calculationId}
        hasBoundary={hasBoundary}
        onClose={() => setOpen(false)}
        initialFiles={dropped}
        onInitialFilesTaken={() => setDropped([])}
      />
      {dragging && (
        <div
          className="fixed inset-0 z-[9998] flex items-center justify-center bg-blue-500/10 border-4 border-dashed border-blue-400 pointer-events-none"
          data-testid="drop-anywhere-overlay"
        >
          <div className="rounded bg-white px-6 py-4 text-lg font-medium text-blue-700 shadow">{t('addData.dropAnywhere')}</div>
        </div>
      )}
    </>
  );
}
