import React, { Component, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

/* ============================================================================
   MdViewer · Markdown 渲染组件（C-MDVIEWER@1）
   · react-markdown + remark-math + rehype-katex：标题/表格/公式/代码块
   · XSS：react-markdown 默认不渲染原始 HTML（未引入 rehype-raw），等价于转义
   · source 为空 → 渲染空 div；解析抛错 → ErrorBoundary 回落 <pre> 保留原文
   ========================================================================== */

class MdViewerBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      const { source, className } = this.props
      return (
        <pre className={`v3-mdviewer__fallback${className ? ` ${className}` : ''}`}>
          {source}
        </pre>
      )
    }
    return this.props.children
  }
}

export default function MdViewer({ source, className = '' }) {
  const content = useMemo(() => {
    if (source == null || source === '') return ''
    return String(source)
  }, [source])

  if (!content) return <div className={`v3-mdviewer${className ? ` ${className}` : ''}`} />

  return (
    <MdViewerBoundary source={content} className={className}>
      <div className={`v3-mdviewer${className ? ` ${className}` : ''}`}>
        <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
          {content}
        </ReactMarkdown>
      </div>
    </MdViewerBoundary>
  )
}
