import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { taxonomyApi } from '../../api/client'
import {
  AnimatedNumber, Badge, Button, Card, CardHead, Chip, Dialog, Empty, Field,
  Input, PageHeader, Skeleton, Textarea, Tile, focusAndScroll, toastErr, toastOk,
  useConfirm,
} from '../ui'
import {
  BookOpen, Edit, FileText, Layers, Plus, RefreshCw, Search, Sparkles, Trash,
} from '../icons'
import '../styles/admin-core-v3.css'

/* 题型枚举（与后端 question_type 对齐） */
const QUESTION_TYPE_OPTIONS = [
  { value: 'single', label: '单选' },
  { value: 'judge', label: '判断' },
  { value: 'fill', label: '填空' },
  { value: 'essay', label: '简答' },
  { value: 'calc', label: '计算' },
  { value: 'draw', label: '作图' },
]
const TYPE_LABEL = Object.fromEntries(QUESTION_TYPE_OPTIONS.map((t) => [t.value, t.label]))

const EMPTY_FORM = { subject: '', chaptersText: '', types: [] }

/* 兼容后端返回形态：数组 / {subjects:[...]} / 旧分页体 {items:[...]} */
function normalizeSubjects(d) {
  if (Array.isArray(d)) return d
  return (d && (d.subjects || d.items)) || []
}

