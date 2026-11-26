'use strict';
const { readdirSync } = require('node:fs');
const { join } = require('node:path');
const { spawnSync } = require('node:child_process');

const tests = readdirSync(join(__dirname, '..', 'tests'))
  .filter(
    (name) => name.endsWith('.test.cjs') && !name.includes('browser') && name !== 'scan.test.cjs',
  )
  .map((name) => join('tests', name));
const result = spawnSync(process.execPath, ['--test', ...tests], { stdio: 'inherit' });
process.exit(result.status ?? 1);
