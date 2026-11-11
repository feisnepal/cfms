/**
 * API client integration tests.
 *
 * Tests authentication endpoints (login, register, user info) against
 * the mock service worker (MSW) handlers defined in mocks/server.ts.
 */
import { describe, it, expect } from 'vitest'
import { authApi } from '../services/api'

describe('authApi.login', () => {
  it('returns a token for valid credentials', async () => {
    const res = await authApi.login({
      email: 'demo@forest.com',
      password: 'Demo1234',
    })
    expect(res.access_token).toBe('test-jwt-token')
    expect(res.token_type).toBe('bearer')
  })
})

describe('authApi.me', () => {
  it('returns the current user', async () => {
    const user = await authApi.me()
    expect(user.email).toBe('demo@forest.com')
    expect(user.role).toBe('admin')
  })
})
