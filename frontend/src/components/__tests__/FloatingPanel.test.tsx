import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { FloatingPanel } from '../FloatingPanel';

function Host({ id = 'a', onClose = () => {}, start = { x: 20, y: 30 } }: { id?: string; onClose?: () => void; start?: { x: number; y: number } }) {
  const [pos, setPos] = useState(start);
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div style={{ position: 'relative', width: 800, height: 600 }}>
      <FloatingPanel
        title={`Panel ${id}`} position={pos} onPositionChange={setPos} collapsed={collapsed} onCollapsedChange={setCollapsed}
        onClose={onClose} testId={`panel-${id}`}
      >
        <div>body {id}</div>
      </FloatingPanel>
    </div>
  );
}

describe('FloatingPanel', () => {
  it('is placed where it is told', () => {
    render(<Host />);
    const el = screen.getByTestId('panel-a');
    expect(el.style.left).toBe('20px');
    expect(el.style.top).toBe('30px');
  });

  it('moves with the pointer when dragged by the header, and stops when released', () => {
    render(<Host />);
    const header = screen.getByTestId('panel-a-header');
    fireEvent.pointerDown(header, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(header, { clientX: 150, clientY: 140, pointerId: 1 });
    expect(screen.getByTestId('panel-a').style.left).toBe('70px');
    expect(screen.getByTestId('panel-a').style.top).toBe('70px');
    fireEvent.pointerUp(header, { pointerId: 1 });
    fireEvent.pointerMove(header, { clientX: 400, clientY: 400, pointerId: 1 });
    expect(screen.getByTestId('panel-a').style.left).toBe('70px');
  });

  it('a press on a header button does not start a drag', () => {
    render(<Host />);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Collapse' }), { clientX: 1, clientY: 1, pointerId: 3 });
    fireEvent.pointerMove(screen.getByTestId('panel-a-header'), { clientX: 99, clientY: 99, pointerId: 3 });
    expect(screen.getByTestId('panel-a').style.left).toBe('20px');
  });

  it('moves with the arrow keys', () => {
    render(<Host />);
    const header = screen.getByTestId('panel-a-header');
    fireEvent.keyDown(header, { key: 'ArrowRight' });
    fireEvent.keyDown(header, { key: 'ArrowDown' });
    expect(screen.getByTestId('panel-a').style.left).toBe('36px');
    expect(screen.getByTestId('panel-a').style.top).toBe('46px');
  });

  it('collapses to its header and expands again', () => {
    render(<Host />);
    expect(screen.getByText('body a')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(screen.queryByText('body a')).toBeNull();
    expect(screen.getByRole('button', { name: 'Expand' }).getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
    expect(screen.getByText('body a')).toBeTruthy();
  });

  it('asks to be closed', () => {
    const onClose = vi.fn();
    render(<Host onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('the panel touched last is on top', () => {
    render(
      <>
        <Host id="a" />
        <Host id="b" />
      </>,
    );
    const z = (id: string) => Number(screen.getByTestId(`panel-${id}`).style.zIndex);
    expect(z('b')).toBeGreaterThan(z('a'));
    fireEvent.pointerDown(screen.getByTestId('panel-a'), { pointerId: 4 });
    expect(z('a')).toBeGreaterThan(z('b'));
    fireEvent.pointerDown(screen.getByTestId('panel-b'), { pointerId: 5 });
    expect(z('b')).toBeGreaterThan(z('a'));
  });
});
