// Initial correctness checks; expand only after the existing source baseline passes.
export default [
  {
    ignores: [
      'airport-catalog.js',
      '**/node_modules/**',
      '**/dist/**',
      '**/.wrangler/**',
      'data/**',
      'docs/reference/**',
      'tests/fixtures/**',
      'preview/*fixtures.js',
    ],
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    languageOptions: { ecmaVersion: 'latest' },
    rules: {
      'no-dupe-args': 'error',
      'no-dupe-keys': 'error',
      'no-unreachable': 'error',
      'no-unsafe-finally': 'error',
      'valid-typeof': 'error',
    },
  },
  {
    files: ['app.js', 'notam-reader.js', 'notam-snapshots.js', 'preview/*.js'],
    languageOptions: { sourceType: 'script' },
  },
];
