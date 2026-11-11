import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { message } from 'antd'
import { PromoteToProtectionUnitButton } from '../PromoteToProtectionUnitButton'

vi.mock('../../../i18n/hooks', () => ({
  useT: () => (k: string, vars?: Record<string, unknown>) =>
    vars ? `${k}:${JSON.stringify(vars)}` : k,
}))

const { promote } = vi.hoisted(() => ({ promote: vi.fn() }))
vi.mock('../../../services/api', () => ({
  forestApi: { promoteSubAreaToUnit: (...a: unknown[]) => promote(...a) },
}))

let ok: MockInstance
let err: MockInstance

describe('PromoteToProtectionUnitButton', () => {
  beforeEach(() => {
    promote.mockReset()
    ok = vi.spyOn(message, 'success').mockImplementation(() => ({}) as never)
    err = vi.spyOn(message, 'error').mockImplementation(() => ({}) as never)
  })
  afterEach(() => {
    ok.mockRestore()
    err.mockRestore()
  })

  const openAndConfirm = async () => {
    await userEvent.click(screen.getByRole('button', { name: 'protectionUnit.makeUnit' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'protectionUnit.makeUnit' }))
  }

  it('confirms then calls the promote API and refreshes', async () => {
    promote.mockResolvedValueOnce({ name: 'P-1' })
    const onDone = vi.fn()
    render(
      <PromoteToProtectionUnitButton
        calculationId="c1" subAreaId="s1" subAreaName="Sacred grove" onDone={onDone}
      />,
    )
    await openAndConfirm()
    await waitFor(() => expect(promote).toHaveBeenCalledWith('c1', 's1'))
    expect(onDone).toHaveBeenCalled()
    expect(ok).toHaveBeenCalled()
  })

  it('shows the lock message on a 423 STRUCTURE_LOCKED', async () => {
    promote.mockRejectedValueOnce({ response: { data: { detail: { code: 'STRUCTURE_LOCKED' } } } })
    render(<PromoteToProtectionUnitButton calculationId="c1" subAreaId="s1" onDone={vi.fn()} />)
    await openAndConfirm()
    await waitFor(() => expect(err).toHaveBeenCalledWith('protectionUnit.lockedError'))
  })

  it('is disabled when disabled prop is set', () => {
    render(<PromoteToProtectionUnitButton calculationId="c1" subAreaId="s1" onDone={vi.fn()} disabled />)
    expect(screen.getByRole('button', { name: 'protectionUnit.makeUnit' })).toBeDisabled()
  })
})

