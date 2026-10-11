/**
 * 全局错误边界组件 V3.0
 * 捕获子组件的渲染错误，显示友好的错误页面，防止整个应用白屏
 *
 * 使用方式：
 * <ErrorBoundary>
 *   <App />
 * </ErrorBoundary>
 */
import React from 'react'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] 组件渲染错误:', error, errorInfo)
    this.setState({ errorInfo })
  }

  handleReload = () => {
    window.location.reload()
  }

  handleCopyError = () => {
    const errorText = `错误信息: ${this.state.error?.message}\n组件栈: ${this.state.errorInfo?.componentStack}`
    navigator.clipboard?.writeText(errorText).then(() => {
      alert('错误信息已复制到剪贴板')
    }).catch(() => {
      // 降级方案
      const textarea = document.createElement('textarea')
      textarea.value = errorText
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      alert('错误信息已复制到剪贴板')
    })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-content">
            <div className="error-boundary-icon">⚠️</div>
            <h2 className="error-boundary-title">页面出了点问题</h2>
            <p className="error-boundary-desc">
              很抱歉，页面在渲染时遇到了错误。您可以尝试刷新页面，或者复制错误信息反馈给开发者。
            </p>
            {this.state.error && (
              <div className="error-boundary-detail">
                <strong>错误信息：</strong>
                <code>{this.state.error.message}</code>
              </div>
            )}
            <div className="error-boundary-actions">
              <button className="btn primary" onClick={this.handleReload}>
                刷新页面
              </button>
              <button className="btn" onClick={this.handleCopyError}>
                复制错误信息
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
