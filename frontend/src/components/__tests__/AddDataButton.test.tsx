import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AddDataButton from '../AddDataButton';

const getSchema = vi.fn();
const classifyUpload = vi.fn();
vi.mock('../../services/api', () => ({
  uploadApi: {
    getSchema: () => getSchema(),
    downloadWorkbook: vi.fn(),
    classifyUpload: (f: File) => classifyUpload(f),
  },
}));

const SCHEMA = {
  schema_version: '1.0',
  purposes: [
    { id: 'forest_boundary', label_en: 'Forest boundary', label_ne: '', kind: 'spatial', order: 0, layer_name: 'forest_boundary', name_aliases: ['boundary'], geometry_types: ['POLYGON'] },
  ],
};

const files = (...names: string[]) => names.map((n) => new File(['x'], n));
function dropOnWindow(list: File[], types: string[] = ['Files']) {
  const ev = new Event('drop', { bubbles: true, cancelable: true }) as any;
  ev.dataTransfer = { types, files: list };
  window.dispatchEvent(ev);
  return ev as Event;
}

describe('AddDataButton — drop anywhere', () => {
  beforeEach(() => {
    getSchema.mockResolvedValue(SCHEMA);
    classifyUpload.mockResolvedValue({ best: null });
  });

  it('opens Add data with the dropped files already in it, without clicking the button', async () => {
    render(<AddDataButton calculationId="c1" hasBoundary />);
    expect(screen.queryByText('Click or drag files here')).not.toBeInTheDocument();

    dropOnWindow(files('forest_boundary.kml'));
    expect(await screen.findByText('Click or drag files here')).toBeInTheDocument();
    expect(await screen.findByText('forest_boundary.kml')).toBeInTheDocument();
    expect(await screen.findByText('matched by name')).toBeInTheDocument();
  });

  it('shows the drop-anywhere hint while files are dragged over the page', async () => {
    render(<AddDataButton calculationId="c1" hasBoundary />);
    const ev = new Event('dragenter', { bubbles: true }) as any;
    ev.dataTransfer = { types: ['Files'] };
    window.dispatchEvent(ev);
    expect(await screen.findByTestId('drop-anywhere-overlay')).toBeInTheDocument();
  });

  it('ignores a drag that is not files (text, links)', async () => {
    render(<AddDataButton calculationId="c1" hasBoundary />);
    const ev = dropOnWindow([], ['text/plain']);
    await waitFor(() => expect(screen.queryByText('Click or drag files here')).not.toBeInTheDocument());
    expect((ev as any).defaultPrevented).toBe(false);
  });

  it('leaves a drop that another drop zone already took', async () => {
    render(<AddDataButton calculationId="c1" hasBoundary />);
    const ev = new Event('drop', { bubbles: true, cancelable: true }) as any;
    ev.dataTransfer = { types: ['Files'], files: files('a.kml') };
    ev.preventDefault();
    window.dispatchEvent(ev);
    await waitFor(() => expect(screen.queryByText('Click or drag files here')).not.toBeInTheDocument());
  });
});
