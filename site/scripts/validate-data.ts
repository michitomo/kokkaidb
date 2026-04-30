/**
 * data/ 配下のセッション JSON 群が参照整合性を保っていることを検証するスタンドアロンスクリプト。
 *
 * 使い方:
 *   tsx scripts/validate-data.ts [DATA_DIR]
 *
 * 環境変数:
 *   DATA_DIR — data/ ディレクトリのパス（デフォルト: ../data）
 *   LAWS_JSON — laws.json のパス（デフォルト: $DATA_DIR/laws/laws.json）
 *
 * 終了コード:
 *   0 = 全セッション OK
 *   1 = R1-R6 のいずれかに違反あり
 */

import fs from 'node:fs';
import path from 'node:path';
import { glob } from 'glob';

import type {
  QAPair,
  QAPairsOutput,
  SessionMetadata,
  SessionSummary,
  TopicsOutput,
} from '../src/types';

const SPEAKER_ROLES = new Set([
  '委員長',
  '質疑者',
  '答弁者',
  '政府参考人',
  '参考人',
  'その他',
]);

const SESSION_KINDS = new Set([
  'regular_qa',
  'representative_questions',
  'floor_speech',
  'procedural',
  'expert_hearing',
]);

interface LawEntry {
  id: string;
}

interface LawsFile {
  bills?: LawEntry[];
  laws?: LawEntry[];
}

interface SessionPaths {
  dir: string;
  metadata: string;
  qaPairs: string;
  summary: string;
  topics: string;
}

interface Violation {
  rule: string;
  level: 'error' | 'warn';
  message: string;
}

interface SessionReport {
  sessionPath: string;
  violations: Violation[];
}

function readJson<T>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as T;
}

function loadLawIds(lawsPath: string): Set<string> {
  if (!fs.existsSync(lawsPath)) {
    console.warn(`[validate-data] laws file not found: ${lawsPath}; R4/R6 skipped`);
    return new Set();
  }
  const data = readJson<LawsFile>(lawsPath);
  const list = data.bills ?? data.laws ?? [];
  return new Set(list.map((l) => l.id).filter(Boolean));
}

function discoverSessions(dataDir: string): SessionPaths[] {
  const dirs = glob.sync('*/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*/', {
    cwd: dataDir,
    absolute: true,
  });
  return dirs.map((dir) => ({
    dir,
    metadata: path.join(dir, 'metadata.json'),
    qaPairs: path.join(dir, 'qa_pairs.json'),
    summary: path.join(dir, 'summary.json'),
    topics: path.join(dir, 'topics.json'),
  }));
}

function validateSession(paths: SessionPaths, validLawIds: Set<string>): SessionReport {
  const violations: Violation[] = [];

  if (!fs.existsSync(paths.qaPairs)) {
    return { sessionPath: paths.dir, violations };
  }

  const qa = readJson<QAPairsOutput>(paths.qaPairs);
  const qaIds = new Set(qa.pairs.map((p) => p.id));

  if (fs.existsSync(paths.topics)) {
    const topics = readJson<TopicsOutput>(paths.topics);
    for (const t of topics.topics) {
      for (const refId of t.related_qa_ids) {
        if (!qaIds.has(refId)) {
          violations.push({
            rule: 'R1',
            level: 'error',
            message: `topics[${t.name}].related_qa_ids contains unknown qa_id "${refId}"`,
          });
        }
      }
    }
  }

  let summary: SessionSummary | null = null;
  if (fs.existsSync(paths.summary)) {
    summary = readJson<SessionSummary>(paths.summary);
    for (const c of summary.key_commitments ?? []) {
      if (c.qa_id && !qaIds.has(c.qa_id)) {
        violations.push({
          rule: 'R2',
          level: 'error',
          message: `key_commitments references unknown qa_id "${c.qa_id}" (text="${c.text.slice(0, 30)}")`,
        });
      }
    }

    for (const rl of summary.related_laws ?? []) {
      for (const qid of rl.qa_ids) {
        if (!qaIds.has(qid)) {
          violations.push({
            rule: 'R3',
            level: 'error',
            message: `related_laws[${rl.law_id}].qa_ids references unknown qa_id "${qid}"`,
          });
        }
      }
      if (validLawIds.size > 0 && !validLawIds.has(rl.law_id)) {
        violations.push({
          rule: 'R4',
          level: 'error',
          message: `related_laws references unknown law_id "${rl.law_id}"`,
        });
      }
    }

    if (fs.existsSync(paths.topics)) {
      const topics = readJson<TopicsOutput>(paths.topics);
      const topicNames = new Set(topics.topics.map((t) => t.name));
      for (const kt of summary.key_topics ?? []) {
        if (!topicNames.has(kt)) {
          violations.push({
            rule: 'R5',
            level: 'error',
            message: `key_topics contains "${kt}" not present in topics[].name`,
          });
        }
      }
    }
  }

  for (const p of qa.pairs as QAPair[]) {
    if (!validLawIds.size || !p.related_law_ids) continue;
    for (const lawId of p.related_law_ids) {
      if (!validLawIds.has(lawId)) {
        violations.push({
          rule: 'R6',
          level: 'error',
          message: `qa_pairs[${p.id}].related_law_ids references unknown law_id "${lawId}"`,
        });
      }
    }
  }

  if (fs.existsSync(paths.metadata)) {
    const metadata = readJson<SessionMetadata>(paths.metadata);
    if (metadata.session_kind && !SESSION_KINDS.has(metadata.session_kind)) {
      violations.push({
        rule: 'R7',
        level: 'warn',
        message: `metadata.session_kind="${metadata.session_kind}" is not a known SessionKind`,
      });
    }
    for (const s of metadata.speakers) {
      if (s.role && !SPEAKER_ROLES.has(s.role)) {
        violations.push({
          rule: 'R8',
          level: 'warn',
          message: `speaker "${s.name}".role="${s.role}" is not a known SpeakerRole`,
        });
      }
    }
  }

  return { sessionPath: paths.dir, violations };
}

