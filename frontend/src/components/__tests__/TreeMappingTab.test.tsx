import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TreeMappingTab } from '../TreeMappingTab'
import { inventoryApi } from '../../services/api'

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../../services/api', () => ({
  // the shelterwood suggestion panel asks this; "not shelterwood" renders nothing
  sfmApi: { getStemMappingSuggestion: vi.fn().mockResolvedValue({ applies: false, series: [], rows: [], suggested: null }) },
  inventoryApi: {
    checkTreeMappingExists: vi.fn(),
    getTreeMappingByCalculation: vi.fn(),
    getInventorySummary: vi.fn(),
    listInventoryTrees: vi.fn(),
    deleteInventory: vi.fn(),
    previewColumnMapping: vi.fn(),
    confirmColumnMapping: vi.fn(),
    processInventory: vi.fn(),
    updateTreeBlockSubarea: vi.fn(),
    forceDeleteByCalculation: vi.fn(),
    acceptCorrections: vi.fn(),
  },
}))
vi.mock('react-chartjs-2', () => ({ Pie: () => null, Bar: () => null }))
vi.mock('../utils/chartSetup', () => ({}))
vi.mock('../utils/download', () => ({ downloadFromApi: vi.fn() }))
vi.mock('./CorrectionPreviewDialog', () => ({ CorrectionPreviewDialog: () => null }))
vi.mock('./TreeMappingAnalysis', () => ({ TreeMappingAnalysis: () => null }))
// The column-mapping step is coverered by its own suite; here it is a stand-in
// whose "confirm" button drives the real handleConfirmMapping onChanged signal.
vi.mock('../ColumnMappingPreview', () => ({
  default: (props: {
    onConfirm: (mapping: Record<string, string>, savePreference: boolean) => void
    onCancel: () => void
  }) => (
    <div data-testid="colmap">
      <button onClick={() => props.onConfirm({ Species: 'species' }, false)}>fake-confirm</button>
    </div>
  ),
}))

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }))
vi.mock('../../i18n/numberFormat', () => ({
  formatDecimal: (v: number) => String(v),
  parseLocaleNumber: (v: string) => Number(v),
}))
vi.mock('../../hooks/useErrorHandler', () => ({
  readDetail: (d: any) => (typeof d === 'string' ? d : d?.message ?? null),
}))

const summary = {
  total_trees: 3,
  mother_trees_count: 1,
  felling_trees_count: 0,
  seedling_count: 2,
  total_volume_m3: 3,
  total_net_volume_m3: 2,
  total_firewood_m3: 1,
  species_distribution: {},
  dbh_classes: {},
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.stubGlobal('alert', vi.fn())
})

