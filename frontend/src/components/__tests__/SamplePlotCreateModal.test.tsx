import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SamplePlotCreateModal from '../SamplePlotCreateModal'

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }))

// The real form is SamplingTab (covered by its own tests); here it is a stand-in that
// lets a test drive the two host callbacks and see the props the modal passes down.
vi.mock('../SamplingTab', () => ({
  SamplingTab: (props: {
    calculationId: string
    startInCreateForm?: boolean
    onDesignChanged?: (c: 'created' | 'deleted') => void
  }) => (
    <div data-testid="sampling-tab" data-calc={props.calculationId} data-start={String(!!props.startInCreateForm)}>
      <button onClick={() => props.onDesignChanged?.('created')}>fake-create</button>
      <button onClick={() => props.onDesignChanged?.('deleted')}>fake-delete</button>
    </div>
  ),
}))

const mount = (over: Partial<React.ComponentProps<typeof SamplePlotCreateModal>> = {}) => {
  const onClose = vi.fn()
  const onChanged = vi.fn()
  render(<SamplePlotCreateModal open calculationId="calc-9" onClose={onClose} onChanged={onChanged} {...over} />)
  return { onClose, onChanged }
}

describe('SamplePlotCreateModal', () => {
  it('shows the sampling form for this forest, opened on the create form', () => {
    mount()
    expect(screen.getByText('sampling.createFromMapTitle')).toBeTruthy()
    const tab = screen.getByTestId('sampling-tab')
    expect(tab.getAttribute('data-calc')).toBe('calc-9')
    expect(tab.getAttribute('data-start')).toBe('true')
  })

  it('renders nothing while closed', () => {
    mount({ open: false })
    expect(screen.queryByTestId('sampling-tab')).toBeNull()
  })

  it('a created design refreshes the workspace AND closes the modal, so the plots are on the map', () => {
    const { onClose, onChanged } = mount()
    fireEvent.click(screen.getByText('fake-create'))
    expect(onChanged).toHaveBeenCalledWith('created')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('a deleted design refreshes the workspace but leaves the modal open on the form', () => {
    const { onClose, onChanged } = mount()
    fireEvent.click(screen.getByText('fake-delete'))
    expect(onChanged).toHaveBeenCalledWith('deleted')
    expect(onClose).not.toHaveBeenCalled()
  })
})
