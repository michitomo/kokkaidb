import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { generateApi, type IndexEntry } from '../generate-api';

const FIXTURES_DIR = path.resolve(__dirname, '../../tests/fixtures/data');

describe('generateApi', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kokkaidb-test-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('フィクスチャデータから全ファイルを生成する', () => {
    generateApi(FIXTURES_DIR, tmpDir);

    expect(fs.existsSync(path.join(tmpDir, 'index.json'))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, 'speakers.json'))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, 'parties.json'))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, 'topics.json'))).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, 'committees.json'))).toBe(true);
  });

  it('index.json にセッション数3が含まれる', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const index: IndexEntry[] = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'index.json'), 'utf-8')
    );
    expect(index).toHaveLength(3);
  });

  it('index.json のQ&Aペア合計が7件', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const index: IndexEntry[] = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'index.json'), 'utf-8')
    );
    const totalQA = index.flatMap((s) => s.qa_pairs).length;
    expect(totalQA).toBe(7);
  });

  it('index.json が日付降順になっている', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const index: IndexEntry[] = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'index.json'), 'utf-8')
    );
    const dates = index.map((s) => s.date);
    const sorted = [...dates].sort((a, b) => b.localeCompare(a));
    expect(dates).toEqual(sorted);
  });

  it('speakers.json が空でない', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const speakers = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'speakers.json'), 'utf-8')
    );
    expect(speakers.length).toBeGreaterThan(0);
  });

  it('parties.json が3件以上の政党を含む', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const parties = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'parties.json'), 'utf-8')
    );
    expect(parties.length).toBeGreaterThanOrEqual(3);
  });

  it('topics.json が4件以上のトピックを含む', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const topics = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'topics.json'), 'utf-8')
    );
    expect(topics.length).toBeGreaterThanOrEqual(4);
  });

  it('committees.json に衆議院と参議院が含まれる', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const committees = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'committees.json'), 'utf-8')
    );
    const chambers = new Set(committees.map((c: { chamber: string }) => c.chamber));
    expect(chambers.has('shugiin')).toBe(true);
    expect(chambers.has('sangiin')).toBe(true);
  });

  it('dataDir が存在しない場合は空のJSONを生成する', () => {
    generateApi('/nonexistent/path', tmpDir);
    const index = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'index.json'), 'utf-8')
    );
    expect(index).toEqual([]);
  });

  it('index.json の各エントリが必須フィールドを持つ', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const index: IndexEntry[] = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'index.json'), 'utf-8')
    );
    for (const entry of index) {
      expect(entry).toHaveProperty('session_id');
      expect(entry).toHaveProperty('chamber');
      expect(entry).toHaveProperty('date');
      expect(entry).toHaveProperty('committee');
      expect(entry).toHaveProperty('source_url');
      expect(entry).toHaveProperty('speakers');
      expect(entry).toHaveProperty('parties');
      expect(entry).toHaveProperty('topics');
      expect(entry).toHaveProperty('qa_pairs');
    }
  });

  it('Q&Aペアにコミットメントがあるものが含まれる', () => {
    generateApi(FIXTURES_DIR, tmpDir);
    const index: IndexEntry[] = JSON.parse(
      fs.readFileSync(path.join(tmpDir, 'index.json'), 'utf-8')
    );
    const allPairs = index.flatMap((s) => s.qa_pairs);
    const withCommitment = allPairs.filter((p) => (p.commitment_strength ?? 0) > 0);
    expect(withCommitment.length).toBeGreaterThanOrEqual(1);
  });
});
