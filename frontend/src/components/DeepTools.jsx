import React, { useState } from 'react'
import { toast } from './UI'
import { outlineFromNotes } from '../utils/words'

/* ============================================================
   DeepStudent 风格·考研智能工具面板
   作文批改 / 翻译 / 错题讲解 / 知识导图 / 一键转卡片 / 知识库问答
   所有工具把处理后的 prompt 交给 send() 走统一引擎（Agent / API / 本地）
   ============================================================ */

const SUBJECT_NAME = { math: '数学', english: '英语', politics: '政治', major: '专业课', other: '其他' }

export default function DeepTools({ send, notebook, pan, words, cards, packs, addCard }) {
  const [tab, setTab] = useState('essay')
  const [essay, setEssay] = useState('')
  const [translate, setTranslate] = useState({ text: '', dir: 'en2zh' })
  const [selectedNote, setSelectedNote] = useState(null)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [docQuestion, setDocQuestion] = useState('')
  const [subjectFilter, setSubjectFilter] = useState('all')

  const call = (prompt) => {
    if (!prompt.trim()) return toast('请先填写内容')
    send(prompt)
  }

  /* 作文批改 */
  const submitEssay = () => {
    if (essay.trim().length < 10) return toast('作文内容太短，无法批改')
    call(
      `请以考研英语阅卷标准批改下面这篇作文，输出：\n1. 总分（按大小作文满分计分并给出档位）\n2. 分项点评：内容要点 / 语言准确性 / 篇章结构 / 词汇语法多样性\n3. 逐句挑出语法或表达问题并给出修改建议\n4. 3-5 句可替换的高级表达\n\n【作文】\n${essay}`
    )
  }

  /* 翻译 */
  const submitTranslate = () => {
    if (!translate.text.trim()) return toast('请输入要翻译的内容')
    const dirText = translate.dir === 'en2zh' ? '英译中' : '中译英'
    call(
      `请将下面的${dirText === '英译中' ? '英文' : '中文'}翻译成${dirText === '英译中' ? '中文' : '英文'}，要求：\n1. 直译 + 意译各给出一个版本\n2. 如果是考研英语长难句，请拆解句子主干、从句结构\n3. 标出其中的核心词汇与固定搭配\n\n【待翻译】\n${translate.text}`
    )
  }

  /* 错题讲解 */
  const submitNoteExplain = () => {
    if (!selectedNote) return toast('请选择一条错题')
    const n = selectedNote
    call(
      `请讲解这道错题：\n【科目】${SUBJECT_NAME[n.subject] || n.subject}\n【题目】${n.question}\n【正确答案】${n.answer}\n【错误原因】${n.reason || '未知'}\n【解析参考】${n.analysis || '无'}\n\n要求：\n1. 用一句话说清这题考什么知识点\n2. 给出完整解题思路（分步骤）\n3. 指出我错在哪、如何避免同类错误\n4. 出一道同类变式题并给答案`
    )
  }

  /* 知识导图 */
  const submitOutline = () => {
    const notes = subjectFilter === 'all' ? notebook : notebook.filter((n) => n.subject === subjectFilter)
    if (!notes.length) return toast('当前科目暂无错题，无法生成导图')
    const outline = outlineFromNotes(notes)
    call(
      `请基于我的错题数据，生成一份考研复习知识导图（Markdown 树状结构，用缩进层级表示）：\n\n【错题分布】\n${outline.map((o) => `${o.subject}（${o.count}题）：\n${o.items.map((it) => `- ${it.q}${it.tag ? '（' + it.tag + '）' : ''}`).join('\n')}`).join('\n\n')}\n\n要求：\n1. 按科目组织成「科目 → 章节/考点 → 具体知识点」层级\n2. 标注高频考点与我的薄弱点\n3. 附一段复习优先级建议`
    )
  }

  /* 一键转卡片 */
  const toCard = (n) => {
    const pack = packs[0]
    if (!pack) return toast('请先创建卡包')
    addCard({ front: n.question, back: n.answer, hint: n.analysis || n.reason || '', subject: n.subject, packId: pack.id })
    toast('已生成记忆卡片，可在「记忆卡片」页复习')
  }

  /* 知识库问答 */
  const submitDocQ = () => {
    if (!selectedDoc) return toast('请先选择网盘中的复习资料')
    if (!docQuestion.trim()) return toast('请输入要基于该资料回答的问题')
    call(
      `请严格基于以下复习资料回答问题「${docQuestion}」。\n\n【资料名称】${selectedDoc.name}\n【资料简介】${selectedDoc.desc || '无'}\n\n要求：\n1. 仅依据资料内容作答，不得编造\n2. 回答末尾标注信息来源「${selectedDoc.name}」\n3. 若资料中没有相关信息，请如实说明，并建议我补充什么资料`
    )
  }

  const tabs = [
    ['essay', '作文批改'],
    ['translate', '翻译'],
    ['explain', '错题讲解'],
    ['outline', '知识导图'],
    ['kb', '知识库问答'],
    ['cards', '一键转卡']
  ]

  return (
    <div className="deep-panel">
      <div className="deep-head">
        <b>DeepStudent 智能学习工具</b>
        <span>作文批改 · 翻译 · 错题讲解 · 知识导图 · 知识库问答 · 一键转卡</span>
      </div>
      <div className="seg" style={{ flexWrap: 'wrap' }}>
        {tabs.map(([k, label]) => (
          <button key={k} className={`seg-btn ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      <div className="deep-body">
        {tab === 'essay' && (
          <div>
            <textarea
              className="input" rows={6}
              placeholder="粘贴你的英语作文，我会按考研阅卷标准批改、打分并给出替换表达…"
              value={essay} onChange={(e) => setEssay(e.target.value)}
            />
            <div className="row" style={{ gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
              <button className="btn primary" onClick={submitEssay}>开始批改</button>
            </div>
            <p className="deep-hint">仿 DeepStudent：考研场景深度适配，输出评分档位、逐句问题与高级表达替换。</p>
          </div>
        )}

        {tab === 'translate' && (
          <div>
            <div className="seg" style={{ marginBottom: 8 }}>
              {[['en2zh', '英译中'], ['zh2en', '中译英']].map(([k, l]) => (
                <button key={k} className={`seg-btn ${translate.dir === k ? 'on' : ''}`} onClick={() => setTranslate({ ...translate, dir: k })}>{l}</button>
              ))}
            </div>
            <textarea
              className="input" rows={6}
              placeholder={translate.dir === 'en2zh' ? '粘贴英文长难句 / 段落…' : '粘贴中文，翻译为英文…'}
              value={translate.text} onChange={(e) => setTranslate({ ...translate, text: e.target.value })}
            />
            <div className="row" style={{ gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
              <button className="btn primary" onClick={submitTranslate}>翻译 + 拆解</button>
            </div>
            <p className="deep-hint">长难句自动拆主干、标从句，直译意译双版本。</p>
          </div>
        )}

        {tab === 'explain' && (
          <div>
            <p className="deep-hint" style={{ marginBottom: 6 }}>选择一条错题，AI 讲解知识点、解题思路、错因与变式题：</p>
            <div className="note-select-list" style={{ maxHeight: 220, overflowY: 'auto' }}>
              {notebook.length === 0 && <p style={{ fontSize: 13, color: 'var(--ink-3)' }}>错题本为空，先去「错题本」收录错题吧。</p>}
              {notebook.map((n) => (
                <button key={n.id} className={`ns-item ${selectedNote?.id === n.id ? 'on' : ''}`} onClick={() => setSelectedNote(n)}>
                  <b>{n.question}</b>
                  <span>{SUBJECT_NAME[n.subject] || n.subject}</span>
                </button>
              ))}
            </div>
            {selectedNote && (
              <div className="row" style={{ gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
                <button className="btn primary" onClick={submitNoteExplain}>开始讲解</button>
              </div>
            )}
          </div>
        )}

        {tab === 'outline' && (
          <div>
            <p className="deep-hint" style={{ marginBottom: 8 }}>基于错题数据生成知识导图（按科目 → 考点 → 薄弱点层级）：</p>
            <div className="seg" style={{ marginBottom: 8 }}>
              <button className={`seg-btn ${subjectFilter === 'all' ? 'on' : ''}`} onClick={() => setSubjectFilter('all')}>全部科目</button>
              {Object.entries(SUBJECT_NAME).map(([k, l]) => (
                <button key={k} className={`seg-btn ${subjectFilter === k ? 'on' : ''}`} onClick={() => setSubjectFilter(k)}>{l}</button>
              ))}
            </div>
            <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn primary" onClick={submitOutline}>生成知识导图</button>
            </div>
          </div>
        )}

        {tab === 'kb' && (
          <div>
            <p className="deep-hint" style={{ marginBottom: 6 }}>仿 NotebookLM：基于网盘自有复习资料精准问答，回答带资料来源。</p>
            <div className="note-select-list" style={{ maxHeight: 180, overflowY: 'auto', marginBottom: 8 }}>
              {pan.length === 0 && <p style={{ fontSize: 13, color: 'var(--ink-3)' }}>网盘暂无资料，先去「网盘联动」添加。</p>}
              {pan.map((p) => (
                <button key={p.id} className={`ns-item ${selectedDoc?.id === p.id ? 'on' : ''}`} onClick={() => setSelectedDoc(p)}>
                  <b>{p.name}</b>
                  <span>{p.cat}</span>
                </button>
              ))}
            </div>
            <textarea
              className="input" rows={2}
              placeholder={`基于「${selectedDoc ? selectedDoc.name : '选中资料'}」提问…（如：总结这套真题的重点题型）`}
              value={docQuestion} onChange={(e) => setDocQuestion(e.target.value)}
            />
            <div className="row" style={{ gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
              <button className="btn primary" onClick={submitDocQ}>基于资料回答</button>
            </div>
          </div>
        )}

        {tab === 'cards' && (
          <div>
            <p className="deep-hint" style={{ marginBottom: 6 }}>把错题一键转成 SM-2 记忆卡片（归入第一个卡包），在「记忆卡片」页按遗忘曲线复习。当前已有 {words.length} 词、{cards.length} 卡：</p>
            <div className="note-select-list" style={{ maxHeight: 220, overflowY: 'auto' }}>
              {notebook.map((n) => (
                <button key={n.id} className="ns-item" onClick={() => toCard(n)}>
                  <b>{n.question}</b>
                  <span className="ns-act">转卡片 →</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
