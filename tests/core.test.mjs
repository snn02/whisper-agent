import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { buildDockerArgs, checkGpu, listMedia, transcribeProject } from '../src/core.mjs';

function fakeSpawn(response, calls) {
  return (command, args) => {
    calls.push({ command, args });
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    queueMicrotask(() => {
      child.stdout.end(response.stdout ?? '');
      child.stderr.end(response.stderr ?? '');
      child.emit('close', response.code ?? 0);
    });
    return child;
  };
}

test('diarization is opt-in and token is forwarded by environment name only', () => {
  const options = { command: 'transcribe', projectDir: '/project', outputDir: '/out', outputFormat: 'txt' };
  const plain = buildDockerArgs(options);
  assert.equal(plain.includes('--diarize'), false);
  assert.equal(plain.includes('HF_TOKEN'), false);
  const args = buildDockerArgs({ ...options, diarize: true });
  assert.ok(args.includes('--diarize'));
  assert.equal(args[args.indexOf('HF_TOKEN') - 1], '--env');
  assert.ok(args.indexOf('HF_TOKEN') < args.indexOf('whisper-agent:torch2.13-cu132'));
});

test('Windows project path with spaces and Cyrillic stays one Docker mount argument', () => {
  const args = buildDockerArgs({
    command: 'transcribe',
    projectDir: 'C:\\Users\\SAWA\\Проект с пробелом',
    outputDir: 'C:\\Users\\SAWA\\Вывод',
    outputFormat: 'txt',
    model: 'small', language: 'ru', imageTag: 'whisper-agent:torch2.13-cu132', overwrite: false,
  }, 'win32');
  assert.ok(args.includes('type=bind,source=C:\\Users\\SAWA\\Проект с пробелом,target=/input,readonly'));
  assert.ok(args.includes('type=bind,source=C:\\Users\\SAWA\\Вывод,target=/output'));
  assert.ok(args.includes('type=volume,source=whisper-agent-models,target=/models'));
  assert.ok(args.includes('--gpus'));
  assert.ok(args.includes('all'));
  assert.ok(args.includes('--rm'));
});
test('diarization rejects subtitle and JSON formats before launching Docker', async () => {
  const options = { command: 'transcribe', projectDir: '/project', outputDir: '/out', outputFormat: 'txt', diarize: true };
  assert.ok(buildDockerArgs(options).includes('--diarize'));
  for (const outputFormat of ['srt', 'vtt', 'tsv', 'json', 'all']) {
    assert.throws(() => buildDockerArgs({ ...options, outputFormat }), /diarization.*txt/i);
  }
  const root = mkdtempSync(path.join(tmpdir(), 'whisper-format-'));
  const calls = [];
  await assert.rejects(transcribeProject({ projectDir: root, outputDir: path.join(root, 'out'), outputFormat: 'srt', diarize: true }, {
    spawn: fakeSpawn({ stdout: '{}' }, calls), env: { WHISPER_LOG_PATH: path.join(root, 'runs.jsonl') },
  }), /diarization.*txt/i);
  assert.equal(calls.length, 0);
});
test('Docker image and bind paths cannot inject mount or run options', () => {
  const options = { command: 'transcribe', projectDir: '/tmp/project', outputDir: '/tmp/results', outputFormat: 'txt' };
  assert.throws(() => buildDockerArgs({ ...options, imageTag: '--privileged' }), /image tag/i);
  assert.throws(() => buildDockerArgs({ ...options, projectDir: '/tmp/with,comma' }), /comma/i);
});

test('save choices are required and output cannot equal project', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'whisper-core-'));
  await assert.rejects(transcribeProject({ projectDir: root, outputDir: '', outputFormat: 'txt' }), /output directory/i);
  await assert.rejects(transcribeProject({ projectDir: root, outputDir: path.join(root, 'out'), outputFormat: '' }), /output format/i);
  await assert.rejects(transcribeProject({ projectDir: root, outputDir: path.join(root, 'out'), outputFormat: 'jsonl' }), /output format/i);
  await assert.rejects(transcribeProject({ projectDir: root, outputDir: root, outputFormat: 'txt' }), /different/i);
});

test('listMedia returns worker candidates without requesting GPU', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'whisper-core-'));
  const calls = [];
  const result = await listMedia({ projectDir: root }, {
    spawn: fakeSpawn({ stdout: JSON.stringify({ files: ['Записи/clip.wav'] }) }, calls),
  });
  assert.deepEqual(result, { files: ['Записи/clip.wav'] });
  assert.equal(calls[0].command, 'docker');
  assert.equal(calls[0].args.includes('--gpus'), false);
});

test('partial transcription logs files, duration and error without transcript text', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'whisper-core-'));
  const project = path.join(root, 'project');
  mkdirSync(project);
  const out = path.join(project, 'results');
  const logPath = path.join(root, 'logs', 'runs.jsonl');
  const calls = [];
  const workerSummary = {
    status: 'partial', model: 'small', language: 'ru', total_duration_ms: 11,
    files: [
      { input: 'good.wav', outputs: ['good.wav/transcript.txt'], duration_ms: 7, error: null },
      { input: 'bad.wav', outputs: [], duration_ms: 4, error: 'decode failed' },
    ],
  };
  const summary = await transcribeProject({ projectDir: project, outputDir: out, outputFormat: 'txt' }, {
    spawn: fakeSpawn({ code: 1, stdout: JSON.stringify(workerSummary) }, calls),
    env: { WHISPER_LOG_PATH: logPath },
  });
  const log = readFileSync(logPath, 'utf8');
  assert.equal(summary.status, 'partial');
  assert.equal(JSON.parse(log).files[1].error, 'decode failed');
  assert.ok(JSON.parse(log).total_duration_ms >= 0);
  assert.equal(log.includes('секретный текст'), false);
  assert.ok(calls[0].args.includes('--exclude-relative'));
  assert.ok(calls[0].args.includes('results'));
});

test('Docker startup failure is logged and returned as an error', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'whisper-core-'));
  const project = path.join(root, 'project');
  mkdirSync(project);
  const logPath = path.join(root, 'runs.jsonl');
  await assert.rejects(transcribeProject({ projectDir: project, outputDir: path.join(root, 'out'), outputFormat: 'txt' }, {
    spawn: fakeSpawn({ code: 125, stderr: 'GPU unavailable' }, []),
    env: { WHISPER_LOG_PATH: logPath },
  }), /GPU unavailable/);
  const record = JSON.parse(readFileSync(logPath, 'utf8'));
  assert.equal(record.status, 'error');
  assert.equal(record.error, 'GPU unavailable');
  assert.deepEqual(record.files, []);
});

test('GPU check returns device name and fails when CUDA is unavailable', async () => {
  const calls = [];
  const device = await checkGpu({}, { spawn: fakeSpawn({ stdout: 'NVIDIA GeForce RTX 5060 Laptop GPU\n' }, calls) });
  assert.equal(device, 'NVIDIA GeForce RTX 5060 Laptop GPU');
  assert.ok(calls[0].args.includes('--gpus'));
  await assert.rejects(checkGpu({}, { spawn: fakeSpawn({ code: 1, stderr: 'CUDA unavailable' }, []) }), /CUDA unavailable/);
});
