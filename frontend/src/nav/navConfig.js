/* 全站唯一导航源：顶栏下拉 / 移动端抽屉 / 面包屑 / 相关功能 / Ctrl+K 命令面板 / 设置页界面自定义
   全部从这里派生。新增页面只改这一处。 */
import { Home, Folder, Book, FileText, Target, Map as MapIcon } from '../components/Icon'

export const MODULES = [
  {
    key: 'today', title: '今日', icon: Home, items: [
      /* 中枢是「先做什么」的行动聚合；仪表盘是「整体怎么样」的统计快照。
         两者共用同一批聚合端点，不产生第二套数据源。 */
      { to: '/hub', label: '今日中枢', desc: '跨模块动态聚合 · 先做什么', kw: ['hub', '中枢', '今日', '聚合', 'jinri', 'zhongshu', 'home'] },
      { to: '/', label: '仪表盘总览', exact: true, desc: '今日概览与考研倒计时', kw: ['dashboard', '首页', '主页', 'shouye', 'yibiaopan'] },
      { to: '/tasks', label: '任务打卡', desc: '今日任务与打卡', kw: ['task', '任务', '待办', 'todo', 'renwu', 'daka'] },
      { to: '/planner', label: '学习计划', desc: '规划与连续打卡', kw: ['planner', '计划', '规划', 'jihua', 'plan'] },
      { to: '/profile', label: '学习画像', desc: '学习数据与薄弱点', kw: ['profile', '画像', 'huaxiang'] },
    ],
  },
  {
    key: 'learn', title: '学习', icon: Folder, items: [
      { to: '/library', label: '学习文库', desc: 'IMA 资料 · 初试/复试 · 知识/试题/单词', kw: ['library', '文库', '资料', 'wenku', 'ima'] },
      { to: '/documents', label: '文档知识库', desc: '资料与知识图谱', kw: ['document', '文档', '资料', 'wendang', 'file'] },
      { to: '/textbooks', label: '教材目录', desc: '教材章节目录', public: true, kw: ['textbook', '教材', 'jiaocai', '目录'] },
      { to: '/pan', label: '网盘联动', desc: '云盘与同步', kw: ['pan', '网盘', '云盘', 'wangpan', 'cloud'] },
      { to: '/knowledge', label: '知识图谱', desc: '科目→章节→知识点纵览与掌握度', public: true, kw: ['knowledge', '知识图谱', '知识地图', '考点', 'zhishi', 'map', 'kbmap'] },
    ],
  },
  {
    key: 'practice', title: '练习', icon: Book, items: [
      { to: '/quiz', label: '刷题中心', desc: '题库与错题强化', kw: ['quiz', '刷题', 'shuati', 'test'] },
      { to: '/exam', label: '真题中心', desc: '按年份/卷种做真题与整卷模考', public: true, kw: ['exam', '真题', 'zhenti', '模考', 'paper'] },
      { to: '/cards', label: '记忆卡片', desc: 'Anki 式间隔复习', kw: ['card', '卡片', 'kapian', 'flash'] },
      { to: '/words', label: '单词记忆', desc: '单词背诵与发音', kw: ['word', '单词', 'danci', 'vocab'] },
      { to: '/codebank', label: '复试代码题库', desc: 'LeetCode 式复试上机题库', kw: ['code', '代码', '复试', 'codebank', 'fushi', 'oj'] },
    ],
  },
  {
    key: 'review', title: '复盘', icon: FileText, items: [
      /* dogfood ISSUE-010：原「错题库」（/quiz?tab=review）入口已移除 ——
         与「错题复盘 / 错题本」三个入口高度重叠，且落地页面包屑显示「刷题中心」、
         名称与落点不一致。该能力仍可从「练习 → 刷题中心」的错题强化 tab 进入。 */
      { to: '/error-review', label: '错题复盘', desc: '错因分布 · 薄弱知识点 · AI 归因分析', kw: ['error', 'review', '错题', '复盘', 'cuoti', 'fupan'] },
      { to: '/notebook', label: '错题本', desc: '错题录入 · 间隔复习（拍照 OCR 收录）', kw: ['notebook', '错题本', 'cuoti', 'error'] },
      { to: '/insights', label: '学习统计', desc: '答题量与正确率趋势', kw: ['insight', '统计', 'tongji', 'stats'] },
      { to: '/favorites', label: '我的收藏', desc: '收藏的题目与资料', kw: ['favorite', '收藏', 'shoucang', 'star'] },
      { to: '/timeline', label: '学习轨迹', desc: '按时间回看学习记录', kw: ['timeline', '轨迹', 'guiji', 'history'] },
    ],
  },
  {
    key: 'school', title: '择校', icon: Target, items: [
      /* 2026-10-19 信息架构精简（对标掌上考研/txkyer，见 docs/kaoyan-ia-benchmark.md）：
         13 页 → 3 入口。对比/推荐/热力图/散点图/成长/分数线/AI 问答等保留路由（书签不 404），
         不再占用学生端导航；收集/导入/抓取源属管理工具，后续归入 /admin。 */
      { to: '/kaoyan', label: '院校库', exact: true, desc: '全国院校 · 专业 · 通知', public: true, kw: ['kaoyan', '择校', 'zexiao', '院校', 'yuanxiao', 'schools'] },
      { to: '/kaoyan/notices', label: '通知中心', desc: '简章/复试/报名/初试 · 改考雷达', public: true, kw: ['notice', '通知', '公告', '简章', 'tongzhi', 'gonggao'] },
      { to: '/kaoyan/plan', label: '考研规划', desc: '18 节点关键日程与阶段规划', kw: ['plan', '规划', '日程', '时间节点', 'guihua'] },
    ],
  },
]

