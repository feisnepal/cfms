import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import UserGroupModal from '../UserGroupModal'

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }))

// The real results tab is UserGroupMapTab (covered by its own tests); here it is
// a stand-in that lets a test drive the host callbacks and see the props passed down.
vi.mock('../UserGroupMapTab', () => ({
  default: (props: {
    calculationId: string
    forestName?: string
    onChanged?: (c: 'analyzed' | 'deleted') => void
  }) => (
    <div data-testid="user-group-tab" data-calc={props.calculationId} data-name={props.forestName ?? ''}>
      <button onClick={() => props.onChanged?.('analyzed')}>fake-analyzed</button>
      <button onClick={() => props.onChanged?.('deleted')}>fake-deleted</button>
    </div>
  ),
}))

const mount = (over: Partial<React.ComponentProps<typeof UserGroupModal>> = {}) => {
  const onClose = vi.fn()
  const onChanged = vi.fn()
  render(<UserGroupModal open calculationId="calc-9" forestName="CF" onClose={onClose} onChanged={onChanged} {...over} />)
  return { onClose, onChanged }
}

describe('UserGroupModal', () => {
  it('shows the User Group analysis results view for this forest', () => {
    mount()
    expect(screen.getByText('workspace.userGroup.analysisTitle')).toBeTruthy()
    const tab = screen.getByTestId('user-group-tab')
    expect(tab.getAttribute('data-calc')).toBe('calc-9')
    expect(tab.getAttribute('data-name')).toBe('CF')
  })

  it('renders nothing while closed', () => {
    mount({ open: false })
    expect(screen.queryByTestId('user-group-tab')).toBeNull()
  })

  it('a finished analysis refreshes the workspace AND closes the modal, so the analysis is on the map', () => {
    const { onClose, onChanged } = mount()
    fireEvent.click(screen.getByText('fake-analyzed'))
    expect(onChanged).toHaveBeenCalledWith('analyzed')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('a deleted extent refreshes the workspace but leaves the modal open', () => {
    const { onClose, onChanged } = mount()
    fireEvent.click(screen.getByText('fake-deleted'))
    expect(onChanged).toHaveBeenCalledWith('deleted')
    expect(onClose).not.toHaveBeenCalled()
  })
})