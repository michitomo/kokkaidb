/**
 * generate-api.ts の generateDashboard 関数の単体テスト
 */
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { generateApi } from '../generate-api';

const FIXTURES_DIR = path.resolve(__dirname, '../../tests/fixtures/data');

let tmpOutDir: string;

beforeAll(() => {
  tmpOutDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kokkaidb-test-'));
});

afterAll(() => {
  fs.rmSync(tmpOutDir, { recursive: true, force: true });
});

describe('generateApi — dashboard outputs', () => {
  it('generates all JSON files without error', () => {
    generateApi(FIXTURES_DIR, tmpOutDir);
    const files = ['stats.json', 'topics-heatmap.json', 'commitments.json', 'calendar.json', 'evasion.json'];
    for (const f of files) {
      expect(fs.existsSync(path.join(tmpOutDir, f)), `${f} should exist`).toBe(true);
    }
  });

  it('stats.json has correct session count', () => {
    const stats = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'stats.json'), 'utf-8'));
    // 3 fixtures: shugiin/56149, shugiin/56200, sangiin/1234
    expect(stats.totalSessions).toBe(3);
    expect(stats.sessionsByChamber.shugiin).toBe(2);
    expect(stats.sessionsByChamber.sangiin).toBe(1);
  });

  it('stats.json totalQAPairs matches fixture data', () => {
    const stats = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'stats.json'), 'utf-8'));
    expect(stats.totalQAPairs).toBeGreaterThan(0);
  });

  it('stats.json avgEvasionScore is a number between 0 and 1', () => {
    const stats = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'stats.json'), 'utf-8'));
    expect(stats.avgEvasionScore).toBeGreaterThanOrEqual(0);
    expect(stats.avgEvasionScore).toBeLessThanOrEqual(1);
  });

  it('stats.json sessionsByMonth is sorted ascending', () => {
    const stats = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'stats.json'), 'utf-8'));
    const months = stats.sessionsByMonth.map((m: { month: string }) => m.month);
    const sorted = [...months].sort();
    expect(months).toEqual(sorted);
  });

  it('topics-heatmap.json has correct shape', () => {
    const heatmap = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'topics-heatmap.json'), 'utf-8'));
    expect(Array.isArray(heatmap.topics)).toBe(true);
    expect(Array.isArray(heatmap.committees)).toBe(true);
    expect(Array.isArray(heatmap.matrix)).toBe(true);
    // matrix rows == topics length
    expect(heatmap.matrix.length).toBe(heatmap.topics.length);
    // matrix cols == committees length
    for (const row of heatmap.matrix) {
      expect(row.length).toBe(heatmap.committees.length);
    }
  });

  it('topics-heatmap.json matrix cells are non-negative integers', () => {
    const heatmap = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'topics-heatmap.json'), 'utf-8'));
    for (const row of heatmap.matrix) {
      for (const cell of row) {
        expect(typeof cell).toBe('number');
        expect(cell).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it('topics-heatmap.json committees_by_chamber has shugiin and sangiin keys', () => {
    const heatmap = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'topics-heatmap.json'), 'utf-8'));
    expect(heatmap.committees_by_chamber).toHaveProperty('shugiin');
    expect(heatmap.committees_by_chamber).toHaveProperty('sangiin');
  });

  it('commitments.json has entries with required fields', () => {
    const commitments = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'commitments.json'), 'utf-8'));
    expect(Array.isArray(commitments)).toBe(true);
    if (commitments.length > 0) {
      const c = commitments[0];
      expect(c).toHaveProperty('id');
      expect(c).toHaveProperty('speaker');
      expect(c).toHaveProperty('text');
      expect(c).toHaveProperty('topic');
      expect(c).toHaveProperty('date');
      expect(c).toHaveProperty('chamber');
      expect(c).toHaveProperty('qaId');
      expect(c).toHaveProperty('sessionSlug');
      expect(c.status).toBe('unverified');
    }
  });

  it('commitments.json is sorted by date descending', () => {
    const commitments = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'commitments.json'), 'utf-8'));
    const dates = commitments.map((c: { date: string }) => c.date);
    const sorted = [...dates].sort((a, b) => b.localeCompare(a));
    expect(dates).toEqual(sorted);
  });

  it('calendar.json is a date-keyed object', () => {
    const calendar = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'calendar.json'), 'utf-8'));
    expect(typeof calendar).toBe('object');
    for (const [key, val] of Object.entries(calendar)) {
      expect(key).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect((val as { count: number }).count).toBeGreaterThan(0);
    }
  });

  it('evasion.json entries have required fields', () => {
    const evasion = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'evasion.json'), 'utf-8'));
    expect(Array.isArray(evasion)).toBe(true);
    for (const e of evasion) {
      expect(e).toHaveProperty('speaker');
      expect(e).toHaveProperty('totalAnswers');
      expect(e).toHaveProperty('clearCount');
      expect(e).toHaveProperty('hedgingCount');
      expect(e).toHaveProperty('evasiveCount');
      expect(e).toHaveProperty('avgEvasionScore');
      expect(e.clearCount + e.hedgingCount + e.evasiveCount).toBe(e.totalAnswers);
    }
  });

  it('evasion.json is sorted by avgAnswerCompleteness descending', () => {
    const evasion = JSON.parse(fs.readFileSync(path.join(tmpOutDir, 'evasion.json'), 'utf-8'));
    const scores = evasion.map((e: { avgAnswerCompleteness: number }) => e.avgAnswerCompleteness);
    const sorted = [...scores].sort((a, b) => b - a);
    expect(scores).toEqual(sorted);
  });

  it('handles empty data directory gracefully', () => {
    const emptyDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kokkaidb-empty-'));
    const emptyOut = fs.mkdtempSync(path.join(os.tmpdir(), 'kokkaidb-empty-out-'));
    try {
      // DATA_DIR doesn't exist — should generate empty JSON without throwing
      generateApi(path.join(emptyDir, 'nonexistent'), emptyOut);
      const stats = JSON.parse(fs.readFileSync(path.join(emptyOut, 'stats.json'), 'utf-8'));
      expect(stats.totalSessions).toBe(0);
      const calendar = JSON.parse(fs.readFileSync(path.join(emptyOut, 'calendar.json'), 'utf-8'));
      expect(calendar).toEqual({});
    } finally {
      fs.rmSync(emptyDir, { recursive: true, force: true });
      fs.rmSync(emptyOut, { recursive: true, force: true });
    }
  });
});
