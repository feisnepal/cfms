/**
 * AccessibleModal — focus trap + restoration + Escape-to-close (Phase 3).
 * aria-modal dialog with focus management for the calculation page.
 */
import { useEffect, useRef } from 'react';

interface AccessibleModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  ariaLabelledBy?: string;
}

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export const AccessibleModal: React.FC<AccessibleModalProps> = ({
  open,
  onClose,
  title,
  children,
  ariaLabelledBy,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;

    previousFocus.current = document.activeElement as HTMLElement;
    setTimeout(() => {
      const focusable = modalRef.current?.querySelector(FOCUSABLE_SELECTOR) as HTMLElement | null;
      focusable?.focus();
    }, 100);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Tab' && modalRef.current) {
        const focusableElements = modalRef.current.querySelectorAll(FOCUSABLE_SELECTOR);
        const first = focusableElements[0] as HTMLElement;
        const last = focusableElements[focusableElements.length - 1] as HTMLElement;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocus.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay"
      role="presentation"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={ariaLabelledBy || 'modal-title'}
        className="modal-content"
      >
        <h2 id={ariaLabelledBy || 'modal-title'} className="sr-only">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
};

export default AccessibleModal;
