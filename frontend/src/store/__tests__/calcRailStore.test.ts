import { describe, it, expect, beforeEach } from 'vitest'
import { useCalcRailStore, RAIL_WIDTH } from '../calcRailStore'

const reset = () =>
  useCalcRailStore.setState({ mode: 'expanded', width: RAIL_WIDTH.DEFAULT })

describe('calcRailStore (A6)', () => {
  beforeEach(() => {
    localStorage.clear()
    reset()
  })

  it('defaults: expanded and the default width', () => {
    const s = useCalcRailStore.getState()
    expect(s.mode).toBe('expanded')
    expect(s.width).toBe(RAIL_WIDTH.DEFAULT)
  })

  it('toggleMode flips expanded <-> compact symmetrically', () => {
    expect(useCalcRailStore.getState().mode).toBe('expanded')
    useCalcRailStore.getState().toggleMode()
    expect(useCalcRailStore.getState().mode).toBe('compact')
    useCalcRailStore.getState().toggleMode()
    expect(useCalcRailStore.getState().mode).toBe('expanded')
  })

  it('setWidth clamps to [MIN, MAX] and rounds', () => {
    const { setWidth } = useCalcRailStore.getState()
    setWidth(10)
    expect(useCalcRailStore.getState().width).toBe(RAIL_WIDTH.MIN)
    setWidth(9999)
    expect(useCalcRailStore.getState().width).toBe(RAIL_WIDTH.MAX)
    setWidth(200.7)
    expect(useCalcRailStore.getState().width).toBe(201)
  })

  it('persists mode + width under cfms.calcRail', async () => {
    useCalcRailStore.getState().toggleMode()
    useCalcRailStore.getState().setWidth(220)
    await useCalcRailStore.persist.rehydrate()
    const raw = localStorage.getItem('cfms.calcRail')
    expect(raw).toBeTruthy()
    const parsed = JSON.parse(raw as string)
    expect(parsed.state).toEqual({ mode: 'compact', width: 220 })
  })

  it('migrates legacy v1 modes to v3 (hidden -> expanded; compact kept)', async () => {
    localStorage.setItem(
      'cfms.calcRail',
      JSON.stringify({ state: { mode: 'hidden', width: 200, userSet: true }, version: 1 }),
    )
    await useCalcRailStore.persist.rehydrate()
    expect(useCalcRailStore.getState().mode).toBe('expanded')
    expect(useCalcRailStore.getState().width).toBe(200)

    localStorage.setItem(
      'cfms.calcRail',
      JSON.stringify({ state: { mode: 'compact', width: 210, userSet: true }, version: 1 }),
    )
    await useCalcRailStore.persist.rehydrate()
    expect(useCalcRailStore.getState().mode).toBe('compact')
    expect(useCalcRailStore.getState().width).toBe(210)
  })

  it('migrates the width-only v2 shape to expanded v3', async () => {
    localStorage.setItem(
      'cfms.calcRail',
      JSON.stringify({ state: { width: 200 }, version: 2 }),
    )
    await useCalcRailStore.persist.rehydrate()
    const s = useCalcRailStore.getState()
    expect(s.mode).toBe('expanded')
    expect(s.width).toBe(200)
  })
})