import React, { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { favoritesApi } from '../../api/client'
import useApiData from '../../hooks/useApiData'
import { clearFavoriteCache } from '../../hooks/useFavorites'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Empty, IconButton, Input, PageHeader,
  Segmented, Skeleton, Tile, toastErr, toastOk,
} from '../ui'
import {
  AlertCircle, AlertTriangle, Brain, ChevronLeft, ChevronRight, ExternalLink, FileText,
  Layers, ListChecks, RefreshCw, Search, Trash, Type,
} from '../icons'
import '../styles/favorites-v3.css'

/* ==========================================================================
   收藏夹（Aurora v3）
   全站统一收藏中心：文档 / 题目 / 错题 / 知识点 / 单词 / 卡片 / 链接。
   数据源：GET /favorites（item_type / q / limit / offset）· DELETE /favorites/{type}/{id}
   ========================================================================== */

const TYPE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'document', label: '文档' },
  { value: 'question', label: '题目' },
  { value: 'error', label: '错题' },
  { value: 'kp', label: '知识点' },
  { value: 'word', label: '单词' },
  { value: 'flashcard', label: '卡片' },
  { value: 'link', label: '链接' },
]

/* 类型色全部取 v3 设计令牌，随明暗主题自动切换 */
const TYPE_META = {
  document: { name: '文档', color: 'var(--v3-primary)', icon: FileText, to: (id) => `/documents?focus=${id}` },
  question: { name: '题目', color: 'var(--v3-secondary)', icon: ListChecks, to: () => '/quiz' },
  error: { name: '错题', color: 'var(--v3-danger)', icon: AlertTriangle, to: () => '/error-review' },
  kp: { name: '知识点', color: 'var(--v3-gemini-4)', icon: Brain, to: (id) => `/knowledge/${id}` },
  word: { name: '单词', color: 'var(--v3-success)', icon: Type, to: () => '/words' },
  flashcard: { name: '卡片', color: 'var(--v3-tertiary)', icon: Layers, to: () => '/cards' },
  link: { name: '链接', color: 'var(--v3-text-3)', icon: ExternalLink, to: () => null },
}

const FALLBACK_META = { name: '收藏', color: 'var(--v3-text-3)', icon: Layers, to: () => null }

const PAGE_SIZE = 50

