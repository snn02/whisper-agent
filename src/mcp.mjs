#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { listMedia as defaultListMedia, transcribeProject as defaultTranscribeProject } from './core.mjs';

const packageVersion = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')).version;

function response(value, isError = false) {
  return { content: [{ type: 'text', text: JSON.stringify(value) }], isError };
}

export function createServer({ listMedia = defaultListMedia, transcribeProject = defaultTranscribeProject } = {}) {
  const server = new McpServer({ name: 'whisper-agent-local', version: packageVersion });
  server.registerTool('list_media', {
    description: 'List supported audio and video files recursively in an absolute project directory. This does not transcribe files. Use the current project root unless the user chose another directory.',
    inputSchema: {
      project_dir: z.string().min(1).describe('Absolute Windows or Linux path to the project'),
      image_tag: z.string().optional().describe('Optional Docker image tag'),
    },
  }, async ({ project_dir, image_tag }) => {
    try { return response(await listMedia({ projectDir: project_dir, imageTag: image_tag })); }
    catch (error) { return response({ error: error.message }, true); }
  });
  server.registerTool('transcribe_project', {
    description: 'Transcribe all supported media in a project with local GPU Whisper using the fixed small model. Before calling, use the user request or project/user rules to determine output_dir and output_format. If either is absent, ask the user where and how to save; do not choose defaults. Other models require a user-run CLI command. The result reports paths, durations and errors. Full transcript text is saved only to result files. A partial result means some files failed.',
    inputSchema: {
      project_dir: z.string().min(1).describe('Absolute Windows or Linux path to the project'),
      output_dir: z.string().min(1).describe('Absolute directory for transcript files; ask user if not specified by request or rules'),
      output_format: z.enum(['txt', 'srt', 'vtt', 'tsv', 'json', 'all']).describe('Transcript format; ask user if not specified by request or rules'),
      model: z.literal('small').optional().describe('MCP permits only small; other models require a user-run CLI command'),
      language: z.string().optional().describe('Spoken language, default ru'),
      image_tag: z.string().optional().describe('Optional Docker image tag for CUDA experiments'),
      overwrite: z.boolean().optional().describe('Replace existing transcript files; default false'),
    },
  }, async ({ project_dir, output_dir, output_format, language, image_tag, overwrite }) => {
    try {
      const result = await transcribeProject({
        projectDir: project_dir, outputDir: output_dir, outputFormat: output_format,
        model: 'small', language, imageTag: image_tag, overwrite,
      });
      return response(result, result.status !== 'success');
    } catch (error) { return response({ error: error.message }, true); }
  });
  return server;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const server = createServer();
  server.connect(new StdioServerTransport()).catch(error => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
