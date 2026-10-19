/* =====================================================================
 * 刷题中心 · 共享纯函数与本地存储工具（自 Quiz.jsx 原样拆出）
 * 只做结构拆分：以下函数/常量与原 Quiz.jsx 模块级定义完全一致，
 * 供 Quiz.jsx（容器）/ QuizHome / QuizYear / QuizReview /
 * QuizPractice / QuizResult 共同引用，避免循环依赖。
 * ===================================================================== */

/* 题型枚举：single 单选 / judge 判断 / fill 填空 / essay 简答 /
   calc 计算 / draw 作图 / multiple 多选（后端暂未返回，前端兼容）。 */
const TYPE_LABELS = {
  single: '单选', judge: '判断', fill: '填空',
  essay: '简答', calc: '计算', draw: '作图', multiple: '多选'
}
const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F']
const letterOf = (i) => LETTERS[i] || String(i + 1)

/* 来源大类（M0 刷题中心）：真题 / 教材题 **分页隔离** 的唯一依据。
   与后端 GET /api/quiz/questions?source_kind= 一一对应：
     exam     = source 以「真题:」开头（历年真题原卷）
     textbook = source 以「知识库:」开头（教材/讲义抽取题）
     all      = 不限制（用户显式选择「全部」时才混合展示）
   默认使用 'exam'，保证「真题与教材题不混在一个列表里」。 */
export const SOURCE_KINDS = [
  { id: 'exam', label: '历年真题' },
  { id: 'textbook', label: '教材题' },
  { id: 'all', label: '全部来源' },
]
const SOURCE_KIND_LABEL = Object.fromEntries(SOURCE_KINDS.map((s) => [s.id, s.label]))

/* 本地错题 id 集合（与旧版 quiz_wrong 兼容；后端错题以 /api/errors 为准）
   P4：实际读写 `quiz_wrong:{uid}`，旧全局键首读时一次性迁给当前用户并删旧键。 */
import { ukey, readMigrated } from '../utils/userKeys'
const WRONG_KEY = 'quiz_wrong'
function loadWrong() { return readMigrated(WRONG_KEY, []) }
function addWrong(id) {
  if (id == null) return
  const arr = loadWrong()
  if (!arr.map(String).includes(String(id))) {
    arr.push(String(id))
    try { localStorage.setItem(ukey(WRONG_KEY), JSON.stringify(arr)) } catch { /* 隐私模式 */ }
  }
}

/* 题目收藏 —— 已统一到后端 favorites 表（S7）。
 *
 * 历史遗留：这里曾是纯 localStorage 实现（quiz_favorites_v9），
 * 与「我的收藏」页的后端数据互不相通 —— 刷题页收藏的题在收藏页看不到。
 * 现在转发到 api/quizFavSync.js：localStorage 退化为**同步读缓存**，
 * 真相源是后端；模块加载时 hydrateFavs() 会把历史收藏补推上去。
 *
 * 签名（loadFavs 返回 map / saveFavs 写入）保持不变，4 个消费组件零改动。 */
import { loadFavs, saveFavs } from '../api/quizFavSync'
import { normalizeOptions, optionText, imageList } from '../utils/optionText'

/* V10 本地作答记录（单机口径）：{ [qid]: { times: n, correct: bool } }。
   替代标杆的「全站做过人数」，题号格颜色与做过次数均读这里。 */
const REC_KEY = 'quiz_records_v10'
function loadRecs() { return readMigrated(REC_KEY, {}) }
function pushRec(qid, correct) {
  try {
    const m = loadRecs()
    const prev = m[String(qid)] || { times: 0, correct: false }
    m[String(qid)] = { times: prev.times + 1, correct: !!correct }
    localStorage.setItem(ukey(REC_KEY), JSON.stringify(m))
  } catch { /* 隐私模式 */ }
}

function safeParseOptions(raw) {
  if (Array.isArray(raw)) return raw
  if (!raw) return []
  try { const v = JSON.parse(raw); return Array.isArray(v) ? v : [] } catch { return [] }
}

/* 剥掉选项自带的序号前缀。库内 options 元素普遍自带「A．」「A、」「A.」
   等前缀，若与 UI 的字母徽标同时渲染会出现「A  A．奇偶校验码」的重复文字。
   剥完为空时回退为原值，保证不丢内容。支持 A-H / a-h。 */
const OPT_LABEL_RE = /^\s*[（(]?\s*([A-Ha-h])\s*[）).、．:：]\s*/
export function stripOptLabel(opt) {
  const s = optionText(opt)
  const m = s.match(OPT_LABEL_RE)
  if (!m) return s.trim()
  const rest = s.slice(m[0].length).trim()
  return rest || s.trim()
}

/* 从答案串中抽出正确选项的下标集合。兼容 'B' / 'B．' / '答案B' /
   'ABC'（多选）/ 'B、C' 等写法。返回 null 表示答案无法解析为字母。 */
export function answerIndexes(answer) {
  const s = String(answer == null ? '' : answer).toUpperCase()
  const m = s.match(/[A-H]/g)
  if (!m || !m.length) return null
  return new Set(m)
}

