#!/usr/bin/env node
// Standalone installer: only Node built-ins; npm ci and the service are unnecessary.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const source = fileURLToPath(new URL('../skills/name-speakers/', import.meta.url));

function absolute(value, label) {
  if (!value || !path.isAbsolute(value)) throw new Error(`${label} must be an absolute path`);
  return path.resolve(value);
}

export function skillDestination({ scope, projectDir, skillsDir, homeDir = os.homedir() }) {
  let base;
  if (scope === 'project') {
    const project = absolute(projectDir, 'Project directory');
    if (!fs.statSync(project, { throwIfNoEntry: false })?.isDirectory()) throw new Error('Project directory does not exist');
    base = path.join(project, '.agents', 'skills');
  } else if (scope === 'global') {
    base = path.join(absolute(homeDir, 'Home directory'), '.agents', 'skills');
  } else if (scope === 'custom') {
    base = absolute(skillsDir, 'Skills directory');
  } else {
    throw new Error('Choose --scope project, global or custom');
  }
  return path.join(base, 'name-speakers');
}

function rejectSymlinks(target) {
  for (let current = target; ; current = path.dirname(current)) {
    if (fs.lstatSync(current, { throwIfNoEntry: false })?.isSymbolicLink()) throw new Error(`Skill destination contains a symlink: ${current}`);
    if (current === path.dirname(current)) break;
  }
}

export function installSkill(options) {
  const target = skillDestination(options);
  rejectSymlinks(target);
  const relative = path.relative(path.resolve(source), target);
  const reverse = path.relative(target, path.resolve(source));
  const inside = value => !value || (!value.startsWith(`..${path.sep}`) && value !== '..' && !path.isAbsolute(value));
  if (inside(relative) || inside(reverse)) throw new Error('Installation must not replace or contain the source skill');
  if (fs.existsSync(target) && !options.overwrite) throw new Error(`Skill already exists: ${target}; use --overwrite only to explicitly replace it`);
  const parent = path.dirname(target);
  fs.mkdirSync(parent, { recursive: true });
  const staging = fs.mkdtempSync(path.join(parent, '.name-speakers-'));
  const payload = path.join(staging, 'skill');
  const backup = path.join(staging, 'previous');
  let backedUp = false;
  try {
    fs.cpSync(source, payload, { recursive: true, filter: entry => {
      if (fs.lstatSync(entry).isSymbolicLink()) throw new Error('Source skill must not contain symlinks');
      return true;
    } });
    if (!fs.statSync(path.join(payload, 'SKILL.md')).isFile()) throw new Error('Skill source is missing SKILL.md');
    rejectSymlinks(target);
    if (fs.existsSync(target)) {
      if (!options.overwrite) throw new Error(`Skill already exists: ${target}`);
      fs.renameSync(target, backup);
      backedUp = true;
    }
    fs.renameSync(payload, target);
  } catch (error) {
    if (backedUp) {
      // Keep the backup if another process occupies the destination during recovery.
      if (fs.existsSync(target)) throw new Error(`Installation failed; previous skill retained at ${backup}`);
      fs.renameSync(backup, target);
    }
    fs.rmSync(staging, { recursive: true, force: true });
    throw error;
  }
  fs.rmSync(staging, { recursive: true, force: true });
  return target;
}

function main() {
  const { values } = parseArgs({ options: {
    scope: { type: 'string' }, 'project-dir': { type: 'string' }, 'skills-dir': { type: 'string' },
    overwrite: { type: 'boolean' }, help: { type: 'boolean' },
  } });
  if (values.help) {
    process.stdout.write('Install only name-speakers (no Docker or npm dependencies).\nnode scripts/install-skill.mjs --scope project --project-dir ABSOLUTE_PATH\nnode scripts/install-skill.mjs --scope global\nnode scripts/install-skill.mjs --scope custom --skills-dir ABSOLUTE_SKILLS_DIRECTORY\nOptional: --overwrite explicitly replaces an installed skill.\n');
    return;
  }
  const installed = installSkill({ scope: values.scope, projectDir: values['project-dir'], skillsDir: values['skills-dir'], overwrite: values.overwrite });
  process.stdout.write(`Installed skill: ${installed}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
