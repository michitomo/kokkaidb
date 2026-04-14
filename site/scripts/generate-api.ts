/**
 * ビルド前に public/api/ 配下の静的JSONを生成するスクリプト。
 * package.json の prebuild に追加して自動実行する。
 *
 * 使い方:
 *   node --import tsx/esm scripts/generate-api.ts [DATA_DIR] [OUT_DIR]
 *
 * 環境変数:
 *   DATA_DIR  — data/ ディレクトリのパス（デフォルト: ../data）
 *   OUT_DIR   — 出力先（デフォルト: public/api）
 */

import fs from 'node:fs';
import path from 'node:path';
import { glob } from 'glob';

// --- パス解決 ---
const DATA_DIR = process.env.DATA_DIR
  ? path.resolve(process.cwd(), process.env.DATA_DIR)
  : path.resolve(process.cwd(), '../data');
const OUT_DIR = process.env.OUT_DIR
  ? path.resolve(process.cwd(), process.env.OUT_DIR)
  : path.resolve(process.cwd(), 'public/api');

// --- 型定義 ---
interface SpeakerInfo {
  name: string;
  affiliation: string;
  role: string;
  start_seconds: number;
  start_time: string;
  duration_minutes: number;
}

interface SessionMetadata {
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

interface QAQuestion {
  speaker: string;
  party: string;
  summary: string;
  full_text: string;
  intent: string;
}

interface QAAnswer {
  speaker: string;
  role: string;
  summary: string;
  full_text: string;
  evasion_score: number;
  has_commitment: boolean;
  commitment_text: string;
}

interface QAPairRaw {
  id: string;
  segment_index: number;
  topic: string;
  question: QAQuestion;
  answer: QAAnswer;
  follow_up_ids: string[];
  video_url: string;
}

interface QAPairsOutput {
  pairs: QAPairRaw[];
}

interface TopicRaw {
  name: string;
  description: string;
  related_qa_ids: string[];
  related_speakers: string[];
}

interface TopicsOutput {
  topics: TopicRaw[];
}

interface KeyCommitmentRaw {
  speaker: string;
  role: string;
  text: string;
  topic: string;
  qa_id: string;
}

interface SummaryRaw {
  session_summary: string;
  key_topics: string[];
  key_commitments: KeyCommitmentRaw[];
}

// index.json のQ&Aペア形式
interface IndexQAPair {
  id: string;
  topic: string;
  question_speaker: string;
  question_party: string;
  question_summary: string;
  question_intent: string;
  answer_speaker: string;
  answer_role: string;
  answer_summary: string;
  evasion_score: number;
  has_commitment: boolean;
  commitment_text: string;
  video_url: string;
}

// index.json のセッションエントリ
export interface IndexEntry {
  session_id: string;
  chamber: 'shugiin' | 'sangiin';
  date: string;
  committee: string;
  source_url: string;
  speakers: string[];
  parties: string[];
  topics: string[];
  qa_pairs: IndexQAPair[];
}

// speakers.json のエントリ
interface SpeakerEntry {
  name: string;
  affiliation: string;
  session_count: number;
}

// stats.json
export interface DashboardStats {
  totalSessions: number;
  totalQAPairs: number;
  totalSpeakers: number;
  totalCommitments: number;
  avgEvasionScore: number;
  sessionsByChamber: { shugiin: number; sangiin: number };
  sessionsByMonth: { month: string; shugiin: number; sangiin: number }[];
  topTopics: { topic: string; count: number }[];
  lastUpdated: string;
}

// topics-heatmap.json のエントリ
export interface TopicHeatmapData {
  topics: string[];
  committees: string[];
  matrix: number[][];
  committees_by_chamber: Record<string, string[]>;
}

// commitments.json のエントリ
export interface CommitmentEntry {
  id: string;
  speaker: string;
  role: string;
  text: string;
  topic: string;
  date: string;
  chamber: string;
  committee: string;
  qaId: string;
  sessionSlug: string;
  status: 'unverified';
}

// calendar.json のエントリ
export interface CalendarData {
  [date: string]: { count: number; shugiin: number; sangiin: number };
}

// evasion.json のエントリ
export interface EvasionEntry {
  speaker: string;
  role: string;
  totalAnswers: number;
  clearCount: number;
  hedgingCount: number;
  evasiveCount: number;
  avgEvasionScore: number;
  byTopic: { topic: string; avgScore: number; count: number }[];
}

// parties.json のエントリ
interface PartyEntry {
  name: string;
  member_count: number;
}

// topics.json のエントリ
interface TopicEntry {
  name: string;
  session_count: number;
}

// committees.json のエントリ
interface CommitteeEntry {
  name: string;
  chamber: string;
  session_count: number;
}

// --- ユーティリティ ---
function readJson<T>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as T;
}