/** 判断第 optIndex 个选项（对应字母 letterOf(optIndex)）是否正确。 */
export function isCorrectOption(optIndex, answer) {
  const set = answerIndexes(answer)
  if (!set) return false
  return set.has(letterOf(optIndex))
}

/* 纯文本题（需要用户输入作答）：填空/简答/计算/作图。
   选择题的 answer 往往是孤立字母，不走输入自评流程——那条路径会让用户
   面对「答案是 D 却无选项」的题目输入文字并被判错，详见 isChoiceLike。 */
const TEXT_TYPES = ['fill', 'essay', 'calc', 'draw']
export function isTextQuestion(q) {
  if (TEXT_TYPES.includes(q?.question_type)) return true
  if (q?.question_type === 'multiple' || q?.question_type === 'single' || q?.question_type === 'judge') return false
  return !answerIndexes(q?.answer)   // 答案为纯字母 → 选择题
}
/** 选择题语义（含「options 为空但答案是字母」的残缺选择题）。 */
export function isChoiceLike(q) { return !isTextQuestion(q) }

/* 是否"真的有可渲染的选项"——**先归一化再判断**，而不是只看数组长度。

   为什么不能只判 length：后端 canonical 形态是对象数组
   `[{key,text}]`（对齐 services/content_sanitizer 的 DB is_canonical_options），
   旧数据是字符串数组 `["A. xxx"]`，还存在「非空数组但元素全为空」的脏题。
   只看 length 会让对象数组判真、全空数组也判真，
   渲染时若再走 String(opt) 就直接变成 "[object Object]"（P0-4）。

   归一化（normalizeOptions）幂等且两种形态通吃，所以这里先归一再看长度，
   isChoiceQ / isChoiceWithoutOptions 共用同一口径，杜绝两处判断打架。 */
function hasRealOptions(q) {
  return normalizeOptions(safeParseOptions(q?.options)).length > 0
}
/** 选择题但选项缺失：只读展示，禁止作答。 */
export function isChoiceWithoutOptions(q) {
  return isChoiceLike(q) && !hasRealOptions(q)
}
/* 题面或答案依赖原书插图。 */
const FIG_RE = /如图|见图|下图|上图|图\s*\d+[-－]?\d*|所示图|图中/
export function dependsOnFigure(q) {
  return FIG_RE.test(String(q?.content || '')) || FIG_RE.test(String(q?.answer || ''))
}

/* 归一化后端题目。
   注意 options 过滤：库内存在大量「options 非空数组但元素全为空/None」的题
   （实测可见可作答 3388 题中 2842 题如此）。若不过滤，isChoiceQ 会判真 →
   渲染出一排**空白选项按钮**，用户点了也没内容（本次要修的核心问题之一）。 */
function normQ(q) {
  const opts = normalizeOptions(safeParseOptions(q.options))
  return {
    id: String(q.id),
    content: q.content || '',
    options: opts,
    images: imageList(q.images),
    answer: q.answer ?? '',
    analysis: q.analysis || '',
    subject: q.subject || '',
    chapter: q.chapter || '',
    knowledge_point: q.knowledge_point || '',
    difficulty: q.difficulty || 1,
    source: q.source || '',
    question_type: q.question_type || '',
    answer_type: q.answer_type || '',
    quality: q.quality || '',
    is_available: q.is_available ?? null,
    year: q.year ?? null,
    paper: q.paper ?? null,
    question_no: q.question_no ?? null
  }
}
const isChoiceQ = (q) => hasRealOptions(q)
const isMultiQ = (q) => q.question_type === 'multiple'

/* 题目「可用性标记」——决定是否可作答，以及给用户什么提示（不渲染空白按钮）。
 * available：正常可作答（有选项或有答案）；
 * memorize ：仅有参考答案但无选项（answer_type=subjective）→ 仅记忆参考，不可作答；
 * locked   ：空题假题（quality=incomplete 或 is_available=false）→ 不可作答。 */
export function questionMark(q) {
  if (q?.is_available === false || q?.quality === 'incomplete') {
    return { id: 'locked', label: '不可作答', desc: '本题为缺选项/缺答案的空题，已下架练习，仅作浏览参考。' }
  }
  if (isChoiceQ(q)) return null
  if (q?.answer_type === 'subjective') {
    return { id: 'memorize', label: '仅记忆参考', desc: '本题有参考答案但题库缺少选项内容，仅供记忆参考，不可作答。' }
  }
  return null
}

/* 后端不可用时不编造题目：以前这里有两道「演示题」被塞进练习会话，
   页面看起来是一次正常刷题，判分和正确率却是凭空来的。加载失败由调用方
   如实报错（Quiz.jsx 的 startWithFilter catch 分支）。 */

export {
  TYPE_LABELS,
  LETTERS,
  letterOf,
  SOURCE_KIND_LABEL,
  loadWrong,
  addWrong,
  loadFavs,
  saveFavs,
  loadRecs,
  pushRec,
  normQ,
  isChoiceQ,
  isMultiQ,
}
