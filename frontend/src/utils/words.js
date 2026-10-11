/* 单词记忆模块：词库数据 + 导入解析 */

/**
 * 预置考研核心词库（示例 20 词，含真题例句、词根词缀、助记）
 * 词条结构：{ word, phonetic, pos, meaning, root, example, ex_cn, tag }
 */
export const CORE_WORDS = [
  { word: 'approach', phonetic: '/əˈprəʊtʃ/', pos: 'v./n.', meaning: '接近；方法，途径', root: 'ap(向)+proach(靠近)→靠近', example: 'We need a new approach to solve this problem.', ex_cn: '我们需要一种新的方法来解决这个问题。', tag: '高频' },
  { word: 'significant', phonetic: '/sɪɡˈnɪfɪkənt/', pos: 'adj.', meaning: '重要的；显著的', root: 'sign(标记)+ificant→有标志的→重要的', example: 'There has been a significant increase in the number of applicants.', ex_cn: '申请人数有了显著增长。', tag: '高频' },
  { word: 'available', phonetic: '/əˈveɪləbl/', pos: 'adj.', meaning: '可获得的；有空的', root: 'a(去)+vail(价值)+able→有价值的→可用的', example: 'The report is available online.', ex_cn: '这份报告可以在线获取。', tag: '高频' },
  { word: 'maintain', phonetic: '/meɪnˈteɪn/', pos: 'v.', meaning: '维持；坚持认为', root: 'main(手)+tain(拿住)→握在手中→维持', example: 'It is important to maintain a balanced diet.', ex_cn: '保持均衡饮食很重要。', tag: '高频' },
  { word: 'phenomenon', phonetic: '/fəˈnɒmɪnən/', pos: 'n.', meaning: '现象', root: 'pheno(显示)+menon→显现出来的东西→现象', example: 'Global warming is a widely discussed phenomenon.', ex_cn: '全球变暖是一个被广泛讨论的现象。', tag: '高频' },
  { word: 'assume', phonetic: '/əˈsjuːm/', pos: 'v.', meaning: '假定；承担', root: 'as(去)+sume(拿取)→拿过来作为己用→承担/假定', example: 'We cannot assume that all students have the same background.', ex_cn: '我们不能假定所有学生背景相同。', tag: '高频' },
  { word: 'environment', phonetic: '/ɪnˈvaɪrənmənt/', pos: 'n.', meaning: '环境', root: 'en(在…内)+viron(转)+ment→环绕周围→环境', example: 'Children need a safe environment to grow.', ex_cn: '儿童需要一个安全的环境来成长。', tag: '高频' },
  { word: 'consequence', phonetic: '/ˈkɒnsɪkwəns/', pos: 'n.', meaning: '结果，后果', root: 'con(共同)+sequ(跟随)+ence→跟随而来的→结果', example: 'Every decision has its consequences.', ex_cn: '每个决定都有其后果。', tag: '高频' },
  { word: 'effective', phonetic: '/ɪˈfektɪv/', pos: 'adj.', meaning: '有效的', root: 'ef(出)+fect(做)+ive→做出来的→有效的', example: 'Regular review is an effective way to memorize words.', ex_cn: '定期复习是记单词的有效方法。', tag: '高频' },
  { word: 'individual', phonetic: '/ˌɪndɪˈvɪdʒuəl/', pos: 'adj./n.', meaning: '个人的；个体', root: 'in(不)+divid(分)+ual→不可再分的→个体', example: 'Each individual has unique strengths.', ex_cn: '每个人都有自己的独特优势。', tag: '高频' },
  { word: 'participate', phonetic: '/pɑːˈtɪsɪpeɪt/', pos: 'v.', meaning: '参与', root: 'part(部分)+cip(拿取)+ate→取一部分→参与', example: 'Students are encouraged to participate in class activities.', ex_cn: '鼓励学生参与课堂活动。', tag: '高频' },
  { word: 'particular', phonetic: '/pəˈtɪkjələ(r)/', pos: 'adj.', meaning: '特别的；特定的', root: 'part(部分)+icular→只属于部分的→特别的', example: 'Pay particular attention to the last paragraph.', ex_cn: '特别注意最后一段。', tag: '高频' },
  { word: 'appropriate', phonetic: '/əˈprəʊpriət/', pos: 'adj.', meaning: '适当的，恰当的', root: 'ap(向)+propri(自己的)+ate→归于自己→适当的', example: 'Choose the appropriate word for each blank.', ex_cn: '为每个空格选择恰当的词语。', tag: '高频' },
  { word: 'require', phonetic: '/rɪˈkwaɪə(r)/', pos: 'v.', meaning: '需要；要求', root: 're(再)+quire(寻求)→反复寻求→要求', example: 'This course requires a lot of self-discipline.', ex_cn: '这门课程需要很强的自律性。', tag: '高频' },
  { word: 'capacity', phonetic: '/kəˈpæsəti/', pos: 'n.', meaning: '容量；能力', root: 'cap(容纳)+acity→容纳的量→容量/能力', example: 'She has a great capacity for learning.', ex_cn: '她有很强的学习能力。', tag: '高频' },
  { word: 'distinguish', phonetic: '/dɪˈstɪŋɡwɪʃ/', pos: 'v.', meaning: '区分，辨别', root: 'di(分开)+sting(刺)+uish→刺出标记→区分', example: 'It is hard to distinguish the twins.', ex_cn: '很难分辨这对双胞胎。', tag: '高频' },
  { word: 'evidence', phonetic: '/ˈevɪdəns/', pos: 'n.', meaning: '证据', root: 'e(出)+vid(看)+ence→看得出→证据', example: 'There is strong evidence supporting this theory.', ex_cn: '有强有力的证据支持这一理论。', tag: '高频' },
  { word: 'exposure', phonetic: '/ɪkˈspəʊʒə(r)/', pos: 'n.', meaning: '暴露；接触', root: 'ex(出)+pos(放置)+ure→放置在外→暴露', example: 'Frequent exposure to English improves listening.', ex_cn: '经常接触英语能提高听力。', tag: '高频' },
  { word: 'fundamental', phonetic: '/ˌfʌndəˈmentl/', pos: 'adj.', meaning: '基础的，根本的', root: 'fund(基础)+ament+al→基础的', example: 'Reading is a fundamental skill.', ex_cn: '阅读是一项基本技能。', tag: '高频' },
  { word: 'inevitable', phonetic: '/ɪnˈevɪtəbl/', pos: 'adj.', meaning: '不可避免的', root: 'in(不)+evit(避免)+able→不可避免的', example: 'Mistakes are inevitable in the learning process.', ex_cn: '学习过程中犯错是不可避免的。', tag: '高频' }
]

