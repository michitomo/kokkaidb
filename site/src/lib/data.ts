import fs from 'node:fs';
import path from 'node:path';
import { glob } from 'glob';

// data/ ディレクトリのパス（site/ の親ディレクトリ配下）
// import.meta.url はビルド時にバンドルされたファイルのパスになるため
// process.cwd()（= astro build を実行したディレクトリ = site/）から計算する
const DATA_DIR = path.resolve(process.cwd(), '../data');

export interface SpeakerInfo {
  name: string;
  affiliation: string;
  role: string;
  start_seconds: number;
  start_time: string;
  duration_minutes: number;
}

export interface SessionMetadata {
  chamber: string;
  session_id: string;
  date: string;
  committee: string;
  duration: string;
  hls_url: string;
  source_url: string;
  processed_at: string;
  whisper_model: string;
  llm_model: string;
  speakers: SpeakerInfo[];
}

export interface QAQuestion {
  speaker: string;
  party: string;
  summary: string;
  full_text: string;
  intent: string;
}

export interface QAAnswer {
  speaker: string;
  role: string;
  summary: string;
  full_text: string;
  evasion_score: number;
  has_commitment: boolean;
  commitment_text: string;
}

export interface QAPair {
  id: string;
  segment_index: number;
  topic: string;
  question: QAQuestion;
  answer: QAAnswer;
  follow_up_ids: string[];
  video_url: string;
}

export interface QAPairsOutput {
  pairs: QAPair[];
}

export interface KeyCommitment {
  speaker: string;
  role: string;
  text: string;
  topic: string;
  qa_id: string;
}

export interface SessionSummary {
  session_summary: string;
  key_topics: string[];
  key_commitments: KeyCommitment[];
}

export interface Topic {
  name: string;
  description: string;
  related_qa_ids: string[];
  related_speakers: string[];
}

export interface TopicsOutput {
  topics: Topic[];
}

function readJson<T = unknown>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
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
    qaPairs: readJson<QAPairsOutput>(path.join(dir, 'qa_pairs.json')),
    summary: readJson<SessionSummary>(path.join(dir, 'summary.json')),
    topics: readJson<TopicsOutput>(path.join(dir, 'topics.json')),
  };
}