function fmtDate(s) {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameYear = d.getFullYear() === now.getFullYear()
  const pad = (n) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return sameYear
    ? `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
    : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function StatTile({ icon, label, value, unit, hint }) {
  return (
    <Tile span={4} className="fv3-stat">
      <span className="v3-tile__label">{icon}{label}</span>
      <span className="v3-tile__value">
        <AnimatedNumber value={value} />
        <em>{unit}</em>
      </span>
      <span className="v3-tile__hint">{hint}</span>
    </Tile>
  )
}

export default function Favorites() {
  const navigate = useNavigate()
  const [type, setType] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const [draft, setDraft] = useState('')
  const [removingId, setRemovingId] = useState(null)

  const fetcher = useCallback(
    () => favoritesApi.list({
      item_type: type || undefined,
      q: q || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [type, q, page],
  )

  const { data, loading, error, reload } = useApiData(fetcher, { deps: [type, q, page] })

  const items = data?.items || []
  const total = data?.total || 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const onSearch = useCallback((e) => {
    e.preventDefault()
    setQ(draft.trim())
    setPage(0)
  }, [draft])

  const clearSearch = () => {
    setDraft('')
    setQ('')
    setPage(0)
  }

  const remove = useCallback(async (item) => {
    setRemovingId(item.id)
    try {
      await favoritesApi.remove(item.item_type, item.item_id)
      // 进程内缓存同步失效，否则回到原页面星标仍是亮的（状态漂移）。
      clearFavoriteCache()
      toastOk('已取消收藏')
      await reload()
    } catch (err) {
      toastErr(err?.message || '操作失败')
    } finally {
      setRemovingId(null)
    }
  }, [reload])

  const grouped = useMemo(() => {
    const m = new Map()
    for (const it of items) {
      if (!m.has(it.item_type)) m.set(it.item_type, [])
      m.get(it.item_type).push(it)
    }
    return [...m.entries()]
  }, [items])

  const refresh = async () => {
    const ok = await reload()
    if (ok) toastOk('收藏列表已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  const activeTypeLabel = TYPE_OPTIONS.find((o) => o.value === type)?.label || '全部'

  const header = (
    <PageHeader
      eyebrow="FAVORITES · 收藏中心"
      title="我的收藏"
      sub="文档、题目、错题、知识点、单词、卡片 —— 任意页面点星标即收进此处"
      actions={(
        <IconButton
          label="刷新收藏"
          icon={<RefreshCw size={17} />}
          onClick={refresh}
          disabled={loading}
        />
      )}
    />
  )

  /* ---------- 首次加载 ---------- */
  if (loading && !data) {
    return (
      <div className="v3-stack v3-favorites">
        {header}
        <div className="v3-bento">
          {[0, 1, 2].map((i) => (
            <Tile span={4} key={i} className="fv3-stat fv3-stat--skeleton">
              <Skeleton height={14} width="52%" />
              <Skeleton height={34} width="40%" style={{ marginTop: 18 }} />
              <Skeleton height={11} width="66%" style={{ marginTop: 10 }} />
            </Tile>
          ))}
        </div>
        <Card>
          <Skeleton height={44} width="100%" />
        </Card>
        <Card>
          <CardHead
            icon={<Layers size={17} />}
            title="收藏列表"
            sub="正在加载收藏…"
          />
          <div className="fv3-skeleton-list">
            {[0, 1, 2, 3].map((i) => (
              <div className="fv3-skel-row" key={i}>
                <Skeleton height={38} width={38} radius={12} />
                <div className="fv3-skel-main">
                  <Skeleton height={13} width={`${44 + (i % 3) * 12}%`} />
                  <Skeleton height={11} width={`${60 + (i % 2) * 16}%`} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    )
  }

  /* ---------- 失败 ---------- */
  if (error) {
    return (
      <div className="v3-stack v3-favorites">
        {header}
        <Card className="fv3-error-card">
          <Empty
            icon={<AlertCircle size={26} />}
            title="收藏加载失败"
            text={error}
            action={<Button variant="tonal" icon={<RefreshCw size={16} />} loading={loading} onClick={reload}>重新加载</Button>}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-stack v3-favorites">
      {header}

      <div className="v3-bento">
        <StatTile
          icon={<Layers size={15} />}
          label="收藏总数"
          value={total}
          unit="条"
          hint={type ? `当前范围：${activeTypeLabel}` : '全站收藏汇总'}
        />
        <StatTile
          icon={<ListChecks size={15} />}
          label="本页条目"
          value={items.length}
          unit="条"
          hint={q ? `搜索「${q}」的结果` : `每页最多 ${PAGE_SIZE} 条`}
        />
        <StatTile
          icon={<FileText size={15} />}
          label="类型分组"
          value={grouped.length}
          unit="类"
          hint={total ? '按收藏类型分组展示' : '还没有收藏记录'}
        />
      </div>

      {/* 筛选与搜索 */}
      <Card className="fv3-toolbar">
        <div className="fv3-toolbar__row">
          <Segmented
            ariaLabel="收藏类型"
            options={TYPE_OPTIONS}
            value={type}
            onChange={(v) => { setType(v); setPage(0) }}
          />
          <span className="fv3-toolbar__hint">
            {loading ? '同步中…' : `共 ${total} 条 · 第 ${page + 1} / ${totalPages} 页`}
          </span>
        </div>
        <form className="fv3-search" onSubmit={onSearch}>
          <div className="fv3-search__field">
            <Input
              icon={<Search size={16} />}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="搜索标题 / 摘要"
              aria-label="搜索收藏"
            />
          </div>
          <Button type="submit" variant="tonal" size="sm" icon={<Search size={15} />}>搜索</Button>
          {(q || draft) ? (
            <Button type="button" variant="text" size="sm" onClick={clearSearch}>清除</Button>
          ) : null}
          {q ? <Badge tone="primary">结果：{q}</Badge> : null}
        </form>
      </Card>

      {items.length === 0 ? (
        <Card className="fv3-empty-card">
          <Empty
            icon={<Layers size={26} />}
            title={q ? '没有匹配的收藏' : '还没有收藏'}
            text={q
              ? `没有匹配「${q}」的收藏，换个关键词试试。`
              : '在文档、题目、错题等页面点击右上星标即可收藏到这里。'}
            action={q ? (
              <Button variant="tonal" onClick={clearSearch}>清除搜索</Button>
            ) : type ? (
              <Button variant="tonal" onClick={() => { setType(''); setPage(0) }}>查看全部收藏</Button>
            ) : (
              <Button variant="gradient" icon={<FileText size={16} />} onClick={() => navigate('/documents')}>去文档库看看</Button>
            )}
          />
        </Card>
      ) : (
        <>
          <div className="fv3-groups">
            {grouped.map(([t, list]) => {
              const meta = TYPE_META[t] || { ...FALLBACK_META, name: t }
              const GroupIcon = meta.icon
              return (
                <Card key={t} className="fv3-group-card" style={{ '--fv3-type': meta.color }}>
                  <CardHead
                    icon={<GroupIcon size={17} />}
                    title={(
                      <span className="fv3-group-title">
                        <span className="fv3-dot" aria-hidden="true" />
                        {meta.name}
                      </span>
                    )}
                    sub={`${list.length} 条 · 点击任意收藏可前往原页面`}
                    actions={<Badge tone="outline">{list.length}</Badge>}
                  />
                  <div className="fv3-list">
                    {list.map((it) => {
                      const to = meta.to?.(it.item_id)
                      const ItemIcon = meta.icon
                      return (
                        <div
                          key={it.id}
                          className={`fv3-item${to ? ' is-link' : ''}`}
                          role={to ? 'button' : undefined}
                          tabIndex={to ? 0 : undefined}
                          aria-label={to ? `打开收藏：${it.title || meta.name}` : undefined}
                          onClick={() => { if (to) navigate(to) }}
                          onKeyDown={(e) => {
                            if (!to || e.target !== e.currentTarget) return
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              navigate(to)
                            }
                          }}
                        >
                          <span className="fv3-item__orb" aria-hidden="true">
                            <ItemIcon size={17} />
                          </span>
                          <span className="fv3-item__main">
                            <span className="fv3-item__title">
                              {it.title || `（无标题 ${meta.name} #${it.item_id}）`}
                            </span>
                            {it.snippet ? <span className="fv3-item__snippet">{it.snippet}</span> : null}
                            <span className="fv3-item__meta">
                              <span className="fv3-item__id">#{it.item_id}</span>
                              {it.created_at ? <span>收藏于 {fmtDate(it.created_at)}</span> : null}
                              {to ? <span className="fv3-item__go">查看原文</span> : <span className="fv3-item__go is-static">仅收藏</span>}
                            </span>
                          </span>
                          <span className="fv3-item__actions">
                            <ChevronRight size={16} className="fv3-item__chev" />
                            <Button
                              variant="text"
                              size="sm"
                              icon={<Trash size={14} />}
                              loading={removingId === it.id}
                              onClick={(e) => { e.stopPropagation(); remove(it) }}
                              aria-label={`取消收藏：${it.title || meta.name}`}
                            >
                              移除
                            </Button>
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </Card>
              )
            })}
          </div>

          {totalPages > 1 ? (
            <div className="fv3-pager">
              <Button
                variant="tonal"
                size="sm"
                icon={<ChevronLeft size={15} />}
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                上一页
              </Button>
              <span className="fv3-pager__info">第 {page + 1} / {totalPages} 页 · 共 {total} 条</span>
              <Button
                variant="tonal"
                size="sm"
                trailingIcon={<ChevronRight size={15} />}
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          ) : null}
        </>
      )}

      <p className="fv3-footnote">
        收藏数据来自全站统一收藏接口；移除后会同步失效前端收藏缓存，原页面的星标状态随之更新。
      </p>
    </div>
  )
}
