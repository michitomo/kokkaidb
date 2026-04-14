import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FilterPanel from '../FilterPanel';

// テスト用フィクスチャデータ
const mockIndexData = [
  {
    session_id: '56149',
    chamber: 'shugiin',
    date: '2026-04-09',
    committee: '本会議',
    source_url: 'https://www.shugiintv.go.jp/jp/index.php?deli_id=56149',
    speakers: ['古川あおい', '上野賢一郎'],
    parties: ['チームみらい', '自由民主党'],
    topics: ['高額療養費制度', 'インボイス制度'],
    qa_pairs: [
      {
        id: '56149-qa-001',
        topic: '高額療養費制度',
        question_speaker: '古川あおい',
        question_party: 'チームみらい',
        question_summary: 'がん患者への影響について',
        question_intent: '制度改善',
        answer_speaker: '上野賢一郎',
        answer_role: '厚生労働大臣',
        answer_summary: '検討する',
        evasion_score: 0.3,
        has_commitment: true,
        commitment_text: '次期改正で対応',
        video_url: 'https://www.shugiintv.go.jp/jp/index.php?deli_id=56149&time=120',
      },
      {
        id: '56149-qa-002',
        topic: 'インボイス制度',
        question_speaker: '田中まこと',
        question_party: '日本維新の会',
        question_summary: '中小事業者への影響',
        question_intent: '支援策確認',
        answer_speaker: '上野賢一郎',
        answer_role: '厚生労働大臣',
        answer_summary: '別途検討',
        evasion_score: 0.7,
        has_commitment: false,
        commitment_text: '',
        video_url: 'https://www.shugiintv.go.jp/jp/index.php?deli_id=56149&time=2400',
      },
    ],
  },
  {
    session_id: '1234',
    chamber: 'sangiin',
    date: '2026-04-09',
    committee: '法務委員会',
    source_url: 'https://webtv.sangiin.go.jp/webtv/detail.php?sid=1234',
    speakers: ['佐藤けんじ', '橋本一郎'],
    parties: ['公明党', '自由民主党'],
    topics: ['刑事司法改革', '外国人労働者制度'],
    qa_pairs: [
      {
        id: '1234-qa-001',
        topic: '刑事司法改革',
        question_speaker: '佐藤けんじ',
        question_party: '公明党',
        question_summary: '録音録画の効果',
        question_intent: '制度確認',
        answer_speaker: '橋本一郎',
        answer_role: '法務大臣',
        answer_summary: '効果あり',
        evasion_score: 0.1,
        has_commitment: false,
        commitment_text: '',
        video_url: 'https://webtv.sangiin.go.jp/webtv/detail.php?sid=1234#180',
      },
    ],
  },
];

const mockCommittees = [{ name: '本会議' }, { name: '法務委員会' }];
const mockParties = [
  { name: 'チームみらい' },
  { name: '自由民主党' },
  { name: '公明党' },
  { name: '日本維新の会' },
];
const mockTopics = [
  { name: '高額療養費制度' },
  { name: 'インボイス制度' },
  { name: '刑事司法改革' },
  { name: '外国人労働者制度' },
];

// fetch モック
function setupFetchMock() {
  const mockFetch = vi.fn((url) => {
    const urlStr = String(url);
    let data;
    if (urlStr.includes('index.json')) data = mockIndexData;
    else if (urlStr.includes('committees.json')) data = mockCommittees;
    else if (urlStr.includes('parties.json')) data = mockParties;
    else if (urlStr.includes('topics.json')) data = mockTopics;
    else data = [];
    return Promise.resolve({ json: () => Promise.resolve(data) });
  });
  vi.stubGlobal('fetch', mockFetch);
  return mockFetch;
}

// URL モック
function setupUrlMock(search = '') {
  Object.defineProperty(window, 'location', {
    value: { pathname: '/browse', search, href: `/browse${search}` },
    writable: true,
  });
  vi.stubGlobal('history', { replaceState: vi.fn() });
}

