import { describe, it, expect } from 'vitest';
import {
  qaPairsToTsv,
  indexEntriesToTsv,
  chamberLabel,
  commitmentStrengthLabel,
  type TsvQAPair,
  type TsvSession,
} from '../tsv-export';
import type { IndexEntry } from '../../../scripts/generate-api';

// テスト用フィクスチャ
const sampleSession: TsvSession = {
  session_id: 'test-001',
  chamber: 'shugiin',
  date: '2026-04-09',
  committee: '本会議',
  source_url: 'https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=test-001',
};

const samplePair: TsvQAPair = {
  id: 'test-001-qa-001',
  topic: '高額療養費制度',
  question_speaker: '古川あおい',
  question_party: 'チームみらい',
  question_summary: 'がん患者への影響について',
  question_intent: '制度改善を求める',
  question_sharpness: 0.7,
  evidence_grounding: 0.6,
  answer_speaker: '上野賢一郎',
  answer_role: '厚生労働大臣',
  answer_summary: '検討すると回答した。',
  answer_completeness: 0.4,
  commitment_strength: 0.3,
  commitment_text: '次期改正で対応する。',
  record_value: 0.5,
  video_url: 'https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=test-001&time=120',
};

describe('chamberLabel', () => {
  it('shugiin → 衆議院', () => {
    expect(chamberLabel('shugiin')).toBe('衆議院');
  });

  it('sangiin → 参議院', () => {
    expect(chamberLabel('sangiin')).toBe('参議院');
  });

  it('未知の値はそのまま返す', () => {
    expect(chamberLabel('unknown')).toBe('参議院');
  });
});

describe('commitmentStrengthLabel', () => {
  it('0 → なし', () => {
    expect(commitmentStrengthLabel(0)).toBe('なし');
  });

  it('undefined → なし', () => {
    expect(commitmentStrengthLabel(undefined)).toBe('なし');
  });

  it('0.1 → 検討', () => {
    expect(commitmentStrengthLabel(0.1)).toBe('検討');
  });

  it('0.5 → 中', () => {
    expect(commitmentStrengthLabel(0.5)).toBe('中');
  });

  it('1.0 → 即時', () => {
    expect(commitmentStrengthLabel(1.0)).toBe('即時');
  });
});

