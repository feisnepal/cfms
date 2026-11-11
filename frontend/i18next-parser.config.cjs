/** i18next-parser config — Phase 0.3 (advisory scan tooling). */
module.exports = {
  contextSeparator: '_',
  createOldCatalogs: false,
  defaultNamespace: 'translation',
  defaultValue: '',
  indentation: 2,
  keepRemoved: false,
  keySeparator: '.',
  namespaceSeparator: ':',
  lexers: {
    ts: [{ lexer: 'JavascriptLexer', functions: ['t'] }],
    tsx: [{ lexer: 'JsxLexer', functions: ['t'] }],
    default: ['JavascriptLexer'],
  },
  locales: ['en', 'ne'],
  output: 'node_modules/.cache/i18n-scan/$LOCALE.json',
  input: ['src/**/*.{ts,tsx}'],
  sort: true,
  verbose: false,
};