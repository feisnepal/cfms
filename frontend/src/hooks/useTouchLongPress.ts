import { useRef, useCallback } from 'react';

interface UseTouchLongPressOptions {
  onLongPress: (e: React.TouchEvent) => void;
  delay?: number;
}

export function useTouchLongPress({ onLongPress, delay = 500 }: UseTouchLongPressOptions) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const touchStartPos = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    timerRef.current = setTimeout(() => {
      onLongPress(e);
    }, delay);
    touchStartPos.current = {
      x: e.touches[0].clientX,
      y: e.touches[0].clientY,
    };
  }, [onLongPress, delay]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    const dx = Math.abs(e.touches[0].clientX - touchStartPos.current.x);
    const dy = Math.abs(e.touches[0].clientY - touchStartPos.current.y);
    if (dx > 10 || dy > 10) {
      clearTimeout(timerRef.current);
    }
  }, []);

  const onTouchEnd = useCallback(() => {
    clearTimeout(timerRef.current);
  }, []);

  return { onTouchStart, onTouchMove, onTouchEnd };
}