function writeJson(filePath: string, data: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf-8');
}

// --- ダッシュボード用集計 ---
export function generateDashboard(indexEntries: IndexEntry[], summaries: Map<string, SummaryRaw>, outDir: string): void {
  // stats.json
  const totalSessions = indexEntries.length;
  const totalQAPairs = indexEntries.reduce((s, e) => s + e.qa_pairs.length, 0);
  const speakerSet = new Set(indexEntries.flatMap((e) => e.speakers));
  const totalSpeakers = speakerSet.size;

  let totalCommitments = 0;
  for (const summary of summaries.values()) {
    totalCommitments += (summary.key_commitments ?? []).length;
  }

  const allScores = indexEntries.flatMap((e) =>
    e.qa_pairs.map((q) => q.evasion_score).filter((s) => typeof s === 'number')
  );
  const avgEvasionScore = allScores.length > 0
    ? allScores.reduce((a, b) => a + b, 0) / allScores.length
    : 0;

  const chamberCount = { shugiin: 0, sangiin: 0 };
  const monthMap = new Map<string, { shugiin: number; sangiin: number }>();
  for (const entry of indexEntries) {
    if (entry.chamber === 'shugiin') chamberCount.shugiin++;
    else chamberCount.sangiin++;
    const month = entry.date.slice(0, 7);
    const m = monthMap.get(month) ?? { shugiin: 0, sangiin: 0 };
    if (entry.chamber === 'shugiin') m.shugiin++; else m.sangiin++;
    monthMap.set(month, m);
  }
  const sessionsByMonth = Array.from(monthMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, counts]) => ({ month, ...counts }));

  const topicCountMap = new Map<string, number>();
  for (const entry of indexEntries) {
    for (const t of entry.topics) {
      topicCountMap.set(t, (topicCountMap.get(t) ?? 0) + 1);
    }
  }
  const topTopics = Array.from(topicCountMap.entries())
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([topic, count]) => ({ topic, count }));

  const stats: DashboardStats = {
    totalSessions,
    totalQAPairs,
    totalSpeakers,
    totalCommitments,
    avgEvasionScore: Math.round(avgEvasionScore * 100) / 100,
    sessionsByChamber: chamberCount,
    sessionsByMonth,
    topTopics,
    lastUpdated: new Date().toISOString(),
  };
  writeJson(path.join(outDir, 'stats.json'), stats);

  // topics-heatmap.json — トピック×委員会の行列
  const topicCommitteeMap = new Map<string, Map<string, number>>();
  const committeesByChamber: Record<string, Set<string>> = { shugiin: new Set(), sangiin: new Set() };
  for (const entry of indexEntries) {
    committeesByChamber[entry.chamber].add(entry.committee);
    for (const topic of entry.topics) {
      const inner = topicCommitteeMap.get(topic) ?? new Map<string, number>();
      inner.set(entry.committee, (inner.get(entry.committee) ?? 0) + 1);
      topicCommitteeMap.set(topic, inner);
    }
  }
  // 上位20トピック
  const sortedTopics = Array.from(topicCommitteeMap.entries())
    .sort(([, a], [, b]) => {
      const sumA = Array.from(a.values()).reduce((s, v) => s + v, 0);
      const sumB = Array.from(b.values()).reduce((s, v) => s + v, 0);
      return sumB - sumA;
    })
    .slice(0, 20)
    .map(([t]) => t);
  // 委員会（セッション数降順）
  const committeeSessionCount = new Map<string, number>();
  for (const entry of indexEntries) {
    committeeSessionCount.set(entry.committee, (committeeSessionCount.get(entry.committee) ?? 0) + 1);
  }
  const sortedCommittees = Array.from(committeeSessionCount.entries())
    .sort(([, a], [, b]) => b - a)
    .map(([c]) => c);
  const heatmapMatrix = sortedTopics.map((topic) =>
    sortedCommittees.map((committee) => topicCommitteeMap.get(topic)?.get(committee) ?? 0)
  );
  const heatmapData: TopicHeatmapData = {
    topics: sortedTopics,
    committees: sortedCommittees,
    matrix: heatmapMatrix,
    committees_by_chamber: {
      shugiin: Array.from(committeesByChamber.shugiin),
      sangiin: Array.from(committeesByChamber.sangiin),
    },
  };
  writeJson(path.join(outDir, 'topics-heatmap.json'), heatmapData);

  // commitments.json
  const commitments: CommitmentEntry[] = [];
  for (const entry of indexEntries) {
    const summary = summaries.get(`${entry.chamber}::${entry.session_id}`);
    if (!summary) continue;
    for (const c of summary.key_commitments ?? []) {
      const slug = `${entry.session_id}_${entry.committee}`;
      commitments.push({
        id: `${entry.chamber}_${entry.session_id}_${c.qa_id}`,
        speaker: c.speaker,
        role: c.role,
        text: c.text,
        topic: c.topic,
        date: entry.date,
        chamber: entry.chamber,
        committee: entry.committee,
        qaId: c.qa_id,
        sessionSlug: slug,
        status: 'unverified',
      });
    }
  }
  commitments.sort((a, b) => b.date.localeCompare(a.date));
  writeJson(path.join(outDir, 'commitments.json'), commitments);

  // calendar.json — 日別セッション数
  const calendarMap = new Map<string, { count: number; shugiin: number; sangiin: number }>();
  for (const entry of indexEntries) {
    const existing = calendarMap.get(entry.date) ?? { count: 0, shugiin: 0, sangiin: 0 };
    existing.count++;
    if (entry.chamber === 'shugiin') existing.shugiin++; else existing.sangiin++;
    calendarMap.set(entry.date, existing);
  }
  writeJson(path.join(outDir, 'calendar.json'), Object.fromEntries(calendarMap));

  // evasion.json — 答弁者別回避度集計
  const evasionMap = new Map<string, {
    role: string;
    scores: number[];
    clearCount: number;
    hedgingCount: number;
    evasiveCount: number;
    byTopic: Map<string, { scores: number[]; count: number }>;
  }>();
  for (const entry of indexEntries) {
    for (const qa of entry.qa_pairs) {
      const speaker = qa.answer_speaker;
      if (!speaker) continue;
      const score = qa.evasion_score ?? 0;
      const existing = evasionMap.get(speaker) ?? {
        role: qa.answer_role,
        scores: [],
        clearCount: 0,
        hedgingCount: 0,
        evasiveCount: 0,
        byTopic: new Map(),
      };
      existing.scores.push(score);
      if (score < 0.3) existing.clearCount++;
      else if (score < 0.7) existing.hedgingCount++;
      else existing.evasiveCount++;
      if (qa.topic) {
        const t = existing.byTopic.get(qa.topic) ?? { scores: [], count: 0 };
        t.scores.push(score);
        t.count++;
        existing.byTopic.set(qa.topic, t);
      }
      evasionMap.set(speaker, existing);
    }
  }
  const evasionEntries: EvasionEntry[] = Array.from(evasionMap.entries())
    .filter(([, v]) => v.scores.length > 0)
    .map(([speaker, v]) => ({
      speaker,
      role: v.role,
      totalAnswers: v.scores.length,
      clearCount: v.clearCount,
      hedgingCount: v.hedgingCount,
      evasiveCount: v.evasiveCount,
      avgEvasionScore: Math.round((v.scores.reduce((a, b) => a + b, 0) / v.scores.length) * 100) / 100,
      byTopic: Array.from(v.byTopic.entries()).map(([topic, t]) => ({
        topic,
        avgScore: Math.round((t.scores.reduce((a, b) => a + b, 0) / t.scores.length) * 100) / 100,
        count: t.count,
      })),
    }))
    .sort((a, b) => b.avgEvasionScore - a.avgEvasionScore);
  writeJson(path.join(outDir, 'evasion.json'), evasionEntries);
}

