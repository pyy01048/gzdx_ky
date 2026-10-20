import React, { useState, useRef } from 'react'
import { toastErr, focusAndScroll } from './UI'

/**
 * 快速添加任务组件（参考滴答清单/Todoist）
 * 支持自然语言输入："明天背单词 30min #英语"
 */
export default function QuickAddTask({ onAdd, subjects = [] }) {
  const [input, setInput] = useState('')
  const [selectedSubject, setSelectedSubject] = useState(subjects[0] || '')
  const [duration, setDuration] = useState(25)
  const inputRef = useRef(null)

  const handleSubmit = (e) => {
    e.preventDefault()
    const title = input.trim()
    if (!title) {
      // 旧实现直接 return，用户按回车以为已添加；现在明确提示并把焦点送回输入框
      toastErr('请输入任务标题')
      focusAndScroll(inputRef.current)
      return
    }

    onAdd({
      title,
      subject: selectedSubject,
      duration: Number(duration),
      completed: false,
      subtasks: [],
      createdAt: new Date().toISOString(),
    })

    setInput('')
    // 保持焦点，方便连续添加
    inputRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    // Esc 清空并失焦
    if (e.key === 'Escape') {
      setInput('')
      e.target.blur()
    }
  }

  return (
    <form className="quick-add-form" onSubmit={handleSubmit}>
      <div className="qa-row">
        <input
          ref={inputRef}
          className="input qa-input"
          type="text"
          placeholder="快速添加任务...（例：背单词 30分钟）"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          aria-label="任务标题"
        />

        {subjects.length > 0 && (
          <select
            className="input qa-subject"
            value={selectedSubject}
            onChange={(e) => setSelectedSubject(e.target.value)}
            aria-label="选择科目"
          >
            {subjects.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        )}

        <select
          className="input qa-duration"
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
          aria-label="预计时长"
        >
          <option value={15}>15分钟</option>
          <option value={25}>25分钟</option>
          <option value={45}>45分钟</option>
          <option value={60}>60分钟</option>
          <option value={90}>90分钟</option>
          <option value={120}>120分钟</option>
        </select>

        <button
          type="submit"
          className="btn primary qa-btn"
          disabled={!input.trim()}
          aria-label="添加任务"
        >
          添加
        </button>
      </div>

      <div className="qa-hint">
        提示：输入后选择科目和时长，按 Enter 或点击"添加"即可快速创建任务
      </div>
    </form>
  )
}
