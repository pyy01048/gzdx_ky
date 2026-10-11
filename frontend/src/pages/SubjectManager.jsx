import React, { useState, useEffect, useCallback } from 'react'
import { taxonomyApi } from '../api/client'
import { Empty, Modal, toast } from '../components/UI'
import { Plus, RefreshCw, Edit, Trash, Book } from '../components/Icon'

/* 题型枚举（与后端 question_type 对齐），中文标签 */
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

/* 兼容后端返回形态：数组 [{subject,...}] / {subjects:[...]} / 旧分页体 {items:[...]} */
function normalizeSubjects(d) {
  if (Array.isArray(d)) return d
  return (d && (d.subjects || d.items)) || []
}

export default function SubjectManager() {
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [editor, setEditor] = useState({ open: false, mode: 'create', original: '', form: EMPTY_FORM })

  /* 拉取科目列表（三态：加载中 / 空态 / 失败 toast + 就地提示） */
  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const d = await taxonomyApi.subjects()
      setList(normalizeSubjects(d))
    } catch (e) {
      setLoadError(e.message || '加载科目失败')
      toast('加载科目失败：' + (e.message || ''))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const openCreate = () =>
    setEditor({ open: true, mode: 'create', original: '', form: { ...EMPTY_FORM, types: [] } })

  const openEdit = (item) =>
    setEditor({
      open: true,
      mode: 'edit',
      original: item.subject,
      form: {
        subject: item.subject || '',
        chaptersText: (item.chapters || []).join('\n'),
        types: Array.isArray(item.question_types) ? [...item.question_types] : [],
      },
    })

  const closeEditor = () => setEditor((ed) => ({ ...ed, open: false }))

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

  /* 添加 / 编辑提交：章节多行文本按行转数组 */
  const handleSubmit = async () => {
    const f = editor.form
    if (!f.subject.trim()) { toast('请填写科目名称'); return }
    const body = {
      subject: f.subject.trim(),
      chapters: f.chaptersText.split('\n').map((s) => s.trim()).filter(Boolean),
      question_types: f.types,
    }
    setSaving(true)
    try {
      if (editor.mode === 'create') {
        await taxonomyApi.createSubject(body)
        toast('科目已添加')
      } else {
        // 编辑时 body.subject 即（可能改名后的）新名，路径参数用原名 original
        await taxonomyApi.updateSubject(editor.original, body)
        toast('科目已更新')
      }
      closeEditor()
      load()
    } catch (e) {
      toast('保存失败：' + (e.message || ''))
    } finally {
      setSaving(false)
    }
  }

  /* 删除：有题目的科目给二次确认提示 */
  const handleDelete = async (item) => {
    const hasQuestions = (item.question_count || 0) > 0
    const tip = hasQuestions
      ? `科目「${item.subject}」下已有 ${item.question_count} 道题目，删除后这些题目将失去科目归属，确定删除吗？`
      : `确定删除科目「${item.subject}」吗？`
    if (!window.confirm(tip)) return
    try {
      await taxonomyApi.removeSubject(item.subject)
      toast('科目已删除')
      load()
    } catch (e) {
      toast('删除失败：' + (e.message || ''))
    }
  }

  return (
    <div className="container stack">
      <div className="page-head spread">
        <div>
          <h1 className="page-title">科目管理</h1>
          <p className="page-sub">维护科目、章节与题型；刷题 / 题库 / 错题本的科目列表由此动态加载</p>
        </div>
        <div className="page-actions row">
          <button className="btn ghost" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> 刷新
          </button>
          <button className="btn primary" onClick={openCreate}>
            <Plus size={14} /> 添加科目
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">全部科目</div>
          <div className="card-sub">共 {list.length} 个</div>
        </div>

        {loading ? (
          <div className="table-loading"><span className="table-spinner" />正在加载科目…</div>
        ) : loadError ? (
          <div className="empty-state">
            <div className="empty-state-title">加载失败</div>
            <div className="empty-state-desc">{loadError}</div>
            <div className="empty-state-action">
              <button className="btn ghost" onClick={load}>重试</button>
            </div>
          </div>
        ) : list.length === 0 ? (
          <Empty
            icon={<Book size={32} />}
            title="暂无科目"
            desc="点击右上角「添加科目」创建第一个科目"
            action={<button className="btn primary" onClick={openCreate}>添加科目</button>}
          />
        ) : (
          <div className="table-container">
            <table className="table table-striped">
              <thead>
                <tr>
                  <th>科目</th>
                  <th>章节</th>
                  <th>题型</th>
                  <th>题目数</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {list.map((item) => (
                  <tr key={item.subject}>
                    <td>
                      <div className="row">
                        <b>{item.subject}</b>
                        <span className={`badge ${item.is_custom ? 'accent' : 'neutral'}`}>
                          {item.is_custom ? '自定义' : '内置'}
                        </span>
                      </div>
                    </td>
                    <td>{(item.chapters || []).length} 章</td>
                    <td>
                      <div className="row wrap">
                        {(item.question_types || []).map((t) => (
                          <span key={t} className="chip">{TYPE_LABEL[t] || t}</span>
                        ))}
                      </div>
                    </td>
                    <td>{item.question_count || 0} 题</td>
                    <td>
                      <div className="row">
                        <button className="btn sm ghost" onClick={() => openEdit(item)}>
                          <Edit size={14} /> 编辑
                        </button>
                        <button className="btn sm danger" onClick={() => handleDelete(item)}>
                          <Trash size={14} /> 删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 添加 / 编辑科目弹窗 */}
      <Modal
        open={editor.open}
        title={editor.mode === 'create' ? '添加科目' : '编辑科目'}
        onClose={closeEditor}
        footer={(
          <>
            <button className="btn ghost" onClick={closeEditor}>取消</button>
            <button className="btn primary" onClick={handleSubmit} disabled={saving}>
              {saving ? '保存中…' : '保存'}
            </button>
          </>
        )}
      >
        <div className="form">
          <div className="form-field">
            <label className="form-label">科目名称 <span className="form-required">*</span></label>
            <input
              className="form-input"
              value={editor.form.subject}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, subject: e.target.value } }))}
              placeholder="如：数字电子技术"
            />
          </div>
          <div className="form-field">
            <label className="form-label">章节（每行一个）</label>
            <textarea
              className="form-input"
              rows={5}
              value={editor.form.chaptersText}
              onChange={(e) => setEditor((ed) => ({ ...ed, form: { ...ed.form, chaptersText: e.target.value } }))}
              placeholder={'第一章 数制与编码\n第二章 逻辑门\n第三章 组合逻辑'}
            />
            <span className="form-help">每行一个章节名，保存后转为章节列表</span>
          </div>
          <div className="form-field">
            <label className="form-label">题型</label>
            <div className="row wrap">
              {QUESTION_TYPE_OPTIONS.map((t) => (
                <label key={t.value} className="form-checkbox">
                  <input
                    type="checkbox"
                    checked={editor.form.types.includes(t.value)}
                    onChange={() => toggleType(t.value)}
                  />
                  {t.label}
                </label>
              ))}
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}
