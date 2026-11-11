import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import type { FireLineSummary } from '../../services/api'
import { FireLinePanel } from '../FireLinePanel'
import { FireLineDrawEditor } from '../FireLineDrawEditor'

vi.mock('../../i18n/hooks', () => ({
  useT: () => (k: string, p?: Record<string, unknown>) => (p ? `${k} ${JSON.stringify(p)}` : k),
}))

const list = vi.fn()
const decide = vi.fn()
const regenerate = vi.fn()
const preview = vi.fn()
const create = vi.fn()
const setWidths = vi.fn()
const planOptions = vi.fn()
const plan = vi.fn()
const riverList = vi.fn()
const riverDecide = vi.fn()
const riverPreview = vi.fn()
const riverCreate = vi.fn()
const riverRegenerate = vi.fn()
const riverSetWidths = vi.fn()
vi.mock('../../services/api', () => ({
  fireLineApi: {
    list: (...a: unknown[]) => list(...a),
    decide: (...a: unknown[]) => decide(...a),
    regenerate: (...a: unknown[]) => regenerate(...a),
    preview: (...a: unknown[]) => preview(...a),
    create: (...a: unknown[]) => create(...a),
    setWidths: (...a: unknown[]) => setWidths(...a),
    planOptions: (...a: unknown[]) => planOptions(...a),
    plan: (...a: unknown[]) => plan(...a),
  },
  riverBankApi: {
    list: (...a: unknown[]) => riverList(...a),
    decide: (...a: unknown[]) => riverDecide(...a),
    regenerate: (...a: unknown[]) => riverRegenerate(...a),
    preview: (...a: unknown[]) => riverPreview(...a),
    create: (...a: unknown[]) => riverCreate(...a),
    setWidths: (...a: unknown[]) => riverSetWidths(...a),
  },
}))

const LINE: GeoJSON.LineString = { type: 'LineString', coordinates: [[85.3, 27.7], [85.301, 27.7], [85.302, 27.701]] }

const row = (unit_key: string, name: string, extra: Record<string, unknown> = {}) => ({
  unit_key, name, group: 'boundary', highway: '', ticked: true, strip_id: `id-${unit_key}`, length_m: 120, area_ha: 0.036,
  edited: false, centerline: LINE, segment_widths_m: [1.5, 1.5], ...extra,
})

const SUMMARY: FireLineSummary = {
  status: { state: 'ok' },
  rows: [
    row('a', 'SC1-SC2'),
    row('b', 'SC1-SC3'),
    row('c', 'बाटो (path)', { group: 'road', length_m: 243, area_ha: 0.073 }),
    row('d', 'SC2-SC3', { ticked: false, strip_id: null }),
  ] as FireLineSummary['rows'],
  drawn: [{ strip_id: 'dr1', name: 'My line', length_m: 80, area_ha: 0.02, segment_widths_m: [1, 2], centerline: LINE }],
  totals: { boundary: { count: 2, km: 0.24, ha: 0.072 }, road: { count: 1, km: 0.243, ha: 0.073 }, drawn: { count: 1, km: 0.08, ha: 0.02 } },
  excluded: ['d'],
}

const panel = (props: Partial<React.ComponentProps<typeof FireLinePanel>> = {}) =>
  render(<FireLinePanel map={null} calculationId="calc-1" onClose={() => {}} onChanged={() => {}} {...props} />)

beforeEach(() => {
  for (const f of [list, decide, regenerate, preview, create, setWidths, planOptions, plan, riverList, riverDecide, riverPreview, riverCreate, riverRegenerate, riverSetWidths]) f.mockReset()
  list.mockResolvedValue(SUMMARY)
})

