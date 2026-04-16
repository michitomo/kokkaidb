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
const LAWS_MD = process.env.LAWS_MD
  ? path.resolve(process.cwd(), process.env.LAWS_MD)
  : path.resolve(process.cwd(), '../docs/laws.md');

// --- 型定義 ---
import type {
  SessionMetadata,
  QAPair as QAPairRaw,
  QAPairsOutput,
  SessionSummary as SummaryRaw,
  TopicsOutput,
} from '../src/types';

// index.json のQ&Aペア形式
interface IndexQAPair {
  id: string;
  topic: string;
  question_speaker: string;
  question_party: string;
  question_summary: string;
  question_full_text: string;
  question_intent: string;
  answer_speaker: string;
  answer_role: string;
  answer_summary: string;
  answer_full_text: string;
  evasion_score: number;
  has_commitment: boolean;
  commitment_text: string;
  video_url: string;
  related_laws: string[];
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
  related_laws: string[];
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

// laws.json のエントリ
export interface LawEntry {
  id: string;
  title: string;
  short_title: string;
  ministry: string;
  tags: string[];
  summary: string;
  submission_target: string;
}

// --- 法案マスタ パーサー ---
function parseLawsMd(filePath: string): LawEntry[] {
  if (!fs.existsSync(filePath)) {
    console.log(`[generate-api] laws.md not found at ${filePath}, skipping law tagging`);
    return [];
  }
  const text = fs.readFileSync(filePath, 'utf-8');
  const laws: LawEntry[] = [];
  let currentMinistry = '';
  let lawIndex = 0;

  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    // 省庁ヘッダ: # **内閣官房 計4件**
    const ministryMatch = lines[i].match(/^# \*\*(.+?)(?:\s+計\d+件)?\*\*$/);
    if (ministryMatch) {
      // 「内閣提出予定法律案等件名・要旨調」や「件数表」はスキップ
      const name = ministryMatch[1].trim();
      if (!name.includes('件名') && !name.includes('件数') && !name.includes('第')) {
        currentMinistry = name;
      }
      continue;
    }

    // 法案タイトル: ## **3月上旬 \- 防災庁設置法案（仮称）**
    const lawMatch = lines[i].match(/^## \*\*(.+?)\s*\\?\s*-\s*(.+?)\*\*$/);
    if (lawMatch) {
      lawIndex++;
      const submissionTarget = lawMatch[1].trim();
      const title = lawMatch[2].trim();

      // 短縮タイトル: 「〜法律案」の前の法律名を抽出、長すぎる場合は先頭40文字
      const shortMatch = title.match(/^(.+?(?:法案|法律案|条約|協定|議定書))/);
      let shortTitle = shortMatch ? shortMatch[1] : title;
      if (shortTitle.length > 40) {
        // 「の一部を改正する」の前で切る
        const cutMatch = shortTitle.match(/^(.+?)(?:の一部を改正する|等の一部|及び)/);
        shortTitle = cutMatch ? cutMatch[1] + '改正案' : shortTitle.slice(0, 40) + '…';
      }

      // タグ行: *`tag1` `tag2` ...*
      let tags: string[] = [];
      if (i + 2 < lines.length) {
        const tagLine = lines[i + 2];
        const tagMatches = tagLine.match(/`([^`]+)`/g);
        if (tagMatches) {
          tags = tagMatches.map(t => t.replace(/`/g, ''));
        }
      }

      // 要旨: タグ行の次の非空行
      let summary = '';
      for (let j = i + 3; j < lines.length && j < i + 6; j++) {
        const line = lines[j].trim();
        if (line && !line.startsWith('#') && !line.startsWith('---') && !line.startsWith('*')) {
          summary = line;
          break;
        }
      }

      laws.push({
        id: `law_${String(lawIndex).padStart(3, '0')}`,
        title,
        short_title: shortTitle,
        ministry: currentMinistry,
        tags,
        summary,
        submission_target: submissionTarget,
      });
    }
  }

  console.log(`[generate-api] Parsed ${laws.length} laws from laws.md`);
  return laws;
}

/**
 * Q&Aペアのtopic/summaryと法案タグを照合し、関連法案IDを返す。
 */
/**
 * 1つのQ&Aペアに対して関連法案IDを返す。
 * summary だけでなく full_text も照合対象に含め、スペース入りタグは分割して扱う。
 */
