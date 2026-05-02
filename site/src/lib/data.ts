import fs from 'node:fs';
import path from 'node:path';
import { glob } from 'glob';

// data/ ディレクトリのパス（site/ の親ディレクトリ配下）
// import.meta.url はビルド時にバンドルされたファイルのパスになるため
// process.cwd()（= astro build を実行したディレクトリ = site/）から計算する
const DATA_DIR = path.resolve(process.cwd(), '../data');

export type {
  SpeakerInfo,
  SessionMetadata,
  QAQuestion,
  QAAnswer,
  QAPair,
  QAPairsOutput,
  QAMetrics,
  KeyCommitment,
  SessionSummary,
  Topic,
  TopicsOutput,
} from '../types';

import type { SessionMetadata, QAPairsOutput, SessionSummary, TopicsOutput } from '../types';

export interface LawEntry {
  id: string;
  title: string;
  short_title: string;
  ministry: string;
}

const API_DIR = path.resolve(process.cwd(), 'public/api');

/**
 * セッションに関連する法案を返す（laws.json + index.jsonを参照）。
 */
export function getRelatedLaws(sessionId: string): LawEntry[] {
  try {
    const indexPath = path.join(API_DIR, 'index.json');
    const lawsPath = path.join(API_DIR, 'laws.json');
    if (!fs.existsSync(indexPath) || !fs.existsSync(lawsPath)) return [];

    const index = readJson<{ session_id: string; related_laws?: string[] }[]>(indexPath);
    const laws = readJson<LawEntry[]>(lawsPath);

    const entry = index.find(e => e.session_id === sessionId);
    if (!entry?.related_laws?.length) return [];

    const lawMap = new Map(laws.map(l => [l.id, l]));
    return entry.related_laws.flatMap(id => lawMap.get(id) ? [lawMap.get(id)!] : []);
  } catch {
    return [];
  }
}

function readJson<T = unknown>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

function readJsonSafe<T>(filePath: string, fallback: T): T {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  } catch {
    return fallback;
  }
}

/**
 * 全セッションのメタデータを読み込む（日付降順）。
 * data/ が空の場合は空配列を返す。
 */
export function getAllSessions(): SessionMetadata[] {
  if (!fs.existsSync(DATA_DIR)) {
    return [];
  }
  const metadataFiles = glob.sync('**/metadata.json', { cwd: DATA_DIR });
  const sessions = metadataFiles.map((file) => {
    const content = fs.readFileSync(path.join(DATA_DIR, file), 'utf-8');
    return JSON.parse(content) as SessionMetadata;
  });
  return sessions.sort((a, b) => b.date.localeCompare(a.date));
}

/**
 * セッションのスラッグを生成する。
 */
export function sessionSlug(session: SessionMetadata): string {
  return `${session.session_id}_${session.committee}`;
}

/**
 * セッションの詳細ページURLを生成する（basePathなし）。
 */
export function sessionPath(session: SessionMetadata): string {
  const [year, month, day] = session.date.split('-');
  const slug = sessionSlug(session);
  return `/${session.chamber}/${year}/${month}/${day}/${slug}`;
}

/**
 * 特定セッションのデータを全て読み込む。
 */
export function getSessionData(
  chamber: string,
  year: string,
  month: string,
  day: string,
  slug: string
): {
  metadata: SessionMetadata;
  qaPairs: QAPairsOutput;
  summary: SessionSummary;
  topics: TopicsOutput;
} {
  const dir = path.join(DATA_DIR, chamber, year, month, day, slug);
  return {
    metadata: readJson<SessionMetadata>(path.join(dir, 'metadata.json')),
    qaPairs: readJsonSafe<QAPairsOutput>(path.join(dir, 'qa_pairs.json'), { pairs: [] }),
    summary: readJsonSafe<SessionSummary>(path.join(dir, 'summary.json'), { session_summary: '', key_topics: [], key_commitments: [] }),
    topics: readJsonSafe<TopicsOutput>(path.join(dir, 'topics.json'), { topics: [] }),
  };
}
