import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StemMappingModal from '../StemMappingModal'

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }))

// The real form is TreeMappingTab (covered by its own tests); here it is a stand-in
// that lets a test drive the host callbacks and see the props the modal passes down.
vi.mock('../TreeMappingTab', () => ({
  TreeMappingTab: (props: {
    calculationId: string
    onChanged?: (c: 'created' | 'deleted' | 'processed' | 'updated') => void
  }) => (
    <div data-testid="tree-mapping-tab" data-calc={props.calculationId}>
      <button onClick={() => props.onChanged?.('created')}>fake-create</button>
      <button onClick={() => props.onChanged?.('deleted')}>fake-delete</button>
      <button onClick={() => props.onChanged?.('processed')}>fake-processed</button>
      <button onClick={() => props.onChanged?.('updated')}>fake-updated</button>
    </div>
  ),
}))

const mount = (over: Partial<React.ComponentProps<typeof StemMappingModal>> = {}) => {
  const onClose = vi.fn()
  const onChanged = vi.fn()
  render(<StemMappingModal open calculationId="calc-9" onClose={onClose} onChanged={onChanged} {...over} />)
  return { onClose, onChanged }
}

describe('StemMappingModal', () => {
  it('shows the Tree Mapping process for this forest', () => {
    mount()
    expect(screen.getByText('treeMapping.manageFromMapTitle')).toBeTruthy()
    const tab = screen.getByTestId('tree-mapping-tab')
    expect(tab.getAttribute('data-calc')).toBe('calc-9')
  })

  it('renders nothing while closed', () => {
    mount({ open: false })
    expect(screen.queryByTestId('tree-mapping-tab')).toBeNull()
  })

  it('a created census refreshes the workspace AND closes the modal, so the trees are on the map', () => {
    const { onClose, onChanged } = mount()
    fireEvent.click(screen.getByText('fake-create'))
    expect(onChanged).toHaveBeenCalledWith('created')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('a processed census (corrections applied) refreshes the workspace but leaves the modal open', () => {
    const { onClose, onChanged } = mount()
    fireEvent.click(screen.getByText('fake-processed'))
    expect(onChanged).toHaveBeenCalledWith('processed')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('a deleted or updated census refreshes the workspace but leaves the modal open', () => {
    const { onClose, onChanged } = mount()
    fireEvent.click(screen.getByText('fake-delete'))
    expect(onChanged).toHaveBeenCalledWith('deleted')
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('fake-updated'))
    expect(onChanged).toHaveBeenCalledWith('updated')
    expect(onClose).not.toHaveBeenCalled()
  })
})