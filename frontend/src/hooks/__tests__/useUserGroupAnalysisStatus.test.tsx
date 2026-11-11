import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useUserGroupAnalysisStatus } from '../useUserGroupAnalysisStatus'
import { useWorkspaceStore } from '../../store/workspaceStore'

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }))
import api from '../../services/api'

const get = api.get as unknown as ReturnType<typeof vi.fn>

describe('useUserGroupAnalysisStatus (BG-2)', () => {
  beforeEach(() => {
    get.mockReset()
    useWorkspaceStore.setState({ geometryVersion: 0 })
  })

  it('reports hasAnalysis when the results carry an extent_id', async () => {
    get.mockResolvedValue({ data: { extent_id: 7, settlements: [] } })
    const { result } = renderHook(() => useUserGroupAnalysisStatus('calc-1'))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.hasAnalysis).toBe(true)
    expect(get).toHaveBeenCalledWith('/api/calculations/calc-1/user-group/results')
  })

  it('reports no analysis when the results are absent (404 / empty)', async () => {
    get.mockRejectedValue({ response: { status: 404 } })
    const { result } = renderHook(() => useUserGroupAnalysisStatus('calc-1'))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.hasAnalysis).toBe(false)
  })

  it('refetches when geometryVersion bumps (fresh analyse/delete refresh)', async () => {
    get.mockResolvedValue({ data: { extent_id: 7 } })
    const { result } = renderHook(() => useUserGroupAnalysisStatus('calc-1'))
    await waitFor(() => expect(result.current.hasAnalysis).toBe(true))
    expect(get).toHaveBeenCalledTimes(1)

    get.mockResolvedValue({ data: { extent_id: 8 } })
    act(() => { useWorkspaceStore.setState({ geometryVersion: 1 }) })
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(result.current.hasAnalysis).toBe(true))
  })

  it('stays no-analysis while loading then resolves', async () => {
    let resolve: (v: unknown) => void = () => {}
    get.mockReturnValue(new Promise((r) => { resolve = r }))
    const { result } = renderHook(() => useUserGroupAnalysisStatus('calc-1'))
    expect(result.current.hasAnalysis).toBe(false)
    expect(result.current.loading).toBe(true)
    await act(async () => { resolve({ data: { extent_id: 9 } }) })
    await waitFor(() => expect(result.current.hasAnalysis).toBe(true))
  })
})