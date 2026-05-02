import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { validateDataDir } from '../validate-data';

interface SessionFiles {
  metadata?: object;
  qa_pairs?: object;
  summary?: object;
  topics?: object;
}

let tmpDir: string;
let dataDir: string;
let lawsPath: string;
let consoleLogSpy: ReturnType<typeof vi.spyOn>;
let consoleErrorSpy: ReturnType<typeof vi.spyOn>;
let consoleWarnSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'validate-data-test-'));
  dataDir = path.join(tmpDir, 'data');
  lawsPath = path.join(dataDir, 'laws', 'laws.json');
  fs.mkdirSync(path.join(dataDir, 'laws'), { recursive: true });
  fs.writeFileSync(
    lawsPath,
    JSON.stringify({ bills: [{ id: 'law_001' }, { id: 'law_002' }] }),
  );
  consoleLogSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
  consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  consoleLogSpy.mockRestore();
  consoleErrorSpy.mockRestore();
  consoleWarnSpy.mockRestore();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function writeSession(slug: string, files: SessionFiles): void {
  const sessionDir = path.join(dataDir, 'shugiin/2026/04/09', slug);
  fs.mkdirSync(sessionDir, { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    fs.writeFileSync(path.join(sessionDir, `${name}.json`), JSON.stringify(content));
  }
}

const goodSession: SessionFiles = {
  metadata: {
    chamber: 'shugiin',
    session_id: '56149',
    date: '2026-04-09',
    committee: '本会議',
    session_kind: 'representative_questions',
    duration: '',
    hls_url: 'https://example.com/x.m3u8',
    source_url: 'https://example.com/x',
    processed_at: '',
    whisper_model: '',
    llm_model: '',
    speakers: [
      {
        name: '高市早苗',
        affiliation: '内閣総理大臣',
        role: '答弁者',
        start_seconds: 0,
        start_time: '13:00',
        duration_minutes: 5,
      },
    ],
  },
  qa_pairs: {
    pairs: [
      {
        id: 'qa_001',
        segment_index: 0,
        topic: 't',
        question: { speaker: 'x', party: 'y', summary: 's', full_text: 'f', intent: 'other' },
        answer: {
          speaker: 'z',
          role: '答弁者',
          summary: 's',
          full_text: 'f'.repeat(40),
          evasion_score: 0.1,
          has_commitment: false,
          commitment_text: '',
        },
        follow_up_ids: [],
        related_law_ids: ['law_001'],
        video_url: '',
      },
    ],
  },
  summary: {
    session_summary: '...',
    key_topics: ['A'],
    key_commitments: [
      { speaker: 'x', role: '答弁者', text: 'commit', topic: 'A', qa_id: 'qa_001' },
    ],
    related_laws: [{ law_id: 'law_001', qa_ids: ['qa_001'] }],
  },
  topics: {
    topics: [
      {
        name: 'A',
        description: 'd',
        related_qa_ids: ['qa_001'],
        related_speakers: [],
      },
    ],
  },
};

describe('validateDataDir', () => {
  it('clean session reports zero errors', () => {
    writeSession('56149_本会議', goodSession);
    const { errors, warnings } = validateDataDir(dataDir, lawsPath);
    expect(errors).toBe(0);
    expect(warnings).toBe(0);
  });

  it('R1: topics.related_qa_ids referencing unknown qa_id is flagged', () => {
    const broken = structuredClone(goodSession);
    broken.topics = {
      topics: [
        { name: 'A', description: 'd', related_qa_ids: ['qa_999'], related_speakers: [] },
      ],
    };
    writeSession('56149_本会議', broken);
    const { errors } = validateDataDir(dataDir, lawsPath);
    expect(errors).toBeGreaterThan(0);
    const calls = consoleLogSpy.mock.calls.flat().join('\n');
    expect(calls).toContain('R1');
  });

  it('R3: related_laws.qa_ids referencing unknown qa_id is flagged', () => {
    const broken = structuredClone(goodSession);
    (broken.summary as any).related_laws = [{ law_id: 'law_001', qa_ids: ['qa_999'] }];
    writeSession('56149_本会議', broken);
    const { errors } = validateDataDir(dataDir, lawsPath);
    expect(errors).toBeGreaterThan(0);
    const calls = consoleLogSpy.mock.calls.flat().join('\n');
    expect(calls).toContain('R3');
  });

  it('R4: related_laws.law_id outside laws.json is flagged', () => {
    const broken = structuredClone(goodSession);
    (broken.summary as any).related_laws = [{ law_id: 'law_999', qa_ids: ['qa_001'] }];
    writeSession('56149_本会議', broken);
    const { errors } = validateDataDir(dataDir, lawsPath);
    expect(errors).toBeGreaterThan(0);
    const calls = consoleLogSpy.mock.calls.flat().join('\n');
    expect(calls).toContain('R4');
  });

  it('R5: key_topics outside topics[].name is flagged', () => {
    const broken = structuredClone(goodSession);
    (broken.summary as any).key_topics = ['存在しないトピック'];
    writeSession('56149_本会議', broken);
    const { errors } = validateDataDir(dataDir, lawsPath);
    expect(errors).toBeGreaterThan(0);
    const calls = consoleLogSpy.mock.calls.flat().join('\n');
    expect(calls).toContain('R5');
  });

  it('R6: qa_pairs.related_law_ids referencing unknown law_id is flagged', () => {
    const broken = structuredClone(goodSession);
    (broken.qa_pairs as any).pairs[0].related_law_ids = ['law_999'];
    writeSession('56149_本会議', broken);
    const { errors } = validateDataDir(dataDir, lawsPath);
    expect(errors).toBeGreaterThan(0);
    const calls = consoleLogSpy.mock.calls.flat().join('\n');
    expect(calls).toContain('R6');
  });

  it('R7: unknown session_kind is a warning, not an error', () => {
    const broken = structuredClone(goodSession);
    (broken.metadata as any).session_kind = 'unknown_kind';
    writeSession('56149_本会議', broken);
    const { errors, warnings } = validateDataDir(dataDir, lawsPath);
    expect(errors).toBe(0);
    expect(warnings).toBeGreaterThan(0);
  });

  it('returns 1 error when DATA_DIR does not exist', () => {
    const { errors } = validateDataDir('/no/such/path', lawsPath);
    expect(errors).toBe(1);
  });
});