describe('TreeMappingTab onChanged', () => {
  it('fires onChanged("deleted") once the census is deleted', async () => {
    vi.mocked(inventoryApi.checkTreeMappingExists).mockResolvedValue({ exists: true, inventory_id: 'inv-1', filename: 'census.csv', status: 'completed' })
    vi.mocked(inventoryApi.getInventorySummary).mockResolvedValue(summary)
    vi.mocked(inventoryApi.listInventoryTrees).mockResolvedValue({ trees: [] })
    vi.mocked(inventoryApi.deleteInventory).mockResolvedValue()

    const onChanged = vi.fn()
    render(<TreeMappingTab calculationId="calc-9" onChanged={onChanged} />)

    await screen.findByText('treeMapping.tab.title')
    fireEvent.click(screen.getByText('common.delete'))

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('deleted'))
    expect(inventoryApi.deleteInventory).toHaveBeenCalledWith('inv-1')
  })

  it('fires onChanged("created") once a fresh census is uploaded and processed', async () => {
    vi.mocked(inventoryApi.checkTreeMappingExists).mockResolvedValue({ exists: false })
    vi.mocked(inventoryApi.getTreeMappingByCalculation).mockRejectedValue({ response: { status: 404 } })
    vi.mocked(inventoryApi.previewColumnMapping).mockResolvedValue({ preview: {} })
    vi.mocked(inventoryApi.confirmColumnMapping).mockResolvedValue({
      inventory_id: 'inv-9',
      summary: { ready_for_processing: true, status: 'ready' },
      boundary_check: { needs_correction: false },
      errors: [],
      warnings: [],
    })
    vi.mocked(inventoryApi.processInventory).mockResolvedValue({})

    const onChanged = vi.fn()
    const { container } = render(<TreeMappingTab calculationId="calc-9" onChanged={onChanged} />)

    // Upload form appears when the forest has no census yet.
    await screen.findByText('treeMapping.tab.uploadCsvFile')

    const file = new File(['x,y'], 'census.csv', { type: 'text/csv' })
    const input = container.querySelector('input[type="file"]')!
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByText('treeMapping.tab.uploadAndProcess'))

    // Column-mapping preview → confirm mapping.
    await screen.findByTestId('colmap')
    fireEvent.click(screen.getByText('fake-confirm'))

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('created'))
    expect(inventoryApi.processInventory).toHaveBeenCalledWith('inv-9', file)
  })

  it('does not fire onChanged when the forest simply has no census', async () => {
    vi.mocked(inventoryApi.checkTreeMappingExists).mockResolvedValue({ exists: false })
    vi.mocked(inventoryApi.getTreeMappingByCalculation).mockRejectedValue({ response: { status: 404 } })

    const onChanged = vi.fn()
    render(<TreeMappingTab calculationId="calc-9" onChanged={onChanged} />)

    await screen.findByText('treeMapping.tab.uploadCsvFile')
    expect(onChanged).not.toHaveBeenCalled()
  })

  const uploadOnce = async (preview: Record<string, unknown>) => {
    vi.mocked(inventoryApi.checkTreeMappingExists).mockResolvedValue({ exists: false })
    vi.mocked(inventoryApi.getTreeMappingByCalculation).mockRejectedValue({ response: { status: 404 } })
    vi.mocked(inventoryApi.previewColumnMapping).mockResolvedValue(preview)
    vi.mocked(inventoryApi.confirmColumnMapping).mockResolvedValue({
      inventory_id: 'inv-9', summary: { ready_for_processing: true, status: 'ready' }, boundary_check: { needs_correction: false }, errors: [], warnings: [],
    })
    vi.mocked(inventoryApi.processInventory).mockResolvedValue({})
    const onChanged = vi.fn()
    const { container } = render(<TreeMappingTab calculationId="calc-9" onChanged={onChanged} />)
    await screen.findByText('treeMapping.tab.uploadCsvFile')
    const file = new File(['x,y'], 'census.csv', { type: 'text/csv' })
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
    fireEvent.click(screen.getByText('treeMapping.tab.uploadAndProcess'))
    return { onChanged, file }
  }

  it('skips the mapping dialog when every required column was recognised (nothing to confirm)', async () => {
    const mapping = { Species: 'species', DBH: 'dia_cm' }
    const { onChanged, file } = await uploadOnce({ needs_user_input: false, mapping, missing_required: [] })
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('created'))
    expect(screen.queryByTestId('colmap')).toBeNull() // no dialog
    expect(inventoryApi.confirmColumnMapping).toHaveBeenCalledTimes(1)
    expect(vi.mocked(inventoryApi.confirmColumnMapping).mock.calls[0][0]).toBe(file)
    expect(vi.mocked(inventoryApi.confirmColumnMapping).mock.calls[0][1]).toEqual(mapping) // the server's own mapping, unchanged
  })

  it('still shows the dialog when the server says something needs the user (missing, ambiguous or low-confidence columns)', async () => {
    await uploadOnce({ needs_user_input: true, mapping: { Species: 'species' }, missing_required: ['dia_cm'] })
    await screen.findByTestId('colmap')
    expect(inventoryApi.confirmColumnMapping).not.toHaveBeenCalled()
  })

  it('Replace names the file and date it replaces, then clears it so the new file can be uploaded (decision D3)', async () => {
    vi.mocked(inventoryApi.checkTreeMappingExists).mockResolvedValue({ exists: true, inventory_id: 'inv-1', filename: 'census.csv', status: 'completed' })
    vi.mocked(inventoryApi.getInventorySummary).mockResolvedValue(summary)
    vi.mocked(inventoryApi.listInventoryTrees).mockResolvedValue({ trees: [] })
    vi.mocked(inventoryApi.deleteInventory).mockResolvedValue()
    const confirmMock = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmMock)

    const onChanged = vi.fn()
    render(<TreeMappingTab calculationId="calc-9" onChanged={onChanged} />)
    await screen.findByText('treeMapping.tab.title')
    expect(screen.getByTestId('upload-state-line').getAttribute('data-present')).toBe('true') // in the system, with the file name
    fireEvent.click(screen.getByTestId('replace-data'))

    await waitFor(() => expect(inventoryApi.deleteInventory).toHaveBeenCalledWith('inv-1'))
    expect(String((confirmMock.mock.calls[0] as unknown[])[0])).toContain('uploadState.replaceConfirm') // the file-naming confirmation, not the plain delete one
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('deleted'))
  })
})