describe('FireLinePanel — the tick-list', () => {
  it('lists the boundaries and the roads in their own groups, with the unticked one unticked', async () => {
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    expect(within(screen.getByTestId('fire-line-group-boundary')).getAllByTestId('fire-line-row')).toHaveLength(3)
    expect(within(screen.getByTestId('fire-line-group-road')).getAllByTestId('fire-line-row')).toHaveLength(1)
    expect((screen.getByLabelText('SC1-SC2') as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText('SC2-SC3') as HTMLInputElement).checked).toBe(false)
    expect(within(screen.getByTestId('fire-line-group-drawn')).getByText('My line')).toBeTruthy()
  })

  it('stages ticks, moves the totals live, and applies them as one batch', async () => {
    decide.mockResolvedValue({ ...SUMMARY, rows: SUMMARY.rows.map((r) => (r.unit_key === 'a' ? { ...r, ticked: false, strip_id: null } : r)) })
    const onChanged = vi.fn()
    panel({ onChanged })
    await screen.findByTestId('fire-line-group-boundary')
    expect((screen.getByTestId('fire-line-apply') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('SC1-SC2'))
    expect(screen.getByTestId('fire-line-totals').textContent).toContain('"count":1')           // boundary 2 -> 1
    expect((screen.getByTestId('fire-line-apply') as HTMLButtonElement).disabled).toBe(false)
    expect(decide).not.toHaveBeenCalled()                                                       // nothing sent per click
    fireEvent.click(screen.getByTestId('fire-line-apply'))
    await waitFor(() => expect(decide).toHaveBeenCalledWith('calc-1', [{ unit_key: 'a', included: false }]))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect((screen.getByLabelText('SC1-SC2') as HTMLInputElement).checked).toBe(false)
  })

  it('reset throws the staged ticks away', async () => {
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.click(screen.getByLabelText('SC1-SC2'))
    fireEvent.click(screen.getByTestId('fire-line-reset'))
    expect((screen.getByLabelText('SC1-SC2') as HTMLInputElement).checked).toBe(true)
    expect(decide).not.toHaveBeenCalled()
  })

  it('"untick all shown" only touches what the filter shows', async () => {
    decide.mockResolvedValue(SUMMARY)
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.change(screen.getByTestId('fire-line-filter'), { target: { value: 'SC1' } })
    expect(screen.getAllByTestId('fire-line-row')).toHaveLength(2)
    fireEvent.click(screen.getByTestId('fire-line-select-none'))
    fireEvent.click(screen.getByTestId('fire-line-apply'))
    await waitFor(() => expect(decide).toHaveBeenCalledWith('calc-1', [{ unit_key: 'a', included: false }, { unit_key: 'b', included: false }]))
  })

  it('regenerate asks the server', async () => {
    regenerate.mockResolvedValue(SUMMARY)
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.click(screen.getByTestId('fire-line-regenerate'))
    await waitFor(() => expect(regenerate).toHaveBeenCalledWith('calc-1'))
  })

  it('explains why nothing was made when the units overlap', async () => {
    list.mockResolvedValue({ ...SUMMARY, status: { state: 'dirty_units', overlap_m2: 2686 }, rows: [], drawn: [], totals: {} })
    panel()
    expect((await screen.findByTestId('fire-line-status')).textContent).toContain('fireLines.status.dirty_units')
    expect(screen.getByTestId('fire-line-status').textContent).toContain('2686')
  })

  it('changes nothing in a locked structure', async () => {
    panel({ structureLocked: true })
    await screen.findByTestId('fire-line-group-boundary')
    expect((screen.getByLabelText('SC1-SC2') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByTestId('fire-line-regenerate') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByTestId('fire-line-draw') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryAllByTestId('fire-line-widths')).toHaveLength(0)
  })

  it('shows a friendly error and keeps the staged ticks when saving fails', async () => {
    decide.mockRejectedValue({ response: { data: { detail: { code: 'x', message: 'Could not do that' } } } })
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.click(screen.getByLabelText('SC1-SC2'))
    fireEvent.click(screen.getByTestId('fire-line-apply'))
    expect((await screen.findByRole('alert')).textContent).toBe('Could not do that')
    expect((screen.getByLabelText('SC1-SC2') as HTMLInputElement).checked).toBe(false)
  })

  it('the draw button needs a map', async () => {
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    expect((screen.getByTestId('fire-line-draw') as HTMLButtonElement).disabled).toBe(true)
  })

  it('opens the width editor for a line with its own widths', async () => {
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.click(screen.getAllByTestId('fire-line-widths')[0])
    expect(await screen.findByTestId('fire-line-draw-editor')).toBeTruthy()
    expect(screen.getByTestId('fire-line-width-0')).toBeTruthy()
    expect(screen.getByTestId('fire-line-width-1')).toBeTruthy()
  })
})

describe('FireLineDrawEditor — a width for every segment', () => {
  const PREVIEW = { name: 'A-B', geometry: { type: 'Polygon', coordinates: [] }, parts: 1, length_m: 210.4, area_ha: 0.061, segment_widths_m: [1.5, 1.5], zone_overlap_ha: {}, warnings: [] }
  beforeEach(() => {
    preview.mockResolvedValue(PREVIEW)
  })

  const editor = (props: Partial<React.ComponentProps<typeof FireLineDrawEditor>> = {}) => {
    const onDone = vi.fn()
    render(<FireLineDrawEditor calculationId="calc-1" map={null} mode="create" centerline={LINE} onClose={() => {}} onDone={onDone} {...props} />)
    return onDone
  }

  it('starts every segment at the default width and previews with them', async () => {
    editor()
    expect((screen.getByTestId('fire-line-width-0') as HTMLInputElement).value).toBe('1.5')
    expect((screen.getByTestId('fire-line-width-1') as HTMLInputElement).value).toBe('1.5')
    await waitFor(() => expect(preview).toHaveBeenCalledWith('calc-1', LINE, [1.5, 1.5]))
    expect((await screen.findByTestId('fire-line-preview-summary')).textContent).toContain('210')
    expect((screen.getByTestId('fire-line-name') as HTMLInputElement).value).toBe('A-B')          // the suggested name
  })

  it('one segment can differ from the next', async () => {
    editor()
    fireEvent.change(screen.getByTestId('fire-line-width-1'), { target: { value: '4' } })
    await waitFor(() => expect(preview).toHaveBeenLastCalledWith('calc-1', LINE, [1.5, 4]))
  })

  it('"same width for all" sets every segment', async () => {
    editor()
    fireEvent.change(screen.getByTestId('fire-line-width-all'), { target: { value: '2.5' } })
    expect((screen.getByTestId('fire-line-width-0') as HTMLInputElement).value).toBe('2.5')
    expect((screen.getByTestId('fire-line-width-1') as HTMLInputElement).value).toBe('2.5')
  })

  it('refuses a width outside the limits before asking the server', async () => {
    editor()
    await waitFor(() => expect(preview).toHaveBeenCalled())
    preview.mockClear()
    fireEvent.change(screen.getByTestId('fire-line-width-0'), { target: { value: '80' } })
    await new Promise((r) => setTimeout(r, 500))
    expect(preview).not.toHaveBeenCalled()
    expect((screen.getByTestId('fire-line-save') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('fire-line-width-0').getAttribute('aria-invalid')).toBe('true')
  })

  it('creates the line with a client id and the widths', async () => {
    create.mockResolvedValue({ created: ['x'], replayed: false })
    const onDone = editor()
    await screen.findByTestId('fire-line-preview-summary')
    fireEvent.change(screen.getByTestId('fire-line-name'), { target: { value: 'Ridge line' } })
    fireEvent.click(screen.getByTestId('fire-line-save'))
    await waitFor(() => expect(create).toHaveBeenCalled())
    const body = create.mock.calls[0][1]
    expect(body).toMatchObject({ centerline: LINE, widths_m: [1.5, 1.5], name: 'Ridge line' })
    expect(typeof body.client_id).toBe('string')
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('changes the widths of an existing line instead of creating one', async () => {
    setWidths.mockResolvedValue({})
    const onDone = editor({ mode: 'edit', stripId: 's9', initialWidths: [1, 3] })
    expect((screen.getByTestId('fire-line-width-1') as HTMLInputElement).value).toBe('3')
    expect(screen.queryByTestId('fire-line-name')).toBeNull()
    await screen.findByTestId('fire-line-preview-summary')
    fireEvent.click(screen.getByTestId('fire-line-save'))
    await waitFor(() => expect(setWidths).toHaveBeenCalledWith('calc-1', 's9', [1, 3]))
    expect(create).not.toHaveBeenCalled()
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it("shows the server's reason when the line is outside the forest", async () => {
    preview.mockRejectedValue({ response: { data: { detail: { code: 'outside_forest', message: 'The line lies outside the forest area' } } } })
    editor()
    expect((await screen.findByRole('alert')).textContent).toBe('The line lies outside the forest area')
    expect((screen.getByTestId('fire-line-save') as HTMLButtonElement).disabled).toBe(true)
  })
})


describe('FireLinePanel — the yearly plan', () => {
  const ACTIVITIES = [{ id: 7, activity: 'Fire line construction', program: 'P', unit: 'कि.मि.', map_kind: 'fire_line' }]

  it('stays closed until asked, then offers the fire-line activities', async () => {
    planOptions.mockResolvedValue({ activities: ACTIVITIES })
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    expect(screen.queryByTestId('fire-line-plan')).toBeNull()
    fireEvent.click(screen.getByTestId('fire-line-plan-toggle'))
    const select = (await screen.findByTestId('fire-line-plan-activity')) as HTMLSelectElement
    expect(planOptions).toHaveBeenCalledWith('calc-1')
    expect(select.value).toBe('7')                                              // the only activity is chosen for you
    expect((screen.getByTestId('fire-line-plan-create') as HTMLButtonElement).disabled).toBe(false)
  })

  it('creates the plan lines, leaving the existing roads out unless asked, and reports what happened', async () => {
    planOptions.mockResolvedValue({ activities: ACTIVITIES })
    plan.mockResolvedValue({ created: 3, existing: 1, skipped_roads: 2, no_unit: ['X'], strips: 4 })
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.click(screen.getByTestId('fire-line-plan-toggle'))
    await screen.findByTestId('fire-line-plan-activity')
    fireEvent.click(screen.getByTestId('fire-line-plan-create'))
    await waitFor(() => expect(plan).toHaveBeenCalledWith('calc-1', { potential_activity_id: 7, include_roads: false }))
    const result = await screen.findByTestId('fire-line-plan-result')
    expect(result.textContent).toContain('"created":3')
    expect(result.textContent).toContain('fireLines.plan.noUnit')
    fireEvent.click(screen.getByTestId('fire-line-plan-roads'))
    fireEvent.click(screen.getByTestId('fire-line-plan-create'))
    await waitFor(() => expect(plan).toHaveBeenLastCalledWith('calc-1', { potential_activity_id: 7, include_roads: true }))
  })

  it('says so when the master list has no fire-line activity', async () => {
    planOptions.mockResolvedValue({ activities: [] })
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.click(screen.getByTestId('fire-line-plan-toggle'))
    expect(await screen.findByTestId('fire-line-plan-none')).toBeTruthy()
    expect(screen.queryByTestId('fire-line-plan-create')).toBeNull()
  })

  it('cannot plan in a locked structure', async () => {
    panel({ structureLocked: true })
    await screen.findByTestId('fire-line-group-boundary')
    expect((screen.getByTestId('fire-line-plan-toggle') as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows the reason when planning fails', async () => {
    planOptions.mockResolvedValue({ activities: ACTIVITIES })
    plan.mockRejectedValue({ response: { data: { detail: { code: 'not_found', message: 'That activity does not exist' } } } })
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    fireEvent.click(screen.getByTestId('fire-line-plan-toggle'))
    await screen.findByTestId('fire-line-plan-activity')
    fireEvent.click(screen.getByTestId('fire-line-plan-create'))
    expect((await screen.findByRole('alert')).textContent).toBe('That activity does not exist')
  })
})


describe('FireLinePanel — river banks (the same panel, a different kind)', () => {
  const RIVER: FireLineSummary = {
    kind: 'river_bank',
    status: { state: 'ok' },
    rows: [
      { unit_key: 'river:river84:Jorchhanga Khola|1', name: 'A-B (Jorchhanga Khola)', group: 'river', highway: '', ticked: true, strip_id: 'b1', length_m: 2539, area_ha: 10.17, edited: false, centerline: LINE, segment_widths_m: [20, 20] },
    ] as FireLineSummary['rows'],
    drawn: [],
    totals: { river: { count: 1, km: 2.539, ha: 10.17 } },
    excluded: [],
  }
  beforeEach(() => {
    riverList.mockResolvedValue(RIVER)
  })

  const riverPanel = () => render(<FireLinePanel kind="river_bank" map={null} calculationId="calc-1" onClose={() => {}} onChanged={() => {}} />)

  it('reads the river-bank list, shows the rivers group, and none of the fire-line things', async () => {
    riverPanel()
    expect(await screen.findByTestId('fire-line-group-river')).toBeTruthy()
    expect(riverList).toHaveBeenCalledWith('calc-1')
    expect(list).not.toHaveBeenCalled()
    expect(screen.queryByTestId('fire-line-group-boundary')).toBeNull()
    expect(screen.queryByTestId('fire-line-group-road')).toBeNull()
    expect(screen.queryByTestId('fire-line-plan-toggle')).toBeNull()                   // a river bank is not planned like a fire line
    expect(screen.getByTestId('fire-line-totals').textContent).toContain('riverBanks.totals')
  })

  it('unticks through the river-bank route', async () => {
    riverDecide.mockResolvedValue({ ...RIVER, rows: [{ ...RIVER.rows[0], ticked: false, strip_id: null }], totals: {} })
    riverPanel()
    await screen.findByTestId('fire-line-group-river')
    fireEvent.click(screen.getByLabelText('A-B (Jorchhanga Khola)'))
    fireEvent.click(screen.getByTestId('fire-line-apply'))
    await waitFor(() => expect(riverDecide).toHaveBeenCalledWith('calc-1', [{ unit_key: 'river:river84:Jorchhanga Khola|1', included: false }]))
    expect(decide).not.toHaveBeenCalled()
  })

  it('regenerates through the river-bank route', async () => {
    riverRegenerate.mockResolvedValue(RIVER)
    riverPanel()
    await screen.findByTestId('fire-line-group-river')
    fireEvent.click(screen.getByTestId('fire-line-regenerate'))
    await waitFor(() => expect(riverRegenerate).toHaveBeenCalledWith('calc-1'))
    expect(regenerate).not.toHaveBeenCalled()
  })

  it('opens the width editor at the bank width and previews with the river-bank route', async () => {
    riverPreview.mockResolvedValue({ name: 'X', geometry: { type: 'Polygon', coordinates: [] }, parts: 1, length_m: 100, area_ha: 0.4, segment_widths_m: [20, 20], zone_overlap_ha: {}, warnings: [] })
    riverPanel()
    await screen.findByTestId('fire-line-group-river')
    fireEvent.click(screen.getByTestId('fire-line-widths'))
    expect((await screen.findByTestId('fire-line-width-0') as HTMLInputElement).value).toBe('20')
    await waitFor(() => expect(riverPreview).toHaveBeenCalledWith('calc-1', LINE, [20, 20]))
    expect(preview).not.toHaveBeenCalled()
  })

  it('a new river-bank strip starts every segment at 20 m and is created through the river-bank route', async () => {
    riverPreview.mockResolvedValue({ name: 'River bank', geometry: { type: 'Polygon', coordinates: [] }, parts: 1, length_m: 100, area_ha: 0.4, segment_widths_m: [20, 20], zone_overlap_ha: {}, warnings: [] })
    riverCreate.mockResolvedValue({ created: ['x'], replayed: false })
    const onDone = vi.fn()
    render(
      <FireLineDrawEditor calculationId="calc-1" map={null} mode="create" centerline={LINE} onClose={() => {}} onDone={onDone}
        api={(await import('../../services/api')).riverBankApi} defaultSide={20} createTitleKey="riverBanks.drawEditorTitle" />,
    )
    expect((screen.getByTestId('fire-line-width-0') as HTMLInputElement).value).toBe('20')
    expect(screen.getByTestId('fire-line-draw-editor').textContent).toContain('riverBanks.drawEditorTitle')
    await screen.findByTestId('fire-line-preview-summary')
    fireEvent.click(screen.getByTestId('fire-line-save'))
    await waitFor(() => expect(riverCreate).toHaveBeenCalled())
    expect(create).not.toHaveBeenCalled()
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('explains a missing generation in river-bank words', async () => {
    riverList.mockResolvedValue({ ...RIVER, status: { state: 'never' }, rows: [], totals: {} })
    riverPanel()
    expect((await screen.findByTestId('fire-line-status')).textContent).toContain('riverBanks.status.never')
  })
})

describe('FireLinePanel — guide, steps and layout', () => {
  beforeEach(() => { window.localStorage.clear() })

  it('opens the guide the first time, remembers that it was read, and brings it back from the chip', async () => {
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    expect(screen.getByTestId('fire-line-guide')).toBeTruthy()
    fireEvent.click(screen.getByTestId('fire-line-guide-close'))
    expect(screen.queryByTestId('fire-line-guide')).toBeNull()
    fireEvent.click(screen.getByTestId('fire-line-guide-toggle'))
    expect(screen.getByTestId('fire-line-guide')).toBeTruthy()
  })

  it('does not open the guide again once it has been read', async () => {
    window.localStorage.setItem('fireLinePanel.guideSeen', '1')
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    expect(screen.queryByTestId('fire-line-guide')).toBeNull()
  })

  it('moves the highlighted step to Apply when there are unsaved ticks', async () => {
    window.localStorage.setItem('fireLinePanel.guideSeen', '1')
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    const active = () => within(screen.getByTestId('fire-line-steps')).getByRole('listitem', { current: 'step' }).textContent
    expect(active()).toContain('fireLines.ui.steps.edit')
    fireEvent.click(screen.getByLabelText('SC1-SC2'))
    expect(active()).toContain('fireLines.ui.steps.apply')
  })

  it('gives every action a tooltip, folds a group, and has no plan step for river banks', async () => {
    window.localStorage.setItem('fireLinePanel.guideSeen', '1')
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    for (const id of ['fire-line-apply', 'fire-line-reset', 'fire-line-regenerate', 'fire-line-draw', 'fire-line-plan-toggle']) {
      expect(screen.getByTestId(id).getAttribute('title')).toBeTruthy()
    }
    const group = screen.getByTestId('fire-line-group-boundary')
    fireEvent.click(within(group).getAllByRole('button').find((b) => b.getAttribute('aria-expanded') === 'true')!)
    expect(within(group).queryAllByTestId('fire-line-row')).toHaveLength(0)
  })

  it('cycles the window size', async () => {
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    const width = () => (screen.getByTestId('fire-line-panel') as HTMLElement).style.width
    const before = width()
    fireEvent.click(screen.getByTestId('fire-line-size'))
    expect(width()).not.toBe(before)
  })
})

describe('FireLinePanel — free resize', () => {
  it('has a corner grip that sets the width and height, and the size button returns to a preset', async () => {
    window.localStorage.setItem('fireLinePanel.guideSeen', '1')
    panel()
    await screen.findByTestId('fire-line-group-boundary')
    const box = screen.getByTestId('fire-line-panel') as HTMLElement
    const grip = screen.getByTestId('fire-line-panel-grip')
    fireEvent.pointerDown(grip, { clientX: 500, clientY: 500, pointerId: 1 })
    fireEvent.pointerMove(grip, { clientX: 560, clientY: 540, pointerId: 1 })
    expect(box.style.height).not.toBe('')
    fireEvent.pointerUp(grip, { pointerId: 1 })
    fireEvent.click(screen.getByTestId('fire-line-size'))
    expect(box.style.height).toBe('')
  })
})
