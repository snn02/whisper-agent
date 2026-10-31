import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const [runtime, project, outputRoot, reportPath] = process.argv.slice(2);
const client = new Client({ name: 'txt-validation', version: '1.0.0' });
const transport = new StdioClientTransport({ command: process.execPath, args: [path.join(runtime, 'src', 'mcp.mjs')], env: process.env, stderr: 'pipe' });
transport.stderr?.on('data', () => {});
try {
  await client.connect(transport);
  const listing = await client.callTool({ name: 'list_media', arguments: { project_dir: project } });
  assert.deepEqual(JSON.parse(listing.content[0].text).files, ['russian-synthetic.wav']);
  for (const output_format of ['srt', 'json', 'all']) {
    const invalid = await client.callTool({ name: 'transcribe_project', arguments: { project_dir: project, output_dir: outputRoot, output_format, diarize: true } });
    assert.equal(invalid.isError, true);
    assert.match(invalid.content[0].text, /diarization.*txt/i);
  }
  assert.equal(fs.existsSync(process.env.WHISPER_LOG_PATH), false, 'Invalid format reached host processing');
  const request = { name: 'transcribe_project', arguments: { project_dir: project, output_dir: outputRoot, output_format: 'txt', diarize: true } };
  const response = await client.callTool(request, undefined, { timeout: 600000 });
  const summary = JSON.parse(response.content[0].text);
  if (response.isError || summary.status !== 'success') {
    fs.writeFileSync(reportPath, JSON.stringify({ status: 'error', summary }, null, 2));
    throw new Error('MCP validation failed; metadata report saved');
  }
  const directory = path.join(outputRoot, 'russian-synthetic.wav');
  assert.deepEqual(fs.readdirSync(directory), ['transcript.txt']);
  assert.equal(summary.files[0].outputs.length, 1);
  const file = path.join(directory, 'transcript.txt');
  const before = fs.readFileSync(file, 'utf8');
  const blocks = before.trim().split(/\r?\n\r?\n/);
  let previous = null;
  for (const block of blocks) {
    const match = /^\[\d+:\d{2}(?::\d{2})?\] (Speaker(?:\d+|Unknown)): (.+)$/.exec(block);
    assert.ok(match, 'Invalid timestamped TXT block');
    assert.ok(match[1] === 'SpeakerUnknown' || match[1] !== previous, 'Adjacent same-speaker blocks were not merged');
    previous = match[1];
  }
  assert.ok(before.includes('Speaker1:'), 'No speaker identified on synthetic voice');
  assert.ok(before.toLowerCase().includes('провер'), 'Expected test speech missing');
  let log = fs.readFileSync(process.env.WHISPER_LOG_PATH, 'utf8');
  for (const block of blocks) {
    const speech = block.replace(/^\[[^\]]+\] Speaker(?:\d+|Unknown): /, '');
    assert.ok(!log.includes(speech), 'Transcript leaked into log');
    assert.ok(!JSON.stringify(response).includes(speech), 'Transcript leaked into MCP response');
  }
  const duplicate = await client.callTool(request, undefined, { timeout: 60000 });
  assert.equal(duplicate.isError, true);
  assert.ok(fs.readFileSync(file, 'utf8') === before, 'Existing result was overwritten');
  log = fs.readFileSync(process.env.WHISPER_LOG_PATH, 'utf8');
  assert.equal(log.trim().split('\n').map(JSON.parse).filter(entry => entry.status === 'success').length, 1);
  assert.ok(!process.env.HF_TOKEN || !log.includes(process.env.HF_TOKEN), 'Token leaked into log');
  const report = { status: 'ok', platform: 'Windows', transport: 'MCP stdio', input: 'synthetic Russian TTS, one voice', txt_only: true, merged_blocks: blocks.length, incompatible_formats_rejected_before_host: true, successful_transcriptions: 1, no_overwrite: true, metadata_only: true, token_not_logged: true };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally { await client.close(); }
