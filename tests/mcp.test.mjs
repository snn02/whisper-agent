import test from 'node:test';
import assert from 'node:assert/strict';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { createServer } from '../src/mcp.mjs';

async function withClient(deps, callback) {
  const server = createServer(deps);
  const client = new Client({ name: 'whisper-test', version: '1.0.0' });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  try { await callback(client); } finally { await Promise.all([client.close(), server.close()]); }
}

test('server exposes exactly list_media and transcribe_project with required save choices', async () => {
  await withClient({}, async client => {
    const { tools } = await client.listTools();
    assert.deepEqual(tools.map(item => item.name).sort(), ['list_media', 'transcribe_project']);
    const transcribe = tools.find(item => item.name === 'transcribe_project');
    assert.deepEqual(transcribe.inputSchema.required.sort(), ['output_dir', 'output_format', 'project_dir']);
    assert.match(transcribe.description, /ask|спрос/i);
  });
});

test('list_media maps project and image to host and returns filenames', async () => {
  let received;
  await withClient({ listMedia: async options => { received = options; return { files: ['запись.wav'] }; } }, async client => {
    const result = await client.callTool({ name: 'list_media', arguments: { project_dir: 'C:\\Project', image_tag: 'custom:cuda' } });
    assert.deepEqual(received, { projectDir: 'C:\\Project', imageTag: 'custom:cuda' });
    assert.deepEqual(JSON.parse(result.content[0].text), { files: ['запись.wav'] });
  });
});

test('missing output choices are rejected before host call', async () => {
  let called = false;
  await withClient({ transcribeProject: async () => { called = true; } }, async client => {
    const result = await client.callTool({ name: 'transcribe_project', arguments: { project_dir: 'C:\\Project' } });
    assert.equal(result.isError, true);
    const unsupported = await client.callTool({ name: 'transcribe_project', arguments: { project_dir: 'C:\\Project', output_dir: 'C:\\Results', output_format: 'jsonl' } });
    assert.equal(unsupported.isError, true);
    assert.equal(called, false);
  });
});

test('transcribe_project fixes the MCP model to small and returns metadata without text', async () => {
  let received;
  await withClient({ transcribeProject: async options => {
    received = options;
    return { status: 'partial', files: [{ input: 'a.wav', duration_ms: 1200, error: null, outputs: ['a.wav/transcript.txt'] }, { input: 'b.wav', duration_ms: 100, error: 'bad media', outputs: [] }] };
  } }, async client => {
    const result = await client.callTool({ name: 'transcribe_project', arguments: {
      project_dir: 'C:\\Project', output_dir: 'C:\\Results', output_format: 'txt', language: 'ru', image_tag: 'custom:cuda', overwrite: true,
    } });
    assert.deepEqual(received, { projectDir: 'C:\\Project', outputDir: 'C:\\Results', outputFormat: 'txt', model: 'small', language: 'ru', imageTag: 'custom:cuda', overwrite: true });
    assert.equal(result.isError, true);
    assert.equal(JSON.parse(result.content[0].text).status, 'partial');
  });
});

test('transcribe_project rejects an agent-selected model before starting Docker', async () => {
  let called = false;
  await withClient({ transcribeProject: async () => { called = true; } }, async client => {
    const result = await client.callTool({ name: 'transcribe_project', arguments: {
      project_dir: 'C:\\Project', output_dir: 'C:\\Results', output_format: 'txt', model: 'medium',
    } });
    assert.equal(result.isError, true);
    assert.equal(called, false);
  });
});

test('host error is reported as a tool error', async () => {
  await withClient({ listMedia: async () => { throw new Error('Docker unavailable'); } }, async client => {
    const result = await client.callTool({ name: 'list_media', arguments: { project_dir: 'C:\\Project' } });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /Docker unavailable/);
  });
});