export const NAV_OTHER = [
  { to: '/glass', label: '毛玻璃实验室', desc: '液态玻璃动效交互演示', public: true, kw: ['glass', '玻璃', '毛玻璃', '动效', 'design', 'boli'] },
  { to: '/assistant', label: 'AI 助手', desc: '问答与 RAG 检索', kw: ['assistant', 'ai', '助手', '问答', 'zhushou', 'chat'] },
  { to: '/settings', label: '设置', desc: '偏好、管理入口与数据管理', kw: ['setting', '设置', '偏好', '管理', 'shezhi', 'config'] },
]

/* 管理端页面：只在 /admin 命名空间（左侧栏）出现，学生端导航与命令面板不可见。
   legacy 是改版前的路径，App 据此生成重定向，旧书签不 404。 */
export const ADMIN_ROOT = '/admin'
export const NAV_ADMIN = [
  { to: '/admin/overview', legacy: '/data-center', label: '数据中心', desc: '数据域计数与接口体检', kw: ['data', '数据中心', '接口', 'shuju'] },
  /* 用户管理：账号 · 角色 · 禁用 · 重置密码。此前只存在于设置页「账号与安全」
     分区内且 ?tab= 深链接不生效，管理员找不到入口——纳入管理后台导航。 */
  { to: '/admin/users', legacy: '/users', label: '用户管理', desc: '账号 · 角色 · 重置密码', kw: ['user', '用户', '账号', 'yonghu', 'users'] },
  { to: '/admin/subjects', legacy: '/subjects', label: '科目管理', desc: '科目 · 章节 · 题型', kw: ['subject', '科目', 'kemu'] },
  { to: '/admin/quiz-bank', legacy: '/quiz-bank', label: '题库管理', desc: '真题地图 · 章节刷题', kw: ['bank', '题库', 'tiku'] },
  { to: '/admin/quality', legacy: '/quality', label: '数据质量', desc: '识别口径与语料体检', kw: ['quality', '评测', '质量', 'zhiliang', 'eval'] },
  { to: '/admin/schools', legacy: '/kaoyan/import', label: '院校数据管理', desc: '定向采集 · 国家线回填 · 公告采集', kw: ['import', '导入', '院校数据', 'daoru', 'notice', '公告'] },
  { to: '/admin/crawl-sources', legacy: '/crawl-sources', label: '院校采集源', desc: '选择参与采集的院校 · 数据源目录', kw: ['crawl', '采集', '爬取', 'caiji', 'paqu'] },
  { to: '/admin/kb-import', legacy: '/kb-import', label: '知识库导入', desc: '按类型导入知识图谱与题库', kw: ['import', '导入', '知识库', 'daoru'] },
  { to: '/admin/model', legacy: '/model-training', label: '模型训练', desc: '答疑模型 LoRA 训练', kw: ['train', 'lora', '模型', '训练', 'xunlian'] },
].map((e) => ({ ...e, roles: ['admin'] }))

export const ADMIN_LEGACY_REDIRECTS = NAV_ADMIN.map((e) => [e.legacy, e.to])

export const NAV_MODULES = MODULES

export const MOBILE_TABS = [
  { to: '/', label: '今日', icon: Home },
  { to: '/knowledge', label: '知识', icon: MapIcon },
  { to: '/quiz', label: '刷题', icon: Book },
  { to: '/error-review', label: '复盘', icon: FileText },
]

/* 命令面板与面包屑用的扁平清单（分组顺序 = 顶栏顺序，其后通用入口、管理页） */
export const ALL_ENTRIES = [
  ...MODULES.flatMap((m) => m.items.map((it) => ({ ...it, group: m.title }))),
  ...NAV_OTHER.map((it) => ({ ...it, group: '通用' })),
  ...NAV_ADMIN.map((it) => ({ ...it, group: '管理' })),
]

