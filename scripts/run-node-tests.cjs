'use strict';
const { readdirSync } = require('node:fs');
const { join } = require('node:path');
const { spawnSync } = require('node:child_process');

const tests = readdirSync(join(__dirname, '..', 'tests'))
  .filter(
    (name) => /\.test\.[cm]js$/.test(name) && !name.includes('browser') && name !== 'scan.test.cjs',
  )
  .sort()
  .map((name) => join('tests', name));
if (tests.length === 0) throw new Error('No offline Node regression tests found');
const result = spawnSync(process.execPath, ['--test', ...tests], { stdio: 'inherit' });
process.exit(result.status ?? 1);
