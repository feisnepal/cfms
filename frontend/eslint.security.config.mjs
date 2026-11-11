// eslint.security.config.mjs
// H4.6 / S2-42 / S3-09 security gates, run by scripts/check-security-rules.mjs.
//
// Three rules that have ZERO tolerance for what they guard:
//   - local/no-console-outside-dev : console.* only inside an `import.meta.env.DEV`
//     guard (the repo's logging convention — the "logger module" S2-42 asks to
//     allowlist). Anything else is a leak into prod bundles and Sentry noise.
//   - no-restricted-syntax / fetch : bare `fetch(` bypasses the shared axios
//     instance in services/api.ts, losing 401-refresh-and-retry, correlation
//     headers, cache invalidation and error normalisation (S3-09 seeks to ban).
//   - no-restricted-syntax / token : reading 'access_token' out of localStorage
//     outside the auth layer is the token-replay surface S3-09 documented
//     (15+ components grabbing it directly).
//
// It is deliberately NOT part of eslint.config.mjs: the baseline ratchet (4.1)
// refuses growth, and this rule family starts with ~700 known violations as an
// existing-debt baseline. A separate config + separate baseline lets the debt
// be frozen and only shrink, without unpicking the 152-error lint baseline.
//
// Sanctioned escapes, encoded as file-scoped overrides:
//   - src/services/**            : the axios client — fetching IS its job, and it
//                                  owns token storage (storeTokens/removeTokens).
//   - src/contexts/**            : AuthContext is the ONE component allowed to
//                                  read the token (login bootstrap).
//   - tests (__tests__, *.test.*, test/) : vitest fixtures mock fetch()/localStorage;
//                                  a rule that flagged test scaffolding would teach
//                                  people to disable the whole gate.
import tseslint from 'typescript-eslint'

/** console.* is the repo's log channel ONLY inside an `import.meta.env.DEV` guard. */
const noConsoleOutsideDev = {
  meta: {
    type: 'problem',
    docs: { description: 'console.* must be inside an import.meta.env.DEV guard' },
    messages: {
      plain:
        'console.{{method}}() outside a DEV-gated block (S2-42). Guard it with `if (import.meta.env.DEV)`, or route through a logger so it does not reach prod bundles.',
    },
  },
  create(context) {
    const sourceCode = context.sourceCode
    return {
      CallExpression(node) {
        const callee = node.callee
        if (callee.type !== 'MemberExpression' || callee.computed) return
        if (callee.object?.type !== 'Identifier' || callee.object.name !== 'console') return
        if (callee.property?.type !== 'Identifier') return
        for (const ancestor of sourceCode.getAncestors(node)) {
          if (
            ancestor.type === 'IfStatement' &&
            ancestor.test &&
            /import\.meta\.env\.DEV/.test(sourceCode.getText(ancestor.test))
          ) {
            return
          }
        }
        context.report({
          node,
          messageId: 'plain',
          data: { method: callee.property.name },
        })
      },
    }
  },
}

const fetchSelector = {
  selector: 'CallExpression[callee.name="fetch"]',
  message:
    'S3-09: bare fetch( bypasses the shared axios client in services/api.ts — it loses 401-refresh-and-retry, correlation headers, cache invalidation and error normalisation. Route through services/api.ts instead.',
}

const tokenSelector = {
  selector:
    'CallExpression[callee.object.name="localStorage"][callee.property.name="getItem"][arguments.0.value="access_token"]',
  message:
    'S3-09: direct localStorage access_token read outside the auth layer. Read the token via AuthContext / services/api.ts only.',
}

export default tseslint.config(
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      local: { rules: { 'no-console-outside-dev': noConsoleOutsideDev } },
    },
    rules: {
      'local/no-console-outside-dev': 'error',
      'no-restricted-syntax': ['error', fetchSelector, tokenSelector],
    },
  },
  {
    // The axios client and the auth context are the sanctioned channels.
    files: ['src/services/**', 'src/contexts/**'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
  {
    // Test scaffolding mocks fetch()/localStorage; gate only production code.
    files: ['src/**/__tests__/**', 'src/**/*.test.{ts,tsx}', 'src/test/**'],
    rules: {
      'local/no-console-outside-dev': 'off',
      'no-restricted-syntax': 'off',
    },
  },
)