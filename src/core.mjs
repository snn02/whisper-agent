import { spawn as nativeSpawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';

const DEFAULT_IMAGE = 'whisper-agent:torch2.13-cu132';
const MODEL_VOLUME = 'whisper-agent-models';

function pathsFor(platform) {
  return platform === 'win32' ? path.win32 : path.posix;
}

function requireAbsoluteDirectory(value, label, platform, mustExist = true) {
  if (!value || typeof value !== 'string') throw new Error(`${label} is required`);
  const pathApi = pathsFor(platform);
  if (!pathApi.isAbsolute(value)) throw new Error(`${label} must be an absolute path`);
  const normalized = pathApi.normalize(value);
  if (mustExist && !fs.statSync(normalized, { throwIfNoEntry: false })?.isDirectory()) {
    throw new Error(`${label} does not exist: ${normalized}`);
  }
  return normalized;
}

function excludedRelative(projectDir, outputDir, platform) {
  if (!outputDir) return null;
  const pathApi = pathsFor(platform);
  const relative = pathApi.relative(projectDir, outputDir);
  if (!relative || relative === '..' || relative.startsWith(`..${pathApi.sep}`) || pathApi.isAbsolute(relative)) return null;
  return relative.split(pathApi.sep).join('/');
}

export function buildDockerArgs(options, platform = process.platform) {
  const {
    command, projectDir, outputDir, outputFormat,
    model = 'small', language = 'ru', imageTag = DEFAULT_IMAGE, overwrite = false,
  } = options;
  if (typeof imageTag !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._/:@-]*$/.test(imageTag)) {
    throw new Error('Docker image tag is invalid');
  }
  for (const mountPath of [projectDir, outputDir].filter(Boolean)) {
    if (/[\x00-\x1f,]/.test(mountPath)) throw new Error('Docker mount path cannot contain a comma or control character');
  }
  const args = ['run', '--rm'];
  if (command === 'transcribe' || command === 'check') args.push('--gpus', 'all');
  if (command !== 'check') {
    args.push('--mount', `type=bind,source=${projectDir},target=/input,readonly`);
    if (command === 'transcribe') args.push('--mount', `type=bind,source=${outputDir},target=/output`);
    args.push('--mount', `type=volume,source=${MODEL_VOLUME},target=/models`);
  }
  args.push(imageTag);
  if (command === 'check') return [...args, 'python', '-c', 'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'];
  args.push('python', '/app/worker.py', command, '--project', '/input');
  const exclusion = excludedRelative(projectDir, outputDir, platform);
  if (exclusion) args.push('--exclude-relative', exclusion);
  if (command === 'transcribe') {
    args.push('--output', '/output', '--format', outputFormat, '--model', model, '--language', language);
    if (overwrite) args.push('--overwrite');
  }
  return args;
}

function runDocker(args, deps = {}) {
  const launch = deps.spawn ?? nativeSpawn;
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = launch('docker', args, { shell: false, windowsHide: true });
    } catch (error) {
      reject(error);
      return;
    }
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk.toString(); });
    child.stderr.on('data', chunk => { stderr += chunk.toString(); });
    child.on('error', reject);
    child.on('close', code => resolve({ code, stdout, stderr }));
  });
}

function parseWorkerResult(processResult) {
  try {
    const result = JSON.parse(processResult.stdout.trim());
    if (result && typeof result === 'object') return result;
  } catch {}
  throw new Error(processResult.stderr.trim() || `Docker exited with code ${processResult.code}`);
}

function logPath(env, platform) {
  if (env.WHISPER_LOG_PATH) return env.WHISPER_LOG_PATH;
  if (platform === 'win32') {
    if (!env.LOCALAPPDATA) throw new Error('LOCALAPPDATA is required for the default log path');
    return path.win32.join(env.LOCALAPPDATA, 'WhisperAgent', 'runs.jsonl');
  }
  return path.join(env.XDG_STATE_HOME ?? path.join(os.homedir(), '.local', 'state'), 'whisper-agent', 'runs.jsonl');
}

function appendLog(record, deps, platform) {
  const file = logPath(deps.env ?? process.env, platform);
  fs.mkdirSync(pathsFor(platform).dirname(file), { recursive: true });
  fs.appendFileSync(file, `${JSON.stringify(record)}\n`, 'utf8');
}

export async function listMedia({ projectDir, imageTag = DEFAULT_IMAGE }, deps = {}) {
  const platform = deps.platform ?? process.platform;
  const project = requireAbsoluteDirectory(projectDir, 'Project directory', platform);
  const result = parseWorkerResult(await runDocker(buildDockerArgs({ command: 'list', projectDir: project, imageTag }, platform), deps));
  if (!Array.isArray(result.files)) throw new Error(result.error || 'Invalid media list from container');
  return { files: result.files };
}

export async function checkGpu({ imageTag = DEFAULT_IMAGE } = {}, deps = {}) {
  const processResult = await runDocker(buildDockerArgs({ command: 'check', imageTag }), deps);
  if (processResult.code !== 0) {
    throw new Error(processResult.stderr.trim() || `GPU check failed with code ${processResult.code}`);
  }
  return processResult.stdout.trim();
}

export async function transcribeProject(options, deps = {}) {
  const platform = deps.platform ?? process.platform;
  const {
    projectDir, outputDir, outputFormat,
    model = 'small', language = 'ru', imageTag = DEFAULT_IMAGE, overwrite = false,
  } = options;
  const project = requireAbsoluteDirectory(projectDir, 'Project directory', platform);
  const output = requireAbsoluteDirectory(outputDir, 'Output directory', platform, false);
  if (!outputFormat || !['txt', 'srt', 'vtt', 'tsv', 'json', 'all'].includes(outputFormat)) {
    throw new Error('Output format is required and must be txt, srt, vtt, tsv, json or all');
  }
  const pathApi = pathsFor(platform);
  if (pathApi.normalize(project).toLowerCase() === pathApi.normalize(output).toLowerCase()) {
    throw new Error('Output directory must be different from project root');
  }
  fs.mkdirSync(output, { recursive: true });
  const started = performance.now();
  const timestamp = new Date().toISOString();
  let record;
  let failure;
  try {
    const processResult = await runDocker(buildDockerArgs({
      command: 'transcribe', projectDir: project, outputDir: output, outputFormat,
      model, language, imageTag, overwrite,
    }, platform), deps);
    const worker = parseWorkerResult(processResult);
    const files = (worker.files ?? []).map(file => ({
      input: file.input,
      outputs: (file.outputs ?? []).map(relative => pathApi.join(output, ...relative.split('/'))),
      duration_ms: file.duration_ms,
      error: file.error ?? null,
    }));
    record = {
      timestamp, project_dir: project, output_dir: output, output_format: outputFormat,
      image_tag: imageTag, model, language, status: worker.status ?? 'error', files,
      total_duration_ms: Math.round(performance.now() - started),
      error: worker.error ?? null,
    };
  } catch (error) {
    failure = error;
    record = {
      timestamp, project_dir: project, output_dir: output, output_format: outputFormat,
      image_tag: imageTag, model, language, status: 'error', files: [],
      total_duration_ms: Math.round(performance.now() - started), error: error.message,
    };
  }
  appendLog(record, deps, platform);
  if (failure) throw failure;
  return record;
}