function matchLawsForQA(
  qa: { topic: string; question_summary: string; answer_summary: string; question_full_text: string; answer_full_text: string },
  laws: LawEntry[],
): string[] {
  if (laws.length === 0) return [];

  const qaText = `${qa.topic} ${qa.question_summary} ${qa.answer_summary} ${qa.question_full_text} ${qa.answer_full_text}`;
  const qaTextLower = qaText.toLowerCase();

  const matched: string[] = [];
  for (const law of laws) {
    // スペースを含むタグは分割して個別タグとして扱う
    const expandedTags = law.tags.flatMap(tag => tag.includes(' ') ? tag.split(/\s+/) : [tag]);
    const hitCount = expandedTags.filter(tag => qaTextLower.includes(tag.toLowerCase())).length;
    // タグの25%以上がヒット、かつ最低2つ以上
    if (hitCount >= 2 && hitCount / expandedTags.length >= 0.25) {
      matched.push(law.id);
    }
  }
  return matched;
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
    writeJson(path.join(outDir, 'laws.json'), []);
    return;
  }

  // 法案マスタを読み込み
  const laws = parseLawsMd(LAWS_MD);

  // laws.md がない場合（CI等）、コミット済みの related-laws-map.json から引き継ぐ
  // 形式: { session_id: { qa_id: law_id[] } }
  const existingQALaws = new Map<string, Record<string, string[]>>();
  if (laws.length === 0) {
    const mapPath = path.join(outDir, 'related-laws-map.json');
    if (fs.existsSync(mapPath)) {
      try {
        const mapping = readJson<Record<string, Record<string, string[]>>>(mapPath);
        for (const [sid, qaMap] of Object.entries(mapping)) {
          existingQALaws.set(sid, qaMap);
        }
        console.log(`[generate-api] Loaded ${existingQALaws.size} sessions with per-QA related_laws from related-laws-map.json`);
      } catch {
        // ignore
      }
    }
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

    // Q&AペアをIndexQAPair形式に変換（法案マッチング込み）
    const existingSessionQALaws = existingQALaws.get(metadata.session_id) || {};
    const indexQAPairs: IndexQAPair[] = rawPairs.map((p) => ({
      id: p.id,
      topic: p.topic,
      question_speaker: p.question.speaker,
      question_party: p.question.party,
      question_summary: p.question.summary,
      question_full_text: p.question.full_text || '',
      question_intent: p.question.intent,
      answer_speaker: p.answer.speaker,
      answer_role: p.answer.role,
      answer_summary: p.answer.summary,
      answer_full_text: p.answer.full_text || '',
      evasion_score: p.answer.evasion_score,
      has_commitment: p.answer.has_commitment,
      commitment_text: p.answer.commitment_text,
      video_url: p.video_url,
      related_laws: laws.length > 0
        ? matchLawsForQA({ topic: p.topic, question_summary: p.question.summary, answer_summary: p.answer.summary, question_full_text: p.question.full_text || '', answer_full_text: p.answer.full_text || '' }, laws)
        : (existingSessionQALaws[p.id] || []),
    }));

    // セッションのrelated_lawsはQ&Aペアのunion
    const relatedLaws = [...new Set(indexQAPairs.flatMap(qa => qa.related_laws))];

    indexEntries.push({
      session_id: metadata.session_id,
      chamber: metadata.chamber as 'shugiin' | 'sangiin',
      date: metadata.date,
      committee: metadata.committee,
      source_url: metadata.source_url,
      speakers: sessionSpeakers,
      parties: sessionParties,
      topics: topicNames,
      related_laws: relatedLaws,
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

  // 法案マスタ（参照されている法案のみをコミット可能なスナップショットとして出力）
  // laws.md はgitignore済みなので、CIでは既存のlaws.jsonをそのまま使用する
  // ローカルでlaws.mdが存在する場合のみ、参照済み法案に絞って上書き
  if (laws.length > 0) {
    const referencedLawIds = new Set(indexEntries.flatMap(e => e.related_laws));
    const lawsForApi = laws
      .filter(l => referencedLawIds.has(l.id))
      .map(l => ({ id: l.id, title: l.title, short_title: l.short_title, ministry: l.ministry }));
    writeJson(path.join(outDir, 'laws.json'), lawsForApi);
    console.log(`[generate-api] laws.json: ${lawsForApi.length} referenced laws (out of ${laws.length} total)`);

    // related-laws-map.json: session_id → { qa_id → law_id[] } のマッピング（コミット用スナップショット）
    const relatedLawsMap: Record<string, Record<string, string[]>> = {};
    for (const entry of indexEntries) {
      const qaMap: Record<string, string[]> = {};
      for (const qa of entry.qa_pairs) {
        if (qa.related_laws.length > 0) {
          qaMap[qa.id] = qa.related_laws;
        }
      }
      if (Object.keys(qaMap).length > 0) {
        relatedLawsMap[entry.session_id] = qaMap;
      }
    }
    const totalQAWithLaws = Object.values(relatedLawsMap).reduce((s, m) => s + Object.keys(m).length, 0);
    writeJson(path.join(outDir, 'related-laws-map.json'), relatedLawsMap);
    console.log(`[generate-api] related-laws-map.json: ${Object.keys(relatedLawsMap).length} sessions, ${totalQAWithLaws} Q&A pairs`);
  } else {
    console.log('[generate-api] laws.md not found — keeping existing laws.json and related-laws-map.json as-is');
  }

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