describe('FilterPanel', () => {
  beforeEach(() => {
    setupFetchMock();
    setupUrlMock();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('ローディング中にスケルトンUIが表示される', () => {
    render(<FilterPanel />);
    expect(document.querySelector('.filter-panel-loading')).toBeInTheDocument();
  });

  it('データ読み込み後にフィルタUIが表示される', async () => {
    render(<FilterPanel />);
    await waitFor(() => {
      expect(screen.getByText('全て')).toBeInTheDocument();
    });
    expect(screen.getByText('衆議院')).toBeInTheDocument();
    expect(screen.getByText('参議院')).toBeInTheDocument();
  });

  it('初期状態で全件（3件）が表示される', async () => {
    render(<FilterPanel />);
    await waitFor(() => {
      const countEl = document.querySelector('.qa-count');
      expect(countEl?.textContent).toMatch(/3件 \/ 全3件/);
    });
  });

  it('衆議院フィルタで件数が減る', async () => {
    const user = userEvent.setup();
    render(<FilterPanel />);
    await waitFor(() => screen.getByText('衆議院'));

    // 衆議院ラジオボタンをクリック
    const radios = screen.getAllByRole('radio');
    const shugiinRadio = radios.find((r) => r.value === 'shugiin');
    await user.click(shugiinRadio);

    await waitFor(() => {
      // 衆議院のQ&Aペアは2件
      const countEl = document.querySelector('.qa-count');
      expect(countEl?.textContent).toMatch(/2件 \/ 全3件/);
    });
  });

  it('日付範囲フィルタが動作する', async () => {
    render(<FilterPanel />);
    await waitFor(() => screen.getByLabelText('開始日'));

    fireEvent.change(screen.getByLabelText('開始日'), {
      target: { value: '2026-04-10' },
    });

    // 2026-04-09以前のデータはフィルタされ、2026-04-10以降のみ残る
    // テストデータは全て2026-04-09なので0件になるはず
    await waitFor(() => {
      expect(screen.getByText(/0件/)).toBeInTheDocument();
    });
  });

  it('0件の場合に空状態メッセージが表示される', async () => {
    render(<FilterPanel />);
    await waitFor(() => screen.getByLabelText('開始日'));

    fireEvent.change(screen.getByLabelText('開始日'), {
      target: { value: '2099-01-01' },
    });

    await waitFor(() => {
      expect(screen.getByText(/該当するQ&Aペアが見つかりません/)).toBeInTheDocument();
    });
  });

  it('フィルタリセットボタンで全フィルタがクリアされる', async () => {
    const user = userEvent.setup();
    render(<FilterPanel />);
    await waitFor(() => screen.getByText('衆議院'));

    // 衆議院フィルタを適用
    await user.click(screen.getAllByRole('radio')[1]);

    await waitFor(() => {
      expect(screen.getByText('フィルタをリセット')).toBeInTheDocument();
    });

    await user.click(screen.getByText('フィルタをリセット'));

    // qa-count span で "3件 / 全3件" が表示されることを確認
    await waitFor(() => {
      const countEl = document.querySelector('.qa-count');
      expect(countEl?.textContent).toMatch(/3件 \/ 全3件/);
    });
  });

  it('URLパラメータからフィルタ状態を復元する', async () => {
    setupUrlMock('?chamber=sangiin');

    render(<FilterPanel />);
    await waitFor(() => {
      // 参議院のQ&Aは1件
      const countEl = document.querySelector('.qa-count');
      expect(countEl?.textContent).toMatch(/1件 \/ 全3件/);
    });
  });

  it('fetch失敗時にエラーメッセージが表示される', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

    render(<FilterPanel />);
    await waitFor(() => {
      expect(screen.getByText(/データの読み込みに失敗しました/)).toBeInTheDocument();
    });
  });
});
