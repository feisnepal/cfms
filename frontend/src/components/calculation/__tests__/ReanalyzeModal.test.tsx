import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ReanalyzeModal } from '../ReanalyzeModal'

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }))

const reanalyze = vi.fn()
vi.mock('../../../services/api', () => ({
  forestApi: { reanalyze: (...a: unknown[]) => reanalyze(...a) },
}))

// AnalysisOptionsPanel pulls in chart/preset machinery we don't need here.
vi.mock('../../AnalysisOptionsPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="analysis-options" />,
}))

const okButton = () => screen.getByRole('button', { name: 'calc.reanalyze.action' })

describe('ReanalyzeModal (A5a)', () => {
  beforeEach(() => {
    reanalyze.mockReset()
  })

  it('does not render its body when closed', () => {
    render(<ReanalyzeModal open={false} calculationId="c1" onClose={vi.fn()} onDone={vi.fn()} />)
    expect(screen.queryByTestId('analysis-options')).not.toBeInTheDocument()
  })

  it('renders the options panel when open', () => {
    render(<ReanalyzeModal open calculationId="c1" onClose={vi.fn()} onDone={vi.fn()} />)
    expect(screen.getByTestId('analysis-options')).toBeInTheDocument()
  })

  it('runs the re-analysis, refreshes, and closes on success', async () => {
    reanalyze.mockResolvedValueOnce({})
    const onClose = vi.fn()
    const onDone = vi.fn()
    render(<ReanalyzeModal open calculationId="c1" onClose={onClose} onDone={onDone} />)
    fireEvent.click(okButton())
    await waitFor(() => expect(reanalyze).toHaveBeenCalledWith('c1', expect.anything()))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('keeps the modal open on failure', async () => {
    reanalyze.mockRejectedValueOnce({ response: { data: { detail: 'boom' } } })
    const onClose = vi.fn()
    render(<ReanalyzeModal open calculationId="c1" onClose={onClose} onDone={vi.fn()} />)
    fireEvent.click(okButton())
    await waitFor(() => expect(reanalyze).toHaveBeenCalled())
    expect(onClose).not.toHaveBeenCalled()
  })
})
