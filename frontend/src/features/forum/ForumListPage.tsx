/** ForumListPage - the questions: search, sort, tag filter. Public. */
import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, Input, Pagination, Segmented, Spin, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { useT } from '../../i18n/hooks';
import { findContext } from '../../components/calculation/calcContexts';
import { forumApi, forumErrorMessage, ForumSort } from './forumApi';

const SORTS: ForumSort[] = ['active', 'newest', 'votes', 'unanswered'];
const PER_PAGE = 20;

const ForumListPage: React.FC = () => {
  const t = useT();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const sort = (SORTS.includes(params.get('sort') as ForumSort) ? params.get('sort') : 'active') as ForumSort;
  const tag = params.get('tag') ?? undefined;
  const q = params.get('q') ?? undefined;
  const step = params.get('step') ?? undefined;
  const mine = params.get('mine') === '1';
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1);
  const [search, setSearch] = useState(q ?? '');
  useEffect(() => setSearch(q ?? ''), [q]);

  const list = useQuery({
    queryKey: ['forum', 'list', { sort, tag, q, step, mine, page }],
    queryFn: () => forumApi.list({ sort, tag, q, step, mine, page, per_page: PER_PAGE }),
  });
  const tags = useQuery({ queryKey: ['forum', 'tags'], queryFn: () => forumApi.tags(), staleTime: 5 * 60_000 });

  const update = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!('page' in changes)) next.delete('page');
    setParams(next);
  };

  const ask = () => {
    const target = `/forum/ask${step ? `?step=${encodeURIComponent(step)}` : ''}`;
    navigate(user ? target : `/login?next=${encodeURIComponent(target)}`);
  };

  return (
    <div className="grid gap-6 md:grid-cols-[1fr_16rem]">
      <section>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h1 className="text-2xl font-semibold m-0">{step ? t('forum.aboutStep', { step: findContext(step) ? t(findContext(step)!.item.labelKey) : step }) : tag ? t('forum.taggedWith', { tag }) : t('forum.allQuestions')}</h1>
          <Button type="primary" onClick={ask}>{t('forum.ask')}</Button>
        </div>
        <Input.Search
          allowClear
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSearch={(value) => update({ q: value.trim() || undefined })}
          placeholder={t('forum.searchPlaceholder')}
          className="mb-3"
        />
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <Segmented
            value={sort}
            onChange={(value) => update({ sort: value === 'active' ? undefined : String(value) })}
            options={SORTS.map((s) => ({ value: s, label: t(`forum.sort.${s}`) }))}
          />
          {user && (
            <Button size="small" type={mine ? 'primary' : 'default'} onClick={() => update({ mine: mine ? undefined : '1' })}>{t('forum.mine')}</Button>
          )}
          {(tag || q || step) && <Button size="small" onClick={() => setParams(new URLSearchParams())}>{t('forum.clearFilters')}</Button>}
        </div>

        {list.isLoading && <div className="py-10 text-center"><Spin /></div>}
        {list.isError && <Alert type="error" showIcon title={forumErrorMessage(list.error, t('forum.loadFailed'))} />}
        {list.data && list.data.items.length === 0 && <Empty description={t('forum.noQuestions')} />}
        <ul className="list-none p-0 m-0 divide-y divide-gray-200 bg-white rounded-lg shadow-sm">
          {list.data?.items.map((p) => (
            <li key={p.id} className="flex gap-4 p-4">
              <div className="flex flex-col items-center text-xs text-gray-600 w-20 flex-shrink-0 gap-1">
                <span><strong className="text-base text-gray-900">{p.score}</strong> {t('forum.votes')}</span>
                <span className={p.accepted || p.answer_count > 0 ? 'text-green-700' : ''}>
                  <strong className="text-base">{p.answer_count}</strong> {t('forum.answers')}
                </span>
                <span>{p.view_count} {t('forum.views')}</span>
              </div>
              <div className="min-w-0 flex-1">
                <Link to={`/forum/q/${p.id}`} className="text-base font-medium text-green-800 hover:underline break-words">{p.title}</Link>
                {p.pending_review && <Tag color="orange" className="ml-2">{t('forum.heldBadge')}</Tag>}
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {p.tags.map((name) => (
                    <Tag key={name} className="cursor-pointer m-0" onClick={() => update({ tag: name })}>{name}</Tag>
                  ))}
                  <span className="ml-auto text-xs text-gray-500">
                    {p.author?.name ?? t('forum.formerMember')} · {new Date(p.last_activity_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>
        {list.data && list.data.total > PER_PAGE && (
          <Pagination className="mt-4 text-center" current={page} pageSize={PER_PAGE} total={list.data.total} showSizeChanger={false}
            onChange={(p) => update({ page: String(p) })} />
        )}
      </section>

      <aside className="bg-white rounded-lg shadow-sm p-4 h-fit">
        <h2 className="text-sm font-semibold uppercase text-gray-500 mt-0">{t('forum.tags')}</h2>
        <div className="flex flex-wrap gap-1">
          {tags.data?.map((x) => (
            <Tag key={x.name} color={x.name === tag ? 'green' : undefined} className="cursor-pointer m-0" onClick={() => update({ tag: x.name === tag ? undefined : x.name })}>
              {x.name} <span className="text-gray-400">{x.used_count}</span>
            </Tag>
          ))}
        </div>
      </aside>
    </div>
  );
};

export default ForumListPage;
