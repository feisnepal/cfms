/**
 * BoundaryPreviewContext — a single, app-wide surface for the forest-boundary
 * overlap & gap preview.  Any boundary-establishing / reshaping action (file
 * import, point-file, direct upload, on-screen digitize, boundary edit) calls
 * `reviewBoundary(...)` when a save endpoint reports `needs_overlap_review`
 * (or a pre-flight `previewBoundaryOverlap` finds relations).  The provider
 * renders ONE `BoundaryOverlapPreviewPanel` modal and, once the user Accepts /
 * Includes / files a dispute, invokes the caller's callbacks so it can navigate
 * or refresh around the (new or kept) calculation.
 */
import { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Modal } from 'antd';
import type { Geometry } from 'geojson';
import BoundaryOverlapPreviewPanel, {
  BoundaryResolutionResult,
} from '../components/BoundaryOverlapPreviewPanel';
import { useT } from '../i18n/hooks';

export type ReviewRequest = {
  geometry: Geometry
  forestName: string
  method: 'upload' | 'points' | 'digitize' | string
  /** Present when accepting/include on an EXISTING calculation (edit/reshape). */
  calculationId?: string
  /** Called after the user resolves (Accept / Include / Dispute); receives the
   *  resulting calculation id (new or kept) so the caller can navigate/refresh. */
  onResolved?: (result: BoundaryResolutionResult) => void
  /** Called when the user cancels (or the preview errors and is dismissed). */
  onCancelled?: () => void
  /** Called when the user picks "Edit manually". */
  onEdit?: (geometry: Geometry) => void
}

type BoundaryPreviewContextValue = {
  reviewBoundary: (req: ReviewRequest) => void
}

const BoundaryPreviewContext = createContext<BoundaryPreviewContextValue | null>(null)

export function useBoundaryPreview(): BoundaryPreviewContextValue {
  const ctx = useContext(BoundaryPreviewContext)
  if (!ctx) {
    throw new Error('useBoundaryPreview must be used within <BoundaryPreviewProvider>')
  }
  return ctx
}

export function BoundaryPreviewProvider({ children }: { children: ReactNode }) {
  const t = useT()
  const [req, setReq] = useState<ReviewRequest | null>(null)

  const close = useCallback(() => {
    setReq((cur) => {
      cur?.onCancelled?.()
      return null
    })
  }, [])

  const reviewBoundary = useCallback((next: ReviewRequest) => {
    setReq(next)
  }, [])

  return (
    <BoundaryPreviewContext.Provider value={{ reviewBoundary }}>
      {children}
      {req
        ? createPortal(
            <Modal
              open
              onCancel={close}
              footer={null}
              width={1100}
              title={t('boundaryPreview.title')}
              centered
              destroyOnHidden
            >
              <BoundaryOverlapPreviewPanel
                geometry={req.geometry}
                forestName={req.forestName}
                method={req.method}
                calculationId={req.calculationId}
                onCancel={close}
                onDone={(result?: BoundaryResolutionResult) => {
                  setReq(null)
                  if (result) req.onResolved?.(result)
                  else req.onResolved?.({ id: req.calculationId || '' })
                }}
                onEdit={(geometry: Geometry) => {
                  setReq(null)
                  req.onEdit?.(geometry)
                }}
              />
            </Modal>,
            document.body,
          )
        : null}
    </BoundaryPreviewContext.Provider>
  )
}
