/**
 * 通用表单组件
 * 支持输入框、文本域、下拉选择、复选框、单选框
 */
import React, { useState } from 'react'

/**
 * Form 表单
 * @param {Object} props
 * @param {Array} props.fields - 字段配置
 * @param {Object} props.initialValues - 初始值
 * @param {Function} props.onSubmit - 提交回调
 * @param {Function} props.onChange - 值变化回调
 * @param {string} props.submitText - 提交按钮文字
 * @param {string} props.layout - 布局 horizontal/vertical
 */
export default function Form({
  fields = [],
  initialValues = {},
  onSubmit = () => {},
  onChange = null,
  submitText = '提交',
  layout = 'vertical',
}) {
  const [values, setValues] = useState(initialValues)
  const [errors, setErrors] = useState({})

  const handleChange = (name, value) => {
    const newValues = { ...values, [name]: value }
    setValues(newValues)
    if (onChange) onChange(newValues)
    // 清除该字段错误
    if (errors[name]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[name]
        return next
      })
    }
  }

  const validate = () => {
    const newErrors = {}
    fields.forEach((field) => {
      if (field.required && !values[field.name]) {
        newErrors[field.name] = field.requiredMessage || `${field.label}不能为空`
      }
      if (field.validate && typeof field.validate === 'function') {
        const err = field.validate(values[field.name], values)
        if (err) newErrors[field.name] = err
      }
    })
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (validate()) {
      onSubmit(values)
    }
  }

  const renderField = (field) => {
    const value = values[field.name] ?? ''
    const error = errors[field.name]
    const baseClass = `form-field ${layout === 'horizontal' ? 'form-field-horizontal' : ''}`
    const inputClass = `form-input ${error ? 'form-input-error' : ''}`

    switch (field.type) {
      case 'textarea':
        return (
          <textarea
            className={inputClass}
            value={value}
            onChange={(e) => handleChange(field.name, e.target.value)}
            placeholder={field.placeholder}
            rows={field.rows || 4}
          />
        )
      case 'select':
        return (
          <select
            className={inputClass}
            value={value}
            onChange={(e) => handleChange(field.name, e.target.value)}
          >
            {field.placeholder && <option value="">{field.placeholder}</option>}
            {(field.options || []).map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        )
      case 'checkbox':
        return (
          <label className="form-checkbox">
            <input
              type="checkbox"
              checked={!!value}
              onChange={(e) => handleChange(field.name, e.target.checked)}
            />
            <span>{field.checkboxLabel || field.label}</span>
          </label>
        )
      case 'radio':
        return (
          <div className="form-radio-group">
            {(field.options || []).map((opt) => (
              <label key={opt.value} className="form-radio">
                <input
                  type="radio"
                  name={field.name}
                  value={opt.value}
                  checked={value === opt.value}
                  onChange={(e) => handleChange(field.name, e.target.value)}
                />
                <span>{opt.label}</span>
              </label>
            ))}
          </div>
        )
      case 'number':
        return (
          <input
            type="number"
            className={inputClass}
            value={value}
            onChange={(e) => handleChange(field.name, e.target.value ? Number(e.target.value) : '')}
            placeholder={field.placeholder}
            min={field.min}
            max={field.max}
            step={field.step}
          />
        )
      case 'date':
        return (
          <input
            type="date"
            className={inputClass}
            value={value}
            onChange={(e) => handleChange(field.name, e.target.value)}
          />
        )
      default:
        return (
          <input
            type="text"
            className={inputClass}
            value={value}
            onChange={(e) => handleChange(field.name, e.target.value)}
            placeholder={field.placeholder}
          />
        )
    }
  }

  return (
    <form className={`form form-${layout}`} onSubmit={handleSubmit}>
      {fields.map((field) => (
        <div key={field.name} className={`form-field ${layout === 'horizontal' ? 'form-field-horizontal' : ''}`}>
          {field.type !== 'checkbox' && (
            <label className="form-label">
              {field.required && <span className="form-required">*</span>}
              {field.label}
            </label>
          )}
          <div className="form-control">
            {renderField(field)}
            {errors[field.name] && <div className="form-error">{errors[field.name]}</div>}
            {field.help && <div className="form-help">{field.help}</div>}
          </div>
        </div>
      ))}
      <div className="form-actions">
        <button type="submit" className="btn btn-primary">{submitText}</button>
      </div>
    </form>
  )
}
