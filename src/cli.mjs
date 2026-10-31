#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { checkGpu, listMedia, transcribeProject } from './core.mjs';

const usage = `Usage: whisper-agent <command> [options]

Commands:
  check                                 Check CUDA GPU in the image
  list --project DIR                    List media in a project
  transcribe --project DIR --output DIR --format FORMAT
                                        Transcribe media to txt, srt, vtt, tsv, json or all

Options:
  --model NAME      Whisper model (default: small)
  --language CODE   Spoken language (default: ru)
  --image TAG       Docker image (default: whisper-agent:torch2.13-cu132)
  --overwrite       Replace existing result files
  --diarize         Add transcript.diarized.json with SpeakerN labels (requires pyannote weights)
`;

async function main(argv) {
  if (argv.length === 0 || argv[0] === '--help' || argv[0] === '-h') {
    process.stdout.write(usage);
    return 0;
  }
  const command = argv[0];
  if (!['check', 'list', 'transcribe'].includes(command)) throw new Error(`Unknown command: ${command}`);
  const { values } = parseArgs({
    args: argv.slice(1),
    options: {
      project: { type: 'string' },
      output: { type: 'string' },
      format: { type: 'string' },
      model: { type: 'string' },
      language: { type: 'string' },
      image: { type: 'string' },
      overwrite: { type: 'boolean' },
      diarize: { type: 'boolean' },
    },
  });
  if (command === 'check') {
    const device = await checkGpu({ imageTag: values.image });
    process.stdout.write(`${JSON.stringify({ cuda: true, device })}\n`);
    return 0;
  }
  if (command === 'list') {
    const result = await listMedia({ projectDir: values.project, imageTag: values.image });
    process.stdout.write(`${JSON.stringify(result)}\n`);
    return 0;
  }
  const result = await transcribeProject({
    projectDir: values.project,
    outputDir: values.output,
    outputFormat: values.format,
    model: values.model,
    language: values.language,
    imageTag: values.image,
    overwrite: values.overwrite ?? false,
    diarize: values.diarize ?? false,
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
  return result.status === 'success' ? 0 : 1;
}

main(process.argv.slice(2)).then(
  code => { process.exitCode = code; },
  error => { process.stderr.write(`${error.message}\n`); process.exitCode = 2; },
);
