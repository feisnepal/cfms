import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { geometryQueryKey } from '../useGeometryVersion'

describe('useGeometryVersion / U02 geometry clock', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    useWorkspaceStore.setState({
      selectedFeatureId: null,
      geometryVersion: 0,
      dirty: false,
      uiMode: 'advanced',
      userRoles: [],
      syncStatus: 'synced',
      syncConflict: 'none',
      serverGeometryVersion: 0,
      mapCompositions: [],
      activeCompositionId: null,
    })
  })

  it('geometryQueryKey embeds calcId and current geometryVersion', () => {
    const key = geometryQueryKey('calc-1', 'sampling')
    expect(key).toEqual(['calc-1', 0, 'sampling'])
    useWorkspaceStore.getState().bumpGeometryVersion()
    expect(geometryQueryKey('calc-1', 'sampling')).toEqual(['calc-1', 1, 'sampling'])
  })

  it('bumpGeometryVersion increments the clock used by derived panes', () => {
    const sel = () => useWorkspaceStore.getState().geometryVersion
    expect(sel()).toBe(0)
    useWorkspaceStore.getState().bumpGeometryVersion()
    expect(sel()).toBe(1)
  })

  it('clean server bump is absorbed silently (no conflict flag)', () => {
    const s = useWorkspaceStore.getState()
    const r = s.reconcileVersion(4)
    expect(r.rejected).toBe(false)
    const after = useWorkspaceStore.getState()
    expect(after.geometryVersion).toBe(4)
    expect(after.syncConflict).toBe('none')
    expect(after.serverGeometryVersion).toBe(4)
  })

  it('dirty store rejects a server bump and raises stale_server (no 3-way merge)', () => {
    const s = useWorkspaceStore.getState()
    s.setDirty(true)
    const r = useWorkspaceStore.getState().reconcileVersion(7)
    expect(r.rejected).toBe(true)
    const after = useWorkspaceStore.getState()
    expect(after.syncConflict).toBe('stale_server')
    expect(after.geometryVersion).toBe(0) // local clock untouched
    expect(after.serverGeometryVersion).toBe(7)
  })
})