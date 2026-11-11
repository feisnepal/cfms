import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SubAreaTablesTab from '../SubAreaTablesTab'

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }))

const getBlockAreaDetail = vi.fn()
const getCalculation = vi.fn()
vi.mock('../../../services/api', () => ({
  forestApi: {
    getBlockAreaDetail: (...a: unknown[]) => getBlockAreaDetail(...a),
    getCalculation: (...a: unknown[]) => getCalculation(...a),
  },
}))

vi.mock('../../DetailDescription/CopyTag', () => ({
  __esModule: true,
  default: ({ label }: { label: string }) => <span data-testid="copytag">{label}</span>,
}))

const CALC = {
  id: 'c1',
  result_data: {
    blocks: [{ block_id: 'b1', block_name: 'Block A' }],
    sub_areas: [
      { id: 's1', name: 'Temple plot', category: 'religious', area_hectares: 1.2345, block_id: 'b1', is_excluded: true },
    ],
  },
}

const DETAIL = {
  block_details: [
    {
      block_name: 'Block A',
      total_area_ha: 10,
      tree_cover_area_ha: 7,
      other_landcover_area_ha: 1,
      protected_area_ha: 1,
      private_land_area_ha: 1,
      effective_area_ha: 8,
    },
  ],
  totals: {
    total_area_ha: 10,
    tree_cover_area_ha: 7,
    other_landcover_area_ha: 1,
    protected_area_ha: 1,
    private_land_area_ha: 1,
    effective_area_ha: 8,
  },
}

describe('SubAreaTablesTab (A5c)', () => {
  beforeEach(() => {
    getBlockAreaDetail.mockReset()
    getCalculation.mockReset()
  })

  it('renders Table 1 from calc.result_data.sub_areas and Tables 2/3 from getBlockAreaDetail', async () => {
    getBlockAreaDetail.mockResolvedValueOnce(DETAIL)
    render(<SubAreaTablesTab calculationId="c1" calculation={CALC as never} />)

    expect(screen.getByText('Table 1: Sub-Areas Detail')).toBeInTheDocument()
    expect(screen.getByText('Temple plot')).toBeInTheDocument()
    expect(screen.getByText('Religious')).toBeInTheDocument()
    expect(screen.getByText('Excluded')).toBeInTheDocument()

    await waitFor(() => expect(getBlockAreaDetail).toHaveBeenCalledWith('c1'))
    await screen.findByText('(Block-wise Detailed Area Description)')
    expect(screen.getByText('(Community Forests and Block Area Description)')).toBeInTheDocument()
    // OP variable tags always render
    expect(screen.getAllByTestId('copytag').length).toBeGreaterThanOrEqual(2)
  })

  it('self-fetches the calculation when none is passed', async () => {
    getCalculation.mockResolvedValueOnce(CALC)
    getBlockAreaDetail.mockResolvedValueOnce(DETAIL)
    render(<SubAreaTablesTab calculationId="c1" />)
    await waitFor(() => expect(getCalculation).toHaveBeenCalledWith('c1'))
    await screen.findByText('Table 1: Sub-Areas Detail')
  })

  it('shows the empty state when the calculation has no blocks', async () => {
    render(<SubAreaTablesTab calculationId="c1" calculation={{ id: 'c1', result_data: { blocks: [] } } as never} />)
    expect(screen.getByText(/No .* defined yet/)).toBeInTheDocument()
    expect(getBlockAreaDetail).not.toHaveBeenCalled()
  })

  it('reads the compartments array when the block was divided into compartments', async () => {
    getBlockAreaDetail.mockResolvedValueOnce(DETAIL)
    const compCalc = {
      id: 'c1',
      result_data: {
        // parent block still present, but compartments is the analysed unit
        blocks: [{ block_id: 'b1', block_name: 'Parent Block' }],
        compartments: [
          { block_id: 'k1', block_name: 'C1' },
          { block_id: 'k2', block_name: 'C2' },
        ],
        polygon_type: 'compartment',
        sub_areas: [],
      },
    }
    render(<SubAreaTablesTab calculationId="c1" calculation={compCalc as never} />)
    // hasBlocks is satisfied by the compartments array, not the parent block
    await waitFor(() => expect(getBlockAreaDetail).toHaveBeenCalledWith('c1'))
    expect(screen.queryByText(/No .* defined yet/)).not.toBeInTheDocument()
  })

  it('Table 1 resolves the compartment name geometrically when the sub-area still carries the parent block name', async () => {
    getBlockAreaDetail.mockResolvedValueOnce(DETAIL)
    const sq = (x0: number, y0: number, x1: number, y1: number) => ({
      type: 'Polygon',
      coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    })
    const compCalc = {
      id: 'c1',
      result_data: {
        blocks: [{ block_id: 'b1', block_name: 'Parent Block', geometry: sq(84.0, 28.0, 84.2, 28.1) }],
        compartments: [
          { block_id: 'k1', block_name: 'C-One', geometry: sq(84.0, 28.0, 84.1, 28.1) },
          { block_id: 'k2', block_name: 'C-Two', geometry: sq(84.1, 28.0, 84.2, 28.1) },
        ],
        polygon_type: 'compartment',
        sub_areas: [
          {
            id: 's1',
            name: 'Temple plot',
            category: 'religious',
            area_hectares: 5,
            // stale: tagged with the parent block, which is NOT a unit name
            blockName: 'Parent Block',
            blockBreakdown: [{ blockName: 'Parent Block' }],
            geometry: sq(84.02, 28.02, 84.05, 28.05), // fully inside C-One
          },
        ],
      },
    }
    render(<SubAreaTablesTab calculationId="c1" calculation={compCalc as never} />)
    await screen.findByText('Temple plot')
    // the unit column shows the geometrically-resolved compartment, not "Parent Block"
    expect(screen.getByText('C-One')).toBeInTheDocument()
    expect(screen.queryByText('Parent Block')).not.toBeInTheDocument()
  })

  it('Table 1 offers "Make protection unit" only on protected sub-area rows', async () => {
    getBlockAreaDetail.mockResolvedValueOnce(DETAIL)
    const calc = {
      id: 'c1',
      result_data: {
        blocks: [{ block_id: 'b1', block_name: 'Block A' }],
        sub_areas: [
          { id: 'p1', name: 'Sacred grove', category: 'protected', area_hectares: 3, blockName: 'Block A' },
          { id: 'r1', name: 'Temple', category: 'religious', area_hectares: 1, blockName: 'Block A' },
        ],
      },
    }
    render(<SubAreaTablesTab calculationId="c1" calculation={calc as never} />)
    await screen.findByText('Sacred grove')
    const buttons = screen.getAllByText('protectionUnit.makeUnit')
    expect(buttons).toHaveLength(1) // only the protected row
  })

  it('lists Protection Working Circle units with a "Merge back" action', async () => {
    getBlockAreaDetail.mockResolvedValueOnce(DETAIL)
    const calc = {
      id: 'c1',
      result_data: {
        blocks: [
          { block_id: 'b1', block_name: 'Block A', working_circle: 'production' },
          { block_id: 'p9', block_name: 'P-1', working_circle: 'protection' },
        ],
        sub_areas: [],
      },
    }
    render(<SubAreaTablesTab calculationId="c1" calculation={calc as never} />)
    await screen.findByText('protectionUnit.wcHeading')
    expect(screen.getByText('P-1')).toBeInTheDocument()
    expect(screen.getByText('protectionUnit.mergeBack')).toBeInTheDocument()
  })
})
