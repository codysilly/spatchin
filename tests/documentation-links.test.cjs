'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { existsSync, readFileSync, readdirSync, statSync } = require('node:fs');
const { dirname, join, normalize, resolve } = require('node:path');

const root = resolve(__dirname, '..');

function markdownFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return markdownFiles(path);
    return entry.name.endsWith('.md') ? [path] : [];
  });
}

test('repository documentation links resolve after relocation', () => {
  const files = [join(root, 'README.md'), join(root, 'AGENTS.md'), ...markdownFiles(join(root, 'docs'))];
  const missing = [];
  const link = /\[[^\]]*\]\(([^)]+)\)/g;

  for (const file of files) {
    const text = readFileSync(file, 'utf8');
    for (const match of text.matchAll(link)) {
      const target = match[1].trim().replace(/^<|>$/g, '');
      if (/^(?:https?:|mailto:|#)/i.test(target)) continue;
      const path = target.split('#', 1)[0].split('?', 1)[0];
      if (!path) continue;
      const destination = normalize(resolve(dirname(file), decodeURIComponent(path)));
      if (!destination.startsWith(root) || !existsSync(destination)) {
        missing.push(`${file.slice(root.length + 1)} -> ${target}`);
      }
    }
  }

  assert.deepEqual(missing, []);
});

test('documentation map records the audited public engineering-source classes', () => {
  const audit = readFileSync(join(root, 'docs', 'PUBLICATION_BOUNDARY.md'), 'utf8');
  for (const path of ['scripts/', 'tests/', 'workers/', 'docs/', 'package manifests and lockfiles']) {
    assert.ok(audit.includes(path), path);
  }
  assert.equal(statSync(join(root, 'docs', 'README.md')).isFile(), true);
});
