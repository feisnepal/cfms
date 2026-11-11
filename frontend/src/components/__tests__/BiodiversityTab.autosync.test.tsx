/** Opening the Biodiversity tab lists the field inventory's species automatically (no confirmation screen). */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';

vi.mock('../../i18n/hooks', () => ({ useT: () => (key: string) => key }));
vi.mock('../../i18n/numberFormat', () => ({ formatNumber: (n: number) => String(n) }));
vi.mock('../../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

import api from '../../services/api';
import BiodiversityTab from '../BiodiversityTab';

const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  mock.get.mockResolvedValue({ data: { species: [], items: [], total: 0, categories: {}, selected: [] } });
});

describe('BiodiversityTab - automatic species from the inventory', () => {
  it('asks the server to list the inventory species once on open, and tells the shell when it added some', async () => {
    mock.post.mockResolvedValue({ data: { added: 16, created: 10 } });
    const changed = vi.fn();
    render(<BiodiversityTab calculationId="C1" view="data" onStepDataChanged={changed} />);
    await waitFor(() => expect(mock.post).toHaveBeenCalledWith('/api/biodiversity/calculations/C1/species/sync-from-inventory'));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  });

  it('does not touch the shell when nothing was added (no inventory, or already listed)', async () => {
    mock.post.mockResolvedValue({ data: { up_to_date: true } });
    const changed = vi.fn();
    render(<BiodiversityTab calculationId="C1" view="data" onStepDataChanged={changed} />);
    await waitFor(() => expect(mock.post).toHaveBeenCalledTimes(1));
    expect(changed).not.toHaveBeenCalled();
  });

  it('still opens when the sync fails', async () => {
    mock.post.mockRejectedValue(new Error('boom'));
    render(<BiodiversityTab calculationId="C1" view="data" />);
    await waitFor(() => expect(mock.post).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mock.get).toHaveBeenCalled());
  });
});