function TableSkeleton() {
  return (
    <div className="v3-admin-table-wrap">
      <table className="v3-admin-table">
        <thead>
          <tr><th>科目</th><th>章节</th><th>题型</th><th className="is-right">题目数</th><th /></tr>
        </thead>
        <tbody>
          {Array.from({ length: 6 }).map((_, i) => (
            <tr key={i} aria-hidden="true">
              <td><Skeleton width={`${54 + (i % 3) * 12}%`} height={13} /></td>
              <td><Skeleton width="44%" height={12} /></td>
              <td><Skeleton width="72%" height={12} /></td>
              <td><Skeleton width="38%" height={12} style={{ marginLeft: 'auto' }} /></td>
              <td><Skeleton width="76%" height={12} style={{ marginLeft: 'auto' }} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function SubjectManager() {
  const [confirm, confirmDialog] = useConfirm()
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [q, setQ] = useState('')
  const [editor, setEditor] = useState({ open: false, mode: 'create', original: '', form: EMPTY_FORM })
  const subjectNameRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const d = await taxonomyApi.subjects()
      setList(normalizeSubjects(d))
      return true
    } catch (e) {
      setLoadError(e?.message || '加载科目失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const refresh = async () => {
    const ok = await load()
    if (ok) toastOk('科目列表已刷新')
    else toastErr('刷新失败，请检查后端服务后重试')
  }

  const stats = useMemo(() => ({
    subjects: list.length,
    chapters: list.reduce((n, s) => n + (s.chapters || []).length, 0),
    questions: list.reduce((n, s) => n + (Number(s.question_count) || 0), 0),
    custom: list.filter((s) => s.is_custom).length,
  }), [list])

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    if (!kw) return list
    return list.filter((s) => String(s.subject || '').toLowerCase().includes(kw)
      || (s.chapters || []).some((c) => String(c).toLowerCase().includes(kw)))
  }, [list, q])

  const openCreate = () =>
    setEditor({ open: true, mode: 'create', original: '', form: { ...EMPTY_FORM, types: [] } })

  const openEdit = (item) => setEditor({
    open: true,
    mode: 'edit',
    original: item.subject,
    form: {
      subject: item.subject || '',
      chaptersText: (item.chapters || []).join('\n'),
      types: Array.isArray(item.question_types) ? [...item.question_types] : [],
    },
  })

  const closeEditor = () => {
    if (saving) return
    setEditor((ed) => ({ ...ed, open: false }))
  }

  const toggleType = (v) =>
    setEditor((ed) => ({
      ...ed,
      form: {
        ...ed.form,
        types: ed.form.types.includes(v)
          ? ed.form.types.filter((x) => x !== v)
          : [...ed.form.types, v],
      },
    }))

  const handleSubmit = async () => {
    const f = editor.form
    if (!f.subject.trim()) {
      toastErr('请填写科目名称')
      focusAndScroll(subjectNameRef.current)
      return
    }
    const body = {
      subject: f.subject.trim(),
      chapters: f.chaptersText.split('\n').map((s) => s.trim()).filter(Boolean),
      question_types: f.types,
    }
    setSaving(true)
    try {
      if (editor.mode === 'create') {
        await taxonomyApi.createSubject(body)
        toastOk('科目已添加')
      } else {
        // 编辑时 subject 是可能改名后的新名，路径参数用原名 original
        await taxonomyApi.updateSubject(editor.original, body)
        toastOk('科目已更新')
      }
      setEditor((ed) => ({ ...ed, open: false }))
      load()
    } catch (e) {
      toastErr('保存失败：' + (e.message || ''))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (item) => {
    const hasQuestions = (item.question_count || 0) > 0
    const tip = hasQuestions
      ? `科目「${item.subject}」下已有 ${item.question_count} 道题目，删除后这些题目将失去科目归属，确定删除吗？`
      : `确定删除科目「${item.subject}」吗？`
    if (!(await confirm({ title: '删除科目', message: tip, danger: true, confirmText: '删除' }))) return
    try {
      await taxonomyApi.removeSubject(item.subject)
      toastOk('科目已删除')
      load()
    } catch (e) {
      toastErr('删除失败：' + (e.message || ''))
    }
  }

  return (
    <div className="v3-admin-page">
      <PageHeader
        eyebrow="ADMIN · 科目口径"
        title="科目管理"
        sub="维护科目、章节与题型；刷题 / 题库 / 错题本的科目列表由此动态加载。"
        actions={(
          <div className="v3-row" style={{ gap: 8 }}>
            <Button
              variant="outline"
              icon={<RefreshCw size={15} />}
              loading={loading}
              onClick={refresh}
            >
              刷新
            </Button>
            <Button variant="filled" icon={<Plus size={15} />} onClick={openCreate}>
              添加科目
            </Button>
          </div>
        )}
      />

      <div className="v3-admin-stats">
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><BookOpen size={14} />科目</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={stats.subjects} /><em>个</em>
          </span>
          <span className="v3-tile__hint">刷题与题库的科目口径</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><Layers size={14} />章节</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={stats.chapters} /><em>章</em>
          </span>
          <span className="v3-tile__hint">由科目章节列表汇总</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><FileText size={14} />题目</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={stats.questions} /><em>题</em>
          </span>
          <span className="v3-tile__hint">归入这些科目的题目总数</span>
        </Tile>
        <Tile className="v3-admin-stat">
          <span className="v3-tile__label"><Sparkles size={14} />自定义</span>
          <span className="v3-tile__value">
            <AnimatedNumber value={stats.custom} /><em>个</em>
          </span>
          <span className="v3-tile__hint">其余为内置或未登记科目</span>
        </Tile>
      </div>

      <Card className="v3-admin-panel">
        <div className="v3-admin-panel__head">
          <CardHead
            icon={<BookOpen size={16} />}
            title="全部科目"
            sub={loading
              ? '正在同步科目清单…'
              : `共 ${list.length} 个科目${q ? ` · 匹配 ${filtered.length} 个` : ''}`}
            actions={(
              <span className="v3-caption">
                {q ? `搜索「${q}」` : '章节与题型修改后全站立即生效'}
              </span>
            )}
          />
        </div>

        <div className="v3-admin-panel__toolbar">
          <div className="v3-admin-toolbar">
            <div className="v3-admin-toolbar__grow">
              <Input
                icon={<Search size={16} />}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索科目或章节"
                aria-label="搜索科目或章节"
              />
            </div>
            {q ? (
              <Button variant="text" size="sm" onClick={() => setQ('')}>清空搜索</Button>
            ) : null}
            <span className="v3-admin-toolbar__spacer" />
            <span className="v3-admin-toolbar__meta">
              <BookOpen size={13} />
              {loading ? '同步中…' : `${filtered.length} / ${list.length} 个科目`}
            </span>
          </div>
        </div>

        {loading ? <TableSkeleton /> : null}

        {!loading && loadError ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<RefreshCw size={28} />}
              title="加载失败"
              text={loadError}
              action={<Button variant="outline" icon={<RefreshCw size={15} />} onClick={load}>重试</Button>}
            />
          </div>
        ) : null}

        {!loading && !loadError && list.length === 0 ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<BookOpen size={30} />}
              title="暂无科目"
              text="添加第一个科目后，刷题、题库与错题本会立即使用这份清单。"
              action={<Button variant="filled" icon={<Plus size={15} />} onClick={openCreate}>添加科目</Button>}
            />
          </div>
        ) : null}

        {!loading && !loadError && list.length > 0 && filtered.length === 0 ? (
          <div className="v3-admin-panel__body">
            <Empty
              icon={<Search size={28} />}
              title="没有匹配的科目"
              text={`没有找到包含「${q}」的科目或章节。`}
              action={<Button variant="outline" onClick={() => setQ('')}>清空搜索</Button>}
            />
          </div>
        ) : null}

        {!loading && !loadError && filtered.length > 0 ? (
          <div className="v3-admin-table-wrap">
            <table className="v3-admin-table">
              <thead>
                <tr>
                  <th>科目</th>
                  <th>章节</th>
                  <th>题型</th>
                  <th className="is-right">题目数</th>
                  <th className="is-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => {
                  const chapters = Array.isArray(item.chapters) ? item.chapters : []
                  const types = Array.isArray(item.question_types) ? item.question_types : []
                  return (
                    <tr key={item.subject}>
                      <td>
                        <div className="v3-admin-subj-name">
                          <b>{item.subject}</b>
                          <Badge tone={item.unregistered ? 'warning' : item.is_custom ? 'primary' : 'outline'}>
                            {item.unregistered ? '未登记' : item.is_custom ? '自定义' : '内置'}
                          </Badge>
                        </div>
                      </td>
                      <td>
                        <div className="v3-admin-subj-chapters" title={chapters.join(' / ')}>
                          <span className="is-strong">{chapters.length} 章</span>
                          {chapters.length > 0 ? (
                            <small className="v3-truncate" style={{ maxWidth: 210 }}>
                              {chapters.slice(0, 2).join(' / ')}{chapters.length > 2 ? ' …' : ''}
                            </small>
                          ) : null}
                        </div>
                      </td>
                      <td>
                        {types.length === 0 ? (
                          <span className="v3-admin-nil">—</span>
                        ) : (
                          <div className="v3-admin-subj-types">
                            {types.map((t) => (
                              <Badge key={t} tone="outline">{TYPE_LABEL[t] || t}</Badge>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="is-right is-nowrap">
                        <span className="is-strong">{Number(item.question_count) || 0}</span>
                        <span className="is-muted"> 题</span>
                      </td>
                      <td>
                        <div className="v3-admin-table__actions">
                          <Button
                            variant="text"
                            size="sm"
                            icon={<Edit size={14} />}
                            aria-label={`编辑科目 ${item.subject}`}
                            onClick={() => openEdit(item)}
                          >
                            编辑
                          </Button>
                          <Button
                            variant="text"
                            size="sm"
                            icon={<Trash size={14} />}
                            className="v3-admin-danger-text"
                            aria-label={`删除科目 ${item.subject}`}
                            onClick={() => handleDelete(item)}
                          >
                            删除
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        {!loading && !loadError && filtered.length > 0 ? (
          <div className="v3-admin-q-table-note">
            科目是刷题 / 题库 / 错题本 / 学习进度的唯一口径，在这里改名或调整章节会同步影响全站。
          </div>
        ) : null}
      </Card>

      <Dialog
        open={editor.open}
        title={editor.mode === 'create' ? '添加科目' : '编辑科目'}
        sub={editor.mode === 'create'
          ? '新科目会立即出现在题库、刷题与错题本筛选器中。'
          : `原名「${editor.original}」，修改名称后路径参数仍按原名更新。`}
        onClose={saving ? undefined : closeEditor}
        footer={(
          <>
            <Button variant="text" onClick={closeEditor} disabled={saving}>取消</Button>
            <Button variant="filled" onClick={handleSubmit} loading={saving}>保存</Button>
          </>
        )}
      >
        <div className="v3-admin-subj-form">
          <Field
            label={<span>科目名称<span className="v3-admin-required">*</span></span>}
            hint="与题库、错题本共用的科目名，建议保持全站唯一。"
            htmlFor="v3-subject-name"
          >
            <Input
              id="v3-subject-name"
              ref={subjectNameRef}
              value={editor.form.subject}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, subject: e.target.value } }))}
              placeholder="如：数字电子技术"
              maxLength={80}
            />
          </Field>

          <Field
            label="章节（每行一个）"
            hint="每行一个章节名，保存后转为章节列表。"
            htmlFor="v3-subject-chapters"
          >
            <Textarea
              id="v3-subject-chapters"
              rows={5}
              value={editor.form.chaptersText}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, chaptersText: e.target.value } }))}
              placeholder={'第一章 数制与编码\n第二章 逻辑门\n第三章 组合逻辑'}
            />
          </Field>

          <div className="v3-field">
            <span className="v3-label">题型</span>
            <div className="v3-admin-subj-type-grid" role="group" aria-label="题型">
              {QUESTION_TYPE_OPTIONS.map((t) => (
                <Chip
                  key={t.value}
                  active={editor.form.types.includes(t.value)}
                  aria-pressed={editor.form.types.includes(t.value)}
                  onClick={() => toggleType(t.value)}
                >
                  {t.label}
                </Chip>
              ))}
            </div>
            <span className="v3-field__hint">不勾选表示该科目尚未配置题型，仍可正常创建。</span>
          </div>

          <div className="v3-admin-hint-card">
            <Sparkles size={16} />
            <span>科目与章节会作为学习进度、错题归因和知识图谱的聚合维度，删除有题目的科目时请先确认题目去向。</span>
          </div>
        </div>
      </Dialog>
      {confirmDialog}
    </div>
  )
}