export const isAdminPath = (to) => to === ADMIN_ROOT || to.startsWith(`${ADMIN_ROOT}/`)
export const entriesFor = (isAdmin) => (isAdmin ? ALL_ENTRIES : ALL_ENTRIES.filter((e) => !isAdminPath(e.to)))

const CRUMB_BY_PATH = new Map(ALL_ENTRIES.filter((e) => !e.to.includes('?')).map((e) => [e.to, e.label]))
CRUMB_BY_PATH.set(ADMIN_ROOT, '管理后台')
/* 择校子页面不在顶栏导航里，补上面包屑名称，避免一律回落到「页面」 */
CRUMB_BY_PATH.set('/kaoyan/schools', '院校库')
CRUMB_BY_PATH.set('/kaoyan/compare', '院校对比')
CRUMB_BY_PATH.set('/kaoyan/analysis', '分数分析')
CRUMB_BY_PATH.set('/kaoyan/map', '区域择校热力图')
CRUMB_BY_PATH.set('/kaoyan/scatter', '招生人数分布')
CRUMB_BY_PATH.set('/kaoyan/recommend', '智能择校推荐')
CRUMB_BY_PATH.set('/kaoyan/growth', '成长体系')
CRUMB_BY_PATH.set('/kaoyan/assistant', '择校 AI 助手')
/* 面包屑父级：管理端页面挂在「管理后台」下 */
export function crumbParent(path) {
  return path !== ADMIN_ROOT && isAdminPath(path) ? { to: ADMIN_ROOT, label: '管理后台' } : null
}
const CRUMB_PREFIX = [
  ['/kaoyan/schools/', '院校详情'],
  ['/knowledge/', '知识点详情'],
  ['/exam/', '真题中心'],
  ['/kaoyan/guide', '择校数据中心'],
]

export function crumbName(path) {
  const hit = CRUMB_BY_PATH.get(path)
  if (hit) return hit
  const pre = CRUMB_PREFIX.find(([p]) => path.startsWith(p))
  return pre ? pre[1] : '页面'
}

export const RELATED = {
  '/tasks': ['/knowledge', '/planner', '/error-review'],
  '/knowledge': ['/documents', '/quiz', '/error-review'],
  '/library': ['/documents', '/knowledge', '/quiz'],
  '/quiz': ['/error-review', '/knowledge', '/cards'],
  '/admin/quiz-bank': ['/quiz', '/knowledge', '/error-review'],
  '/error-review': ['/notebook', '/quiz', '/knowledge'],
  '/notebook': ['/quiz', '/knowledge', '/error-review'],
  '/insights': ['/quiz', '/error-review', '/notebook'],
  '/documents': ['/knowledge', '/pan', '/assistant'],
  '/pan': ['/documents', '/assistant', '/settings'],
  '/planner': ['/tasks', '/knowledge', '/error-review'],
  '/settings': ['/pan', '/documents', '/assistant'],
  '/admin/overview': ['/documents', '/quiz', '/error-review'],
  '/admin/crawl-sources': ['/admin/schools', '/kaoyan/schools', '/admin/overview'],
  '/admin/subjects': ['/admin/quiz-bank', '/knowledge', '/settings'],
}

/* 择校模块内 Tab：与顶栏「择校」下拉同源 */
export const KAOYAN_TABS = MODULES.find((m) => m.key === 'school').items.map((it) => ({ value: it.to, label: it.label }))

/* 按设置页「界面自定义」的偏好过滤/排序顶栏分组与「其他」入口 */
export function visibleModules(layout) {
  const hidden = new Set(layout?.navHidden || [])
  const order = layout?.navOrder || []
  const idx = new Map(order.map((k, i) => [k, i]))
  const rank = (m) => (idx.has(m.key) ? idx.get(m.key) : order.length + MODULES.indexOf(m))
  return MODULES.filter((m) => !hidden.has(m.key)).sort((a, b) => rank(a) - rank(b))
}

export function visibleOther(layout) {
  const hidden = new Set(layout?.otherHidden || [])
  return NAV_OTHER.filter((n) => !hidden.has(n.to))
}

/* 访客模式（2026-10-19）：只保留标了 public 的条目，分组内无公开项则整组隐藏。
   登录用户不受影响（isGuest=false 原样返回）。 */
export function visibleModulesFor(modules, isGuest) {
  if (!isGuest) return modules
  return modules
    .map((m) => ({ ...m, items: m.items.filter((it) => it.public) }))
    .filter((m) => m.items.length > 0)
}
