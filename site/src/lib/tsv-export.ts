/**
 * Q&AペアをTSV形式に変換するユーティリティ。
 * Google Sheets貼り付け想定（15列）。
 */

import type { IndexEntry } from '../../scripts/generate-api';

// TSVの列ヘッダ（18列）
const TSV_HEADERS = [
  '日付',
  '院',
  '委員会',
  'トピック',
  '質問者',
  '質問者所属',
  '質問要旨',
  '質問精度',
  '根拠品質',
  '答弁者',
  '答弁者役職',
  '答弁要旨',
  '答弁網羅性',
  'コミット強度',
  '約束内容',
  '議事録価値',
  '動画URL',
  '出典URL',
] as const;

/**
 * タブ・改行を安全な文字に変換する。
 * - タブ → スペース
 * - 改行 → リテラル "\n"（表示用）
 */
function escapeTsv(value: string | number | boolean): string {
  const str = String(value);
  return str.replace(/\t/g, ' ').replace(/\r?\n/g, '\\n');
}

/**
 * chamber を日本語に変換する。
 */
export function chamberLabel(chamber: string): string {
  return chamber === 'shugiin' ? '衆議院' : '参議院';
}

/**
 * commitment_strength を文字列ラベルに変換する。
 */
export function commitmentStrengthLabel(strength: number | undefined): string {
  if (!strength || strength === 0) return 'なし';
  if (strength < 0.2) return '検討';
  if (strength < 0.5) return '弱';
  if (strength < 0.7) return '中';
  if (strength < 0.9) return '強';
  return '即時';
}

export interface TsvQAPair {
  id: string;
  topic: string;
  question_speaker: string;
  question_party: string;
  question_summary: string;
  question_intent: string;
  question_sharpness?: number;
  evidence_grounding?: number;
  answer_speaker: string;
  answer_role: string;
  answer_summary: string;
  answer_completeness?: number;
  commitment_strength?: number;
  commitment_text: string;
  record_value?: number;
  video_url: string;
}

export interface TsvSession {
  session_id: string;
  chamber: string;
  date: string;
  committee: string;
  source_url: string;
}

/**
 * Q&Aペア配列をTSV文字列に変換する（ヘッダ行 + データ行）。
 *
 * @param pairs  Q&Aペアの配列
 * @param sessions  セッション情報の配列（session_id で対応付け）
 * @returns TSV文字列（空の場合はヘッダ行のみ）
 */
export function qaPairsToTsv(
  pairs: TsvQAPair[],
  sessions: TsvSession[]
): string {
  const sessionMap = new Map(sessions.map((s) => [s.session_id, s]));

  const headerRow = TSV_HEADERS.join('\t');

  if (pairs.length === 0) {
    return headerRow;
  }

  // セッション情報はペアのIDプレフィックスから逆引き
  // ペアには session_id フィールドがないので、呼び出し元が pairs に session を紐付けて渡す
  // → この関数では pairs と sessions を並列に受け取り、indexで対応させる想定ではなく、
  //    呼び出し元が IndexEntry[] を展開して session を付与する形で使う。
  // この関数は IndexEntry を flat に受け取る版も提供する。
  const rows = pairs.map((pair, i) => {
    // sessions 配列から対応するセッションを探す
    // pairs[i] の呼び出し元は sessions[i] と対応させる（一対一対応）
    const session = sessions[i];
    return [
      escapeTsv(session?.date ?? ''),
      escapeTsv(chamberLabel(session?.chamber ?? '')),
      escapeTsv(session?.committee ?? ''),
      escapeTsv(pair.topic),
      escapeTsv(pair.question_speaker),
      escapeTsv(pair.question_party),
      escapeTsv(pair.question_summary),
      escapeTsv((pair.question_sharpness ?? 0.5).toFixed(2)),
      escapeTsv((pair.evidence_grounding ?? 0.5).toFixed(2)),
      escapeTsv(pair.answer_speaker),
      escapeTsv(pair.answer_role),
      escapeTsv(pair.answer_summary),
      escapeTsv((pair.answer_completeness ?? 0.5).toFixed(2)),
      escapeTsv(commitmentStrengthLabel(pair.commitment_strength)),
      escapeTsv(pair.commitment_text),
      escapeTsv((pair.record_value ?? 0.5).toFixed(2)),
      escapeTsv(pair.video_url),
      escapeTsv(session?.source_url ?? ''),
    ].join('\t');
  });

  return [headerRow, ...rows].join('\n');
}

/**
 * IndexEntry[] からフラットなTSV文字列を生成するヘルパー。
 * FilterPanel での利用を想定。
 */
export function indexEntriesToTsv(entries: IndexEntry[]): string {
  const pairs: TsvQAPair[] = [];
  const sessions: TsvSession[] = [];

  for (const entry of entries) {
    for (const qa of entry.qa_pairs) {
      pairs.push(qa);
      sessions.push({
        session_id: entry.session_id,
        chamber: entry.chamber,
        date: entry.date,
        committee: entry.committee,
        source_url: entry.source_url,
      });
    }
  }

  return qaPairsToTsv(pairs, sessions);
}
