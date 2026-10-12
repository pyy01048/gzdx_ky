import React, { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import useStore from './store/useStore'
import { useTheme, Segmented } from './components/UI'
import { hydrate } from './api/sync'

/* 路由级代码分割：按页面懒加载，减小首屏主包体积 */
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Tasks = lazy(() => import('./pages/Tasks'))
const KbMap = lazy(() => import('./pages/KbMap'))
const Library = lazy(() => import('./pages/Library'))
const Notebook = lazy(() => import('./pages/Notebook'))
const Assistant = lazy(() => import('./pages/Assistant'))
const Pan = lazy(() => import('./pages/Pan'))
const Words = lazy(() => import('./pages/Words'))
const Cards = lazy(() => import('./pages/Cards'))
const Settings = lazy(() => import('./pages/Settings'))
const Quiz = lazy(() => import('./pages/Quiz'))
const QuizBank = lazy(() => import('./pages/QuizBank'))
const Panorama = lazy(() => import('./pages/Panorama'))
const ExamFrequency = lazy(() => import('./pages/ExamFrequency'))
const Analysis = lazy(() => import('./pages/Analysis'))
const LearnerProfile = lazy(() => import('./pages/LearnerProfile'))
const SubjectManager = lazy(() => import('./pages/SubjectManager'))
const Documents = lazy(() => import('./pages/Documents'))
const Planner = lazy(() => import('./pages/Planner'))
const KaoyanGuide = lazy(() => import('./pages/KaoyanGuide'))
const KaoyanSchools = lazy(() => import('./pages/KaoyanSchools'))
const NoticeCenter = lazy(() => import('./pages/NoticeCenter'))
const KaoyanSchoolDetail = lazy(() => import('./pages/KaoyanSchoolDetail'))
const KaoyanCompare = lazy(() => import('./pages/KaoyanCompare'))
const KaoyanAnalysis = lazy(() => import('./pages/KaoyanAnalysis'))
const KaoyanRecommend = lazy(() => import('./pages/KaoyanRecommend'))
const KaoyanImport = lazy(() => import('./pages/KaoyanImport'))
const KaoyanMap = lazy(() => import('./pages/KaoyanMap'))
const KaoyanScatter = lazy(() => import('./pages/KaoyanScatter'))
const KaoyanAssistant = lazy(() => import('./pages/KaoyanAssistant'))
const PlanPage = lazy(() => import('./pages/PlanPage'))
const GrowthPage = lazy(() => import('./pages/GrowthPage'))
const ErrorReview = lazy(() => import('./pages/ErrorReview'))
const QualityDashboard = lazy(() => import('./pages/QualityDashboard'))

function PageFallback() {
  return <div style={{ padding: '48px 16px', textAlign: 'center', color: 'var(--ink-3)', minHeight: '60vh' }}>加载中…</div>
}

// D7: 考研择校模块分组布局（嵌套路由 + 各页面懒加载）
// 择校模块内 Tab 导航（复用 Segmented/.seg，零新增样式）
const KAOYAN_TABS = [
  { value: '/kaoyan/guide', label: '择校中心' },
  { value: '/kaoyan/notices', label: '通知中心' },
  { value: '/kaoyan/schools', label: '院校库' },
  { value: '/kaoyan/compare', label: '院校对比' },
  { value: '/kaoyan/analysis', label: '分数分析' },
  { value: '/kaoyan/recommend', label: '智能择校' },
  { value: '/kaoyan/map', label: '区域热力图' },
  { value: '/kaoyan/import', label: '数据管理' },
]
const KaoyanModuleLayout = () => {
  const location = useLocation()
  const navigate = useNavigate()
  // 当前 tab：schools/:id 归到 schools，guide 是默认
  const currentTab = KAOYAN_TABS.find((t) => location.pathname.startsWith(t.value))?.value || '/kaoyan/guide'
  return (
    <div>
      <Segmented options={KAOYAN_TABS} value={currentTab} onChange={(v) => navigate(v)} />
      <Outlet />
    </div>
  )
}

export default function App() {
  const theme = useStore((s) => s.settings.theme)
  // V7.0 P0-1：主题写入收敛到 useResolvedTheme（内部委托自 useTheme），全应用仅此一处订阅
  useTheme(theme)

  // P0-1：应用挂载时从后端拉取真实数据回填 store（后端优先，本地兜底）
  useEffect(() => {
    hydrate()
  }, [])

  return (
    <ErrorBoundary>
    <Layout>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/kbmap" element={<KbMap />} />
          {/* 评测与数据质量：eval_runs 历史 + 语料体检（数字全部来自库内聚合） */}
          <Route path="/quality" element={<QualityDashboard />} />
          {/* 学习文库：IMA 知识库资料按 初试/复试 + 科目 + 知识/试题/单词 浏览 */}
          <Route path="/library" element={<Library />} />
          <Route path="/quiz" element={<Quiz />} />
          <Route path="/quiz-bank" element={<QuizBank />} />
          {/* 知识点全景刷题：科目→章节→知识点 一屏纵览，点知识点直达刷题 */}
          <Route path="/panorama" element={<Panorama />} />
          {/* 考频分析：知识点/章节/套卷 三维考频排行（对标 exam-strategy） */}
          <Route path="/exam-frequency" element={<ExamFrequency />} />
          <Route path="/subjects" element={<SubjectManager />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/profile" element={<LearnerProfile />} />
          {/* 错题复盘：错因分布 / 薄弱知识点 / 单题 AI 归因与知识点挂接（5+1 的第 5 个模块主页） */}
          <Route path="/error-review" element={<ErrorReview />} />
          {/* 旧入口兼容：/errors 与 /cuoti 早期用过，重定向到新页，避免历史链接失效 */}
          <Route path="/errors" element={<Navigate to="/error-review" replace />} />
          <Route path="/cuoti" element={<Navigate to="/error-review" replace />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/notebook" element={<Notebook />} />
          <Route path="/planner" element={<Planner />} />
          <Route path="/assistant" element={<Assistant />} />
          <Route path="/pan" element={<Pan />} />
          <Route path="/words" element={<Words />} />
          <Route path="/cards" element={<Cards />} />
          <Route path="/settings" element={<Settings />} />
          {/* D7: 考研择校模块分组（嵌套路由 + 懒加载） */}
          <Route path="/kaoyan" element={<KaoyanModuleLayout />}>
            <Route index element={<KaoyanGuide />} />
            <Route path="guide" element={<KaoyanGuide />} />
            {/* 通知中心：已读/未读标记 + 加星置顶（防止错过重要通知） */}
            <Route path="notices" element={<NoticeCenter />} />
            <Route path="schools" element={<KaoyanSchools />} />
            <Route path="schools/:id" element={<KaoyanSchoolDetail />} />
            <Route path="compare" element={<KaoyanCompare />} />
            <Route path="analysis" element={<KaoyanAnalysis />} />
            <Route path="recommend" element={<KaoyanRecommend />} />
            <Route path="import" element={<KaoyanImport />} />
            <Route path="map" element={<KaoyanMap />} />
            <Route path="scatter" element={<KaoyanScatter />} />
            <Route path="assistant" element={<KaoyanAssistant />} />
            <Route path="plan" element={<PlanPage />} />
            <Route path="growth" element={<GrowthPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  </ErrorBoundary>
  )
}
