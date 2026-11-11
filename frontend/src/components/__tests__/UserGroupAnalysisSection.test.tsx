import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { UserGroupAnalysisSection } from '../UserGroupAnalysisSection'
import { useWorkspaceStore } from '../../store/workspaceStore'

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }))

const { useUserGroupAnalysisStatus } = vi.hoisted(() => ({ useUserGroupAnalysisStatus: vi.fn() }))
vi.mock('../../hooks/useUserGroupAnalysisStatus', () => ({ useUserGroupAnalysisStatus }))

const catalog = [
  { id: 'ug_landcover', name: 'User Group Land Cover', description: '' },
  { id: 'ug_biomass', name: 'User Group Biomass', description: '' },
]

const baseStatus = { hasAnalysis: true, loading: false, refetch: vi.fn() }

describe('UserGroupAnalysisSection (BG-2/D6)', () => {
  beforeEach(() => {
    useUserGroupAnalysisStatus.mockReset();
    useWorkspaceStore.setState({
      rasterCatalog: catalog,
      activeRasterLayers: [],
      userGroupPoiVisible: {},
      layerVisibility: { ...useWorkspaceStore.getState().layerVisibility, user_group: true },
    });
  })

  it('renders nothing while there is no analysis', () => {
    useUserGroupAnalysisStatus.mockReturnValue({ ...baseStatus, hasAnalysis: false })
    render(<UserGroupAnalysisSection calculationId="calc-1" />)
    expect(screen.queryByTestId('user-group-analysis-section')).toBeNull()
  })

  it('renders nothing when the user_group layer itself is hidden', () => {
    useUserGroupAnalysisStatus.mockReturnValue(baseStatus)
    useWorkspaceStore.setState({
      layerVisibility: { ...useWorkspaceStore.getState().layerVisibility, user_group: false },
    })
    render(<UserGroupAnalysisSection calculationId="calc-1" />)
    expect(screen.queryByTestId('user-group-analysis-section')).toBeNull()
  })

  it('renders nothing while loading (avoids flicker-in/out)', () => {
    useUserGroupAnalysisStatus.mockReturnValue({ ...baseStatus, loading: true })
    render(<UserGroupAnalysisSection calculationId="calc-1" />)
    expect(screen.queryByTestId('user-group-analysis-section')).toBeNull()
  })

  it('shows POI + raster toggles when an analysis exists', () => {
    useUserGroupAnalysisStatus.mockReturnValue(baseStatus)
    render(<UserGroupAnalysisSection calculationId="calc-1" />)
    expect(screen.getByTestId('user-group-analysis-section')).toBeTruthy()
    expect(screen.getByText('workspace.userGroup.poiEducation')).toBeTruthy()
    expect(screen.getByText('workspace.userGroup.poiHealth')).toBeTruthy()
    expect(screen.getByText('workspace.userGroup.poiPoints')).toBeTruthy()
    expect(screen.getByText('workspace.userGroup.poiRivers')).toBeTruthy()
    expect(screen.getByText('User Group Land Cover')).toBeTruthy()
    expect(screen.getByText('User Group Biomass')).toBeTruthy()
  })

  it('a POI toggle flips the userGroupPoiVisible slice', () => {
    useUserGroupAnalysisStatus.mockReturnValue(baseStatus)
    render(<UserGroupAnalysisSection calculationId="calc-1" />)
    fireEvent.click(screen.getByText('workspace.userGroup.poiEducation'))
    expect(useWorkspaceStore.getState().userGroupPoiVisible.education).toBe(true)
    fireEvent.click(screen.getByText('workspace.userGroup.poiEducation'))
    expect(useWorkspaceStore.getState().userGroupPoiVisible.education).toBe(false)
  })

  it('a raster toggle adds/removes the user-group overlay from activeRasterLayers', () => {
    useUserGroupAnalysisStatus.mockReturnValue(baseStatus)
    render(<UserGroupAnalysisSection calculationId="calc-1" />)
    fireEvent.click(screen.getByText('User Group Land Cover'))
    expect(useWorkspaceStore.getState().activeRasterLayers).toEqual(['ug_landcover'])
    fireEvent.click(screen.getByText('User Group Land Cover'))
    expect(useWorkspaceStore.getState().activeRasterLayers).toEqual([])
  })

  it('falls back to the i18n name when the catalog has not loaded yet', () => {
    useUserGroupAnalysisStatus.mockReturnValue(baseStatus)
    useWorkspaceStore.setState({ rasterCatalog: [] })
    render(<UserGroupAnalysisSection calculationId="calc-1" />)
    expect(screen.getByText('workspace.userGroup.landcoverOverlay')).toBeTruthy()
    expect(screen.getByText('workspace.userGroup.biomassOverlay')).toBeTruthy()
  })
})