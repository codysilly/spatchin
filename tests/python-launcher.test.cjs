'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { pythonCommand } = require('./python-launcher.cjs');

test('selects the native Python command for each platform', () => {
  assert.equal(pythonCommand({}, 'win32'), 'python');
  assert.equal(pythonCommand({}, 'linux'), 'python3');
  assert.equal(pythonCommand({}, 'darwin'), 'python3');
});

test('preserves the PYTHON environment override on every platform', () => {
  assert.equal(pythonCommand({ PYTHON: 'custom-python' }, 'win32'), 'custom-python');
  assert.equal(pythonCommand({ PYTHON: 'custom-python' }, 'linux'), 'custom-python');
});
