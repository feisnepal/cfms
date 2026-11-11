/**
 * Render with the providers a component needs in production but not in a unit
 * test.
 *
 * Added for DBH_SSOT P3. The DBH class list now comes from the API through
 * `useDbhClassConfig`, which is a react-query hook, so any test that renders a
 * component using it needs a `QueryClientProvider`. Without this the failure is
 * `No QueryClient set, use QueryClientProvider to set one` -- thrown from inside
 * a render rather than from a missing mock, which is a slow thing to diagnose.
 *
 * The client here has retries off. In a test environment the network is not
 * there, and three retries per query turns a 4-second assertion into a
 * 30-second one; it also produces the `[i18n] Overlay fetch attempt 1/3 failed`
 * noise that hides real output.
 *
 * That noise comes from `src/test/setup.ts`, not from react-query, so silencing
 * react-query would not remove it. It is left alone rather than suppressed at the
 * source: a fetch failing in a test is usually the test's own missing mock, and
 * making that quiet would hide the clue.
 *
 * What this does *not* do is supply class data. A component using the hook under
 * this provider gets an empty class list, which is the documented behaviour when
 * the API is unreachable, and it renders empty tables rather than throwing. Tests
 * that assert on class-table content should stub the API layer or the hook, as
 * `fieldInventoryResultsTables.test.tsx` does -- stubbing at the network keeps the
 * real mapper in the path.
 */
import React from 'react';
import { render, RenderOptions, RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  });
}

export function renderWithProviders(
  ui: React.ReactElement,
  options?: Omit<RenderOptions, 'wrapper'> & { queryClient?: QueryClient },
): RenderResult {
  const { queryClient = makeTestQueryClient(), ...rest } = options ?? {};
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return render(ui, { wrapper: Wrapper, ...rest });
}