function printReport(reports: SessionReport[], dataDir: string): { errors: number; warnings: number } {
  let errors = 0;
  let warnings = 0;
  const ruleCounts: Record<string, number> = {};

  for (const r of reports) {
    if (r.violations.length === 0) continue;
    const rel = path.relative(dataDir, r.sessionPath) || r.sessionPath;
    const errs = r.violations.filter((v) => v.level === 'error');
    const warns = r.violations.filter((v) => v.level === 'warn');
    if (errs.length) {
      console.log(`[FAIL] ${rel}`);
      for (const v of errs) {
        console.log(`  ${v.rule}: ${v.message}`);
        ruleCounts[v.rule] = (ruleCounts[v.rule] ?? 0) + 1;
        errors++;
      }
    }
    if (warns.length) {
      console.log(`[WARN] ${rel}`);
      for (const v of warns) {
        console.log(`  ${v.rule}: ${v.message}`);
        ruleCounts[v.rule] = (ruleCounts[v.rule] ?? 0) + 1;
        warnings++;
      }
    }
  }

  const ruleSummary = Object.entries(ruleCounts)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([rule, count]) => `${rule}: ${count}`)
    .join(', ');
  console.log('---');
  console.log(
    `Summary: ${reports.length} sessions checked, ${errors} error(s), ${warnings} warning(s)` +
      (ruleSummary ? ` (${ruleSummary})` : '')
  );
  return { errors, warnings };
}

export function validateDataDir(dataDir: string, lawsPath: string): { errors: number; warnings: number } {
  if (!fs.existsSync(dataDir)) {
    console.error(`[validate-data] DATA_DIR not found: ${dataDir}`);
    return { errors: 1, warnings: 0 };
  }

  const validLawIds = loadLawIds(lawsPath);
  const sessions = discoverSessions(dataDir);
  const reports = sessions.map((s) => validateSession(s, validLawIds));
  return printReport(reports, dataDir);
}

function resolveDefaults(): { dataDir: string; lawsPath: string } {
  const argDir = process.argv[2];
  const dataDir = argDir
    ? path.resolve(process.cwd(), argDir)
    : process.env.DATA_DIR
      ? path.resolve(process.cwd(), process.env.DATA_DIR)
      : path.resolve(process.cwd(), '../data');
  const lawsPath = process.env.LAWS_JSON
    ? path.resolve(process.cwd(), process.env.LAWS_JSON)
    : path.join(dataDir, 'laws', 'laws.json');
  return { dataDir, lawsPath };
}

const isMain =
  typeof process !== 'undefined' &&
  process.argv[1] &&
  path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname);

if (isMain) {
  const { dataDir, lawsPath } = resolveDefaults();
  console.log(`[validate-data] DATA_DIR=${dataDir}`);
  console.log(`[validate-data] LAWS_JSON=${lawsPath}`);
  const result = validateDataDir(dataDir, lawsPath);
  process.exit(result.errors > 0 ? 1 : 0);
}