/** 预置卡包数据（错题/知识点可直接转为卡片） */
export const SEED_PACKS = [
  { id: 'pk-math', name: '数学公式卡', subject: 'math', color: 0 },
  { id: 'pk-english', name: '英语高频词卡', subject: 'english', color: 1 },
  { id: 'pk-politics', name: '政治知识点卡', subject: 'politics', color: 3 },
  { id: 'pk-major', name: '834 专业卡', subject: 'major', color: 2 }
]

/**
 * 解析自定义词库文本
 * 支持格式：
 *   - 每行：word / 释义 / 例句  (用 / 或 | 分隔)
 *   - 或：word 释义 (空格分隔)
 *   - 或 JSON 数组 [{word, meaning, ...}]
 * @returns {Array} 解析出的词条数组
 */
export function parseWordList(text) {
  if (!text || !text.trim()) return []
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  const out = []
  for (const line of lines) {
    if (line.startsWith('[') || line.startsWith('{')) {
      try {
        const arr = JSON.parse(line)
        if (Array.isArray(arr)) {
          arr.forEach((w) => {
            if (w && w.word) out.push(normalizeWord(w))
          })
          continue
        }
      } catch { /* 非 JSON 则按行解析 */ }
    }
    const sep = line.includes('/') ? '/' : line.includes('|') ? '|' : null
    if (sep) {
      const [word, meaning, example, ex_cn] = line.split(sep).map((s) => s.trim())
      if (word) out.push(normalizeWord({ word, meaning: meaning || '', example: example || '', ex_cn: ex_cn || '' }))
    } else {
      // word + 空格 + 释义
      const m = line.match(/^(\S+)\s+(.+)$/)
      if (m) out.push(normalizeWord({ word: m[1], meaning: m[2] }))
    }
  }
  return out
}

function normalizeWord(w) {
  return {
    word: String(w.word).trim(),
    phonetic: w.phonetic || '',
    pos: w.pos || '',
    meaning: w.meaning || '',
    root: w.root || '',
    example: w.example || '',
    ex_cn: w.ex_cn || '',
    tag: w.tag || '自定义'
  }
}

/** 从错题生成单词卡（English 科目错题） */
export function noteToCard(note) {
  return {
    front: note.question,
    back: note.answer,
    hint: note.analysis || '',
    subject: note.subject,
    sourceNoteId: note.id
  }
}

/** 按科目生成大纲式知识点清单（供 AI 生成知识导图） */
export function outlineFromNotes(notes) {
  const groups = {}
  notes.forEach((n) => {
    const sub = n.subject || 'other'
    if (!groups[sub]) groups[sub] = []
    groups[sub].push({ q: n.question, tag: (n.tags || []).join(',') })
  })
  return Object.entries(groups).map(([sub, items]) => ({
    subject: sub,
    items: items.slice(0, 8),
    count: items.length
  }))
}