// --- メイン処理 ---
export function generateApi(dataDir: string, outDir: string): void {
  if (!fs.existsSync(dataDir)) {
    console.warn(`[generate-api] DATA_DIR not found: ${dataDir} — generating empty API files`);
    fs.mkdirSync(outDir, { recursive: true });
    writeJson(path.join(outDir, 'index.json'), []);
    writeJson(path.join(outDir, 'speakers.json'), []);
    writeJson(path.join(outDir, 'parties.json'), []);
    writeJson(path.join(outDir, 'topics.json'), []);
    writeJson(path.join(outDir, 'committees.json'), []);
    writeJson(path.join(outDir, 'stats.json'), {
      totalSessions: 0, totalQAPairs: 0, totalSpeakers: 0, totalCommitments: 0,
      avgEvasionScore: 0, sessionsByChamber: { shugiin: 0, sangiin: 0 },
      sessionsByMonth: [], topTopics: [], lastUpdated: new Date().toISOString(),
    });
    writeJson(path.join(outDir, 'topics-heatmap.json'), { topics: [], committees: [], matrix: [], committees_by_chamber: { shugiin: [], sangiin: [] } });
    writeJson(path.join(outDir, 'commitments.json'), []);
    writeJson(path.join(outDir, 'calendar.json'), {});
    writeJson(path.join(outDir, 'evasion.json'), []);
    return;
  }

  const metadataFiles = glob.sync('**/metadata.json', { cwd: dataDir });

  const indexEntries: IndexEntry[] = [];
  const speakerMap = new Map<string, SpeakerEntry>();
  const partyMap = new Map<string, PartyEntry>();
  const topicMap = new Map<string, TopicEntry>();
  const committeeMap = new Map<string, CommitteeEntry>();
  const summaryMap = new Map<string, SummaryRaw>(); // for dashboard

  for (const relPath of metadataFiles) {
    const dir = path.dirname(path.join(dataDir, relPath));
    let metadata: SessionMetadata;
    try {
      metadata = readJson<SessionMetadata>(path.join(dir, 'metadata.json'));
    } catch {
      continue;
    }

    // Q&Aペア読み込み
    let rawPairs: QAPairRaw[] = [];
    try {
      const qaPairsOutput = readJson<QAPairsOutput>(path.join(dir, 'qa_pairs.json'));
      rawPairs = qaPairsOutput.pairs ?? [];
    } catch {
      // qa_pairs.json が存在しない場合はスキップ
    }

    // トピック読み込み
    let topicNames: string[] = [];
    try {
      const topicsOutput = readJson<TopicsOutput>(path.join(dir, 'topics.json'));
      topicNames = (topicsOutput.topics ?? []).map((t) => t.name);
    } catch {
      // topics.json が存在しない場合はスキップ
    }

    // summary読み込み（dashboard用）
    try {
      const summary = readJson<SummaryRaw>(path.join(dir, 'summary.json'));
      summaryMap.set(`${metadata.chamber}::${metadata.session_id}`, summary);
    } catch {
      // summary.json が存在しない場合はスキップ
    }

    // 発言者・政党をセッションからユニーク抽出
    const sessionSpeakers = metadata.speakers.map((s) => s.name);
    const sessionParties = [
      ...new Set(
        metadata.speakers
          .map((s) => s.affiliation)
          .filter((a) => a && a.trim() !== '')
      ),
    ];

    // Q&AペアをIndexQAPair形式に変換
    const indexQAPairs: IndexQAPair[] = rawPairs.map((p) => ({
      id: p.id,
      topic: p.topic,
      question_speaker: p.question.speaker,
      question_party: p.question.party,
      question_summary: p.question.summary,
      question_intent: p.question.intent,
      answer_speaker: p.answer.speaker,
      answer_role: p.answer.role,
      answer_summary: p.answer.summary,
      evasion_score: p.answer.evasion_score,
      has_commitment: p.answer.has_commitment,
      commitment_text: p.answer.commitment_text,
      video_url: p.video_url,
    }));

    indexEntries.push({
      session_id: metadata.session_id,
      chamber: metadata.chamber as 'shugiin' | 'sangiin',
      date: metadata.date,
      committee: metadata.committee,
      source_url: metadata.source_url,
      speakers: sessionSpeakers,
      parties: sessionParties,
      topics: topicNames,
      qa_pairs: indexQAPairs,
    });

    // 発言者マスタ集計
    for (const speaker of metadata.speakers) {
      const existing = speakerMap.get(speaker.name);
      if (existing) {
        existing.session_count += 1;
      } else {
        speakerMap.set(speaker.name, {
          name: speaker.name,
          affiliation: speaker.affiliation,
          session_count: 1,
        });
      }
    }

    // 政党マスタ集計（発言者の所属から）
    for (const party of sessionParties) {
      const existing = partyMap.get(party);
      if (existing) {
        existing.member_count += 1;
      } else {
        partyMap.set(party, { name: party, member_count: 1 });
      }
    }

    // トピックマスタ集計
    for (const topicName of topicNames) {
      const existing = topicMap.get(topicName);
      if (existing) {
        existing.session_count += 1;
      } else {
        topicMap.set(topicName, { name: topicName, session_count: 1 });
      }
    }

    // 委員会マスタ集計
    const committeeKey = `${metadata.chamber}::${metadata.committee}`;
    const existingCommittee = committeeMap.get(committeeKey);
    if (existingCommittee) {
      existingCommittee.session_count += 1;
    } else {
      committeeMap.set(committeeKey, {
        name: metadata.committee,
        chamber: metadata.chamber,
        session_count: 1,
      });
    }
  }

  // 日付降順にソート
  indexEntries.sort((a, b) => b.date.localeCompare(a.date));

  const speakers = Array.from(speakerMap.values()).sort(
    (a, b) => b.session_count - a.session_count
  );
  const parties = Array.from(partyMap.values()).sort(
    (a, b) => b.member_count - a.member_count
  );
  const topics = Array.from(topicMap.values()).sort(
    (a, b) => b.session_count - a.session_count
  );
  const committees = Array.from(committeeMap.values()).sort(
    (a, b) => b.session_count - a.session_count
  );

  fs.mkdirSync(outDir, { recursive: true });
  writeJson(path.join(outDir, 'index.json'), indexEntries);
  writeJson(path.join(outDir, 'speakers.json'), speakers);
  writeJson(path.join(outDir, 'parties.json'), parties);
  writeJson(path.join(outDir, 'topics.json'), topics);
  writeJson(path.join(outDir, 'committees.json'), committees);

  // ダッシュボード用JSON生成
  generateDashboard(indexEntries, summaryMap, outDir);

  const totalQA = indexEntries.reduce((sum, e) => sum + e.qa_pairs.length, 0);
  console.log(
    `[generate-api] Generated: ${indexEntries.length} sessions, ${totalQA} Q&A pairs → ${outDir}`
  );
}

// CLIとして直接実行された場合
const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(import.meta.url.replace('file://', ''));
if (isMain || process.argv[1]?.endsWith('generate-api.ts') || process.argv[1]?.endsWith('generate-api.js')) {
  generateApi(DATA_DIR, OUT_DIR);
}
