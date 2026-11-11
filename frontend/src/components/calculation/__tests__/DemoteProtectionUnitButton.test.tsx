import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { message } from 'antd'
import { DemoteProtectionUnitButton } from '../DemoteProtectionUnitButton'

vi.mock('../../../i18n/hooks', () => ({
  useT: () => (k: string, vars?: Record<string, unknown>) =>
    vars ? `${k}:${JSON.stringify(vars)}` : k,
}))

const { demote } = vi.hoisted(() => ({ demote: vi.fn() }))
vi.mock('../../../services/api', () => ({
  forestApi: { demoteProtectionUnit: (...a: unknown[]) => demote(...a) },
}))

let ok: MockInstance
let err: MockInstance

describe('DemoteProtectionUnitButton', () => {
  beforeEach(() => {
    demote.mockReset()
    ok = vi.spyOn(message, 'success').mockImplementation(() => ({}) as never)
    err = vi.spyOn(message, 'error').mockImplementation(() => ({}) as never)
  })
  afterEach(() => {
    ok.mockRestore()
    err.mockRestore()
  })

  const confirm = async () => {
    await userEvent.click(screen.getByRole('button', { name: 'protectionUnit.mergeBack' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'protectionUnit.mergeBack' }))
  }

  it('confirms then calls the demote API and refreshes', async () => {
    demote.mockResolvedValueOnce({ sub_area_id: 's9' })
    const onDone = vi.fn()
    render(<DemoteProtectionUnitButton calculationId="c1" blockId="b7" unitName="P-1" onDone={onDone} />)
    await confirm()
    await waitFor(() => expect(demote).toHaveBeenCalledWith('c1', 'b7'))
    expect(onDone).toHaveBeenCalled()
    expect(ok).toHaveBeenCalled()
  })

  it('shows the lock message on a 423 STRUCTURE_LOCKED', async () => {
    demote.mockRejectedValueOnce({ response: { data: { detail: { code: 'STRUCTURE_LOCKED' } } } })
    render(<DemoteProtectionUnitButton calculationId="c1" blockId="b7" onDone={vi.fn()} />)
    await confirm()
    await waitFor(() => expect(err).toHaveBeenCalledWith('protectionUnit.lockedError'))
  })
})
