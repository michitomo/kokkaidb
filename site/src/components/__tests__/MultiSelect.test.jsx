import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MultiSelect from '../MultiSelect';

describe('MultiSelect', () => {
  const defaultOptions = ['内閣委員会', '法務委員会', '本会議', '予算委員会'];

  it('ラベルとプレースホルダーが表示される', () => {
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={[]}
        onChange={() => {}}
      />
    );
    expect(screen.getByText('委員会')).toBeInTheDocument();
    expect(screen.getByText('委員会（全て）')).toBeInTheDocument();
  });

  it('クリックでドロップダウンが開く', async () => {
    const user = userEvent.setup();
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={[]}
        onChange={() => {}}
      />
    );
    await user.click(screen.getByRole('button'));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByText('内閣委員会')).toBeInTheDocument();
  });

  it('選択するとonChangeが呼ばれる', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={[]}
        onChange={onChange}
      />
    );
    await user.click(screen.getByRole('button'));
    await user.click(screen.getByRole('option', { name: /内閣委員会/ }));
    expect(onChange).toHaveBeenCalledWith(['内閣委員会']);
  });

  it('選択済み項目をクリックすると解除される', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={['内閣委員会']}
        onChange={onChange}
      />
    );
    await user.click(screen.getByRole('button'));
    // ドロップダウン内の option をクリック（role="option" で特定）
    await user.click(screen.getByRole('option', { name: /内閣委員会/ }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('検索テキストで候補が絞られる', async () => {
    const user = userEvent.setup();
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={[]}
        onChange={() => {}}
      />
    );
    await user.click(screen.getByRole('button'));
    const searchInput = screen.getByPlaceholderText('絞り込み...');
    await user.type(searchInput, '法務');
    expect(screen.getByText('法務委員会')).toBeInTheDocument();
    expect(screen.queryByText('内閣委員会')).not.toBeInTheDocument();
  });

  it('検索で一致なしの場合「候補なし」が表示される', async () => {
    const user = userEvent.setup();
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={[]}
        onChange={() => {}}
      />
    );
    await user.click(screen.getByRole('button'));
    const searchInput = screen.getByPlaceholderText('絞り込み...');
    await user.type(searchInput, 'xxxxxxxxxx');
    expect(screen.getByText('候補なし')).toBeInTheDocument();
  });

  it('クリアボタンで全選択が解除される', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={['内閣委員会', '法務委員会']}
        onChange={onChange}
      />
    );
    await user.click(screen.getByRole('button'));
    await user.click(screen.getByText('クリア'));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('value が1件の場合、その名前がトリガーに表示される', () => {
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={['内閣委員会']}
        onChange={() => {}}
      />
    );
    expect(screen.getByText('内閣委員会')).toBeInTheDocument();
  });

  it('value が2件以上の場合「〇〇 他N件」と表示される', () => {
    render(
      <MultiSelect
        label="委員会"
        options={defaultOptions}
        value={['内閣委員会', '法務委員会', '本会議']}
        onChange={() => {}}
      />
    );
    expect(screen.getByText('内閣委員会 他2件')).toBeInTheDocument();
  });
});
