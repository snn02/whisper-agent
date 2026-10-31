import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { installSkill, skillDestination } from '../scripts/install-skill.mjs';

function temporary(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'speaker-skill-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test('standalone project installation copies only the portable skill and refuses replacement', t => {
  const root = temporary(t);
  const project = path.join(root, 'Проект с пробелом');
  fs.mkdirSync(project);
  const options = { scope: 'project', projectDir: project };
  const installed = installSkill(options);
  assert.equal(installed, path.join(project, '.agents', 'skills', 'name-speakers'));
  assert.ok(fs.existsSync(path.join(installed, 'SKILL.md')));
  assert.equal(fs.existsSync(path.join(project, 'node_modules')), false);
  assert.equal(fs.existsSync(path.join(project, 'Dockerfile')), false);
  fs.writeFileSync(path.join(installed, 'local.txt'), 'keep');
  assert.throws(() => installSkill(options), /already exists/i);
  assert.equal(fs.readFileSync(path.join(installed, 'local.txt'), 'utf8'), 'keep');
  installSkill({ ...options, overwrite: true });
  assert.equal(fs.existsSync(path.join(installed, 'local.txt')), false);
});

test('global and explicit agent directory resolve independently of transcription runtime', t => {
  const root = temporary(t);
  assert.equal(skillDestination({ scope: 'global', homeDir: root }), path.join(root, '.agents', 'skills', 'name-speakers'));
  const skillsDir = path.join(root, 'agent', 'skills');
  assert.equal(installSkill({ scope: 'custom', skillsDir }), path.join(skillsDir, 'name-speakers'));
  assert.throws(() => skillDestination({ scope: 'project' }), /project/i);
  assert.throws(() => skillDestination({ scope: 'custom', skillsDir: 'relative' }), /absolute/i);
});

test('installer refuses a destination redirected by a symbolic link', t => {
  const root = temporary(t);
  const outside = path.join(root, 'outside');
  const project = path.join(root, 'project');
  fs.mkdirSync(project);
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(project, '.agents'), 'junction');
  assert.throws(() => installSkill({ scope: 'project', projectDir: project }), /symlink/i);
  assert.deepEqual(fs.readdirSync(outside), []);
});