describe('qaPairsToTsv', () => {
  it('空の配列ではヘッダ行のみ返す', () => {
    const result = qaPairsToTsv([], []);
    const lines = result.split('\n');
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain('日付');
  });

  it('ヘッダが18列である', () => {
    const result = qaPairsToTsv([], []);
    const headers = result.split('\t');
    expect(headers).toHaveLength(18);
  });

  it('ヘッダ列名が正しい順序', () => {
    const result = qaPairsToTsv([], []);
    const headers = result.split('\t');
    expect(headers[0]).toBe('日付');
    expect(headers[1]).toBe('院');
    expect(headers[2]).toBe('委員会');
    expect(headers[3]).toBe('トピック');
    expect(headers[4]).toBe('質問者');
    expect(headers[7]).toBe('質問精度');
    expect(headers[8]).toBe('根拠品質');
    expect(headers[12]).toBe('答弁網羅性');
    expect(headers[13]).toBe('コミット強度');
    expect(headers[15]).toBe('議事録価値');
    expect(headers[17]).toBe('出典URL');
  });

  it('1件のデータが正しく変換される', () => {
    const result = qaPairsToTsv([samplePair], [sampleSession]);
    const lines = result.split('\n');
    expect(lines).toHaveLength(2); // ヘッダ + 1行
    const cols = lines[1].split('\t');
    expect(cols[0]).toBe('2026-04-09');
    expect(cols[1]).toBe('衆議院');
    expect(cols[2]).toBe('本会議');
    expect(cols[3]).toBe('高額療養費制度');
    expect(cols[4]).toBe('古川あおい');
    expect(cols[5]).toBe('チームみらい');
    expect(cols[13]).toBe('弱'); // commitment_strength 0.3 → 弱
  });

  it('タブ文字がスペースに置換される', () => {
    const pairWithTab: TsvQAPair = {
      ...samplePair,
      question_summary: '質問\tタブあり',
    };
    const result = qaPairsToTsv([pairWithTab], [sampleSession]);
    expect(result).not.toContain('質問\tタブあり');
    expect(result).toContain('質問 タブあり');
  });

  it('改行がリテラル \\n に置換される', () => {
    const pairWithNewline: TsvQAPair = {
      ...samplePair,
      answer_summary: '答弁\n改行あり',
    };
    const result = qaPairsToTsv([pairWithNewline], [sampleSession]);
    const lines = result.split('\n');
    // データ行にリテラル \n が含まれている（実際の改行ではない）
    expect(lines[1]).toContain('答弁\\n改行あり');
  });

  it('日本語文字列が正しく出力される', () => {
    const result = qaPairsToTsv([samplePair], [sampleSession]);
    expect(result).toContain('古川あおい');
    expect(result).toContain('チームみらい');
    expect(result).toContain('高額療養費制度');
  });

  it('commitment_strength=0 の場合「なし」が出力される', () => {
    const pairNoCommitment: TsvQAPair = {
      ...samplePair,
      commitment_strength: 0,
      commitment_text: '',
    };
    const result = qaPairsToTsv([pairNoCommitment], [sampleSession]);
    const lines = result.split('\n');
    const cols = lines[1].split('\t');
    expect(cols[13]).toBe('なし');
    expect(cols[14]).toBe('');
  });

  it('参議院の院名が「参議院」になる', () => {
    const sangiinSession: TsvSession = {
      ...sampleSession,
      chamber: 'sangiin',
    };
    const result = qaPairsToTsv([samplePair], [sangiinSession]);
    const lines = result.split('\n');
    const cols = lines[1].split('\t');
    expect(cols[1]).toBe('参議院');
  });

  it('複数件のデータが正しく出力される', () => {
    const pair2: TsvQAPair = { ...samplePair, id: 'test-001-qa-002', topic: '別トピック' };
    const result = qaPairsToTsv([samplePair, pair2], [sampleSession, sampleSession]);
    const lines = result.split('\n');
    expect(lines).toHaveLength(3); // ヘッダ + 2行
  });
});

describe('indexEntriesToTsv', () => {
  const sampleEntry: IndexEntry = {
    session_id: 'test-001',
    chamber: 'shugiin',
    date: '2026-04-09',
    committee: '本会議',
    source_url: 'https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=test-001',
    speakers: ['古川あおい', '上野賢一郎'],
    parties: ['チームみらい', '自由民主党'],
    topics: ['高額療養費制度'],
    related_laws: [],
    qa_pairs: [
      {
        id: 'test-001-qa-001',
        topic: '高額療養費制度',
        question_speaker: '古川あおい',
        question_party: 'チームみらい',
        question_summary: 'がん患者への影響について',
        question_full_text: '',
        question_intent: '制度改善を求める',
        question_sharpness: 0.7,
        evidence_grounding: 0.6,
        answer_speaker: '上野賢一郎',
        answer_role: '厚生労働大臣',
        answer_summary: '検討すると回答した。',
        answer_full_text: '',
        answer_completeness: 0.4,
        commitment_strength: 0.3,
        commitment_text: '次期改正で対応する。',
        record_value: 0.5,
        evasion_score: 0.6,
        video_url: 'https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=test-001&time=120',
        related_laws: [],
      },
    ],
  };

  it('IndexEntry[] からTSVを生成できる', () => {
    const result = indexEntriesToTsv([sampleEntry]);
    const lines = result.split('\n');
    expect(lines).toHaveLength(2); // ヘッダ + 1件
  });

  it('空の IndexEntry[] はヘッダのみ', () => {
    const result = indexEntriesToTsv([]);
    const lines = result.split('\n');
    expect(lines).toHaveLength(1);
  });

  it('複数セッションの全Q&Aペアが出力される', () => {
    const entry2: IndexEntry = {
      ...sampleEntry,
      session_id: 'test-002',
      qa_pairs: [
        { ...sampleEntry.qa_pairs[0], id: 'test-002-qa-001' },
        { ...sampleEntry.qa_pairs[0], id: 'test-002-qa-002' },
      ],
    };
    const result = indexEntriesToTsv([sampleEntry, entry2]);
    const lines = result.split('\n');
    expect(lines).toHaveLength(4); // ヘッダ + 3件
  });
});
