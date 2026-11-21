// ESLint flat config（完善方案 07 §3.1）
// 策略：存量 57 个页面先以 warn 收敛，error 级问题当场清零；新代码 0 error 门禁。
import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import prettier from 'eslint-config-prettier'

export default [
  {
    ignores: [
      'dist',
      '../backend-main-fastapi/static',
      'node_modules',
      'e2e',
      'playwright.config.js',
      'vite.config.js',
    ],
  },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { react, 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...js.configs.recommended.rules,
      // 渐进 TS 替代 prop-types；JSX 新运行时无需 React 导入
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      'react/jsx-uses-react': 'off',
      'react/jsx-uses-vars': 'error',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // 存量：未用变量先告警（不阻断），下划线前缀豁免
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'react-refresh/only-export-components': 'warn',
      // 存量兜底：空块/常量条件等常见噪音降级为 warn
      'no-empty': ['warn', { allowEmptyCatch: true }],
      'no-constant-condition': 'warn',
      'no-useless-escape': 'warn',
      // 中文注释里需要保留全角空格（题干示例），只对代码/字符串生效
      'no-irregular-whitespace': ['error', { skipComments: true }],
    },
    settings: { react: { version: 'detect' } },
  },
  prettier,
]
