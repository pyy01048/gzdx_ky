import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Modal, toastOk, toastErr, focusAndScroll, useConfirm } from '../components/UI'
import { EmptyState } from '../components/States'
import { taxonomyApi } from '../api/client'

/* =====================================================================
 * 文档知识库 · 内联科目维护弹窗（自 Documents.jsx 拆出）
 * V3 治理：增删改科目，走科目 API，不硬编码。含添加/编辑子弹窗。
 * open 由容器传入；科目列表/编辑态/保存动作在本组件。
 * ===================================================================== */

export default function DocSubjectMgrModal({ open, onClose, onSubjectsChanged }) {
  const [confirm, confirmDialog] = useConfirm()
  const [subjList, setSubjList] = useState([])
  const [subjBusy, setSubjBusy] = useState(false)
  const [subjEditor, setSubjEditor] = useState({ open: false, mode: 'create', original: '', name: '' })
  const subjNameRef = useRef(null)

  const loadSubjects = useCallback(async () => {
    setSubjBusy(true)
    try {
      const d = await taxonomyApi.subjects()
      const list = Array.isArray(d) ? d : (d?.subjects || d?.items || [])
      setSubjList(Array.isArray(list) ? list : [])
      return true
    } catch (e) {
      return false
    } finally {
      setSubjBusy(false)
    }
  }, [])

  /* 手动刷新：成功/失败都给明确反馈（弹窗内也能看到） */
  const refreshSubjects = async () => {
    const ok = await loadSubjects()
    if (ok) toastOk('科目列表已刷新')
    else toastErr('刷新失败，请稍后重试')
  }

  /* 打开即拉取科目列表，与拆分前 openSubjectMgr 同步发起；闩锁保证一次打开只拉一次 */
  const loadedOpenRef = useRef(false)
  useEffect(() => {
    if (open && !loadedOpenRef.current) loadSubjects()
    loadedOpenRef.current = open
  }, [open, loadSubjects])

  const submitSubjectForm = async () => {
    const name = (subjEditor.name || '').trim()
    if (!name) {
      toastErr('请填写科目名称')
      focusAndScroll(subjNameRef.current)
      return
    }
    setSubjBusy(true)
    try {
      if (subjEditor.mode === 'create') {
        await taxonomyApi.createSubject({ subject: name })
        toastOk('科目已添加')
      } else {
        await taxonomyApi.updateSubject(subjEditor.original, { subject: name })
        toastOk('科目已更新')
      }
      setSubjEditor({ open: false, mode: 'create', original: '', name: '' })
      await loadSubjects()
      onSubjectsChanged()
    } catch (e) {
      toastErr(`保存失败：${e.message}`)
    } finally {
      setSubjBusy(false)
    }
  }

  const removeSubject = async (item) => {
    const n = item?.question_count || 0
    const tip = n > 0
      ? `科目「${item.subject}」下已有 ${n} 道题目，删除后这些题目将失去科目归属，确定删除吗？`
      : `确定删除科目「${item.subject}」吗？`
    if (!(await confirm({ title: '删除科目', message: tip, danger: true }))) return
    try {
      await taxonomyApi.removeSubject(item.subject)
      toastOk('科目已删除')
      await loadSubjects()
      onSubjectsChanged()
    } catch (e) {
      toastErr(`删除失败：${e.message}`)
    }
  }

  return (
    <>
    <Modal
      open={open}
      title="科目维护（文档页内联入口）"
      onClose={onClose}
      footer={<button className="btn primary" onClick={onClose}>关闭</button>}
    >
      <div className="doc-subjmgr">
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
          <span className="badge info">共 {subjList.length} 个科目</span>
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            <button className="btn ghost sm" disabled={subjBusy} onClick={refreshSubjects}>刷新</button>
            <button className="btn primary sm" onClick={() => setSubjEditor({ open: true, mode: 'create', original: '', name: '' })}>+ 添加科目</button>
          </div>
        </div>
        {subjBusy && subjList.length === 0 ? (
          <div className="loading-inline"><i />加载科目…</div>
        ) : subjList.length === 0 ? (
          <EmptyState icon="资料" title="暂无科目" desc="点击「添加科目」创建第一个科目" />
        ) : (
          <div className="list">
            {subjList.map((s) => (
              <div key={s.subject} className="list-row">
                <div className="lr-main">
                  <div className="lr-title">{s.subject}</div>
                  <div className="lr-meta">
                    {s.unregistered ? '未登记' : s.is_custom ? '自定义' : '内置'}
                    {s.question_count != null ? ` · ${s.question_count} 题` : ''}
                    {s.document_count != null ? ` · ${s.document_count} 篇资料` : ''}
                  </div>
                </div>
                <div className="lr-actions">
                  <button className="btn ghost sm" onClick={() => setSubjEditor({ open: true, mode: 'edit', original: s.subject, name: s.subject })}>编辑</button>
                  <button className="btn danger sm" onClick={() => removeSubject(s)}>删除</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 添加 / 编辑子弹窗 */}
      <Modal
        open={subjEditor.open}
        title={subjEditor.mode === 'create' ? '添加科目' : '编辑科目'}
        onClose={() => setSubjEditor({ open: false, mode: 'create', original: '', name: '' })}
        footer={(
          <>
            <button className="btn ghost" onClick={() => setSubjEditor({ open: false, mode: 'create', original: '', name: '' })}>取消</button>
            <button className="btn primary" disabled={subjBusy} onClick={submitSubjectForm}>{subjBusy ? '保存中…' : '保存'}</button>
          </>
        )}
      >
        <div className="field">
          <label>科目名称</label>
          <input className="input" aria-label="科目名称" value={subjEditor.name} autoFocus ref={subjNameRef}
            onChange={(e) => setSubjEditor((s) => ({ ...s, name: e.target.value }))}
            placeholder="如：数字电子技术" />
        </div>
      </Modal>
    </Modal>
    {confirmDialog}
    </>
  )
}
