/**
 * reportApi on the wire — the request the endpoint actually receives.
 *
 * WORKSPACE_FLOW_NAV_PLAN D5. `POST /report/{id}/generate` has a body model of
 * `{metadata, sections}` and one query parameter, `include_images`. The client
 * used to post `{metadata, selected_sections, include_images}` as a single JSON
 * body, and Pydantic ignored the two keys it did not know:
 *
 *   - `selected_sections` was dropped, so `sections` fell back to its default of
 *     *every* section. The section picker appeared to work and had no effect:
 *     the document always came out complete.
 *   - `include_images` was dropped, so `include_images` kept its default of
 *     `true`. The images toggle appeared to work and had no effect.
 *
 * Neither was visible in the UI. The report simply appeared, wrong, and the only
 * way to notice was to read the document. So these are asserted against the
 * axios call rather than against the buttons that trigger it.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * The client is built with `axios.create`, so the mock has to be an instance,
 * not a bag of methods on the default export.
 */
const h = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  calls: [] as any[][],
}));

vi.mock('axios', () => {
  const instance: any = {
    get: (...a: any[]) => {
      h.calls.push(['get', ...a]);
      return h.get(...a);
    },
    post: (...a: any[]) => {
      h.calls.push(['post', ...a]);
      return h.post(...a);
    },
    put: (...a: any[]) => {
      h.calls.push(['put', ...a]);
      return h.put(...a);
    },
    patch: (...a: any[]) => {
      h.calls.push(['patch', ...a]);
      return h.patch(...a);
    },
    delete: (...a: any[]) => {
      h.calls.push(['delete', ...a]);
      return h.delete(...a);
    },
    defaults: { headers: { common: {} } },
    interceptors: {
      request: { use: () => {} },
      response: { use: () => {} },
    },
  };
  return { default: { create: () => instance, ...instance } };
});

const { reportApi, forestMetadataApi } = await import('../api');

/** The single call made by the test just run, as [url, body, config]. */
const call = (): any[] => h.calls[h.calls.length - 1].slice(1);

beforeEach(() => {
  h.calls.length = 0;
  h.get.mockReset();
  h.post.mockReset();
  h.put.mockReset();
  h.post.mockResolvedValue({ data: { job_id: 'job-1' } });
});

describe('generateReport', () => {
  it('puts the chosen sections in the body, under the key the endpoint reads', async () => {
    await reportApi.generateReport('calc-1', ['1', '3'], false);

    const [url, body, config] = call();
    expect(url).toBe('/api/report/calc-1/generate');
    expect(body).toEqual({ sections: ['1', '3'] });
    // The old name. Pydantic dropped it, and the report silently contained
    // every section the document has.
    expect(body).not.toHaveProperty('selected_sections');
    expect(config?.params).toEqual({ include_images: false });
  });

  it('carries the image flag as a query parameter, not in the body', async () => {
    await reportApi.generateReport('calc-1', ['1'], true);
    const [url, body, config] = call();

    expect(url).not.toContain('include_images');
    expect(body).not.toHaveProperty('include_images');
    expect(config?.params).toEqual({ include_images: true });
  });

  it('sends no metadata at all, so the server reads the stored record', async () => {
    // The endpoint resolves the record itself (saved > derived > posted). A
    // posted blob would be a second, unvalidated source of truth for exactly
    // the fields the record exists to hold.
    await reportApi.generateReport('calc-1', ['1'], true);
    expect(call()[1]).not.toHaveProperty('metadata');
  });

  it('sends an empty section list rather than omitting it', async () => {
    // Omitting the key lets the server default to "all sections", so a
    // deliberate "none" has to go out as one.
    await reportApi.generateReport('calc-1', [], false);
    expect(call()[1]).toEqual({ sections: [] });
  });
});

describe('forestMetadataApi', () => {
  it('reads the record from the calculation', async () => {
    h.get.mockResolvedValue({ data: { forest_name: 'Kali Prasad forest', persisted: false } });
    const res = await forestMetadataApi.get('calc-1');
    expect(call()[0]).toBe('/api/calculations/calc-1/forest-metadata');
    expect(res.forest_name).toBe('Kali Prasad forest');
    expect(res.persisted).toBe(false);
  });

  it('sends every field, blanks included, so a value can be cleared', async () => {
    // Omitting an untouched field would leave the stored value in place and
    // make "clear this" unexpressible from the UI.
    h.put.mockResolvedValue({ data: { message: 'saved' } });
    await forestMetadataApi.save('calc-1', { forest_name: 'X', cf_national_code: '' } as any);

    const [url, body] = call();
    expect(url).toBe('/api/calculations/calc-1/forest-metadata');
    expect(body).toEqual({ forest_name: 'X', cf_national_code: '' });
  });
});
