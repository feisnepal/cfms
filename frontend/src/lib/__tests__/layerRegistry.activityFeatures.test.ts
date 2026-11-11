/**
 * The Activity Features layer used to call `/calculations/{id}/drawn-features` POST / PATCH / DELETE,
 * routes that never existed. It now calls the facade (YEARLY_ACTIVITIES plan §5.1).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LAYER_REGISTRY } from '../layerRegistry';

const source = LAYER_REGISTRY.activity_features.dataSource;
const point = { type: 'Point', coordinates: [85.05, 27.44] };

let fetchMock: ReturnType<typeof vi.fn>;

const reply = (status: number, body: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('activity_features data source', () => {
  it('create posts the facade body to /activity-features', async () => {
    fetchMock.mockResolvedValue(reply(200, { created_plan_line: true }));

    const result = await source.create!('calc-1', {
      type: 'Feature',
      geometry: point,
      properties: { potential_activity_id: 4, years: [1, 2], name: 'Nursery' },
    } as never);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/yearly-activities/calculations/calc-1/activity-features');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toMatchObject({
      potential_activity_id: 4,
      feature_type: 'point',
      years: [1, 2],
      name: 'Nursery',
    });
    expect(result).toEqual({ created_plan_line: true });
  });

  it('create refuses, without calling the server, when no activity was chosen', async () => {
    await expect(
      source.create!('calc-1', { type: 'Feature', geometry: point, properties: {} } as never),
    ).rejects.toThrow(/activity/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('a server refusal is thrown with its code, not swallowed', async () => {
    fetchMock.mockResolvedValue(reply(422, { detail: { code: 'YEAR_NOT_PLANNED', years: [4] } }));
    await expect(
      source.create!('calc-1', {
        type: 'Feature',
        geometry: point,
        properties: { potential_activity_id: 4, years: [4] },
      } as never),
    ).rejects.toThrow('YEAR_NOT_PLANNED');
  });

  it('update patches only the given fields to /activity-features/{id}', async () => {
    fetchMock.mockResolvedValue(reply(200, {}));
    await source.update!('calc-1', 'f-9', { properties: { name: 'Renamed' } } as never);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/yearly-activities/calculations/calc-1/activity-features/f-9');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body)).toEqual({ name: 'Renamed' });
  });

  it('delete calls the facade and reports a failure', async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { deleted: true }));
    await source.delete!('calc-1', 'f-9');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/yearly-activities/calculations/calc-1/activity-features/f-9');
    expect(init.method).toBe('DELETE');

    fetchMock.mockResolvedValueOnce(reply(404, { detail: 'Drawn feature not found' }));
    await expect(source.delete!('calc-1', 'gone')).rejects.toThrow('Drawn feature not found');
  });
});
