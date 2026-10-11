/**
 * API 类型定义（JSDoc）
 * 用于前端开发时的类型提示和文档
 */

/**
 * @typedef {Object} PaginatedResponse
 * @property {Array} items - 数据列表
 * @property {number} total - 总数
 * @property {number} page - 当前页码
 * @property {number} page_size - 每页数量
 * @property {number} total_pages - 总页数
 */

/**
 * @typedef {Object} Task
 * @property {number} id - 任务ID
 * @property {string} title - 任务标题
 * @property {string} subject - 科目（math/english/politics/major）
 * @property {string} task_type - 任务类型
 * @property {string} stage - 阶段
 * @property {string} status - 状态（pending/doing/done）
 * @property {number} priority - 优先级
 * @property {string} due_date - 截止日期（ISO格式）
 * @property {string} created_at - 创建时间
 * @property {string} completed_at - 完成时间
 */

/**
 * @typedef {Object} Word
 * @property {number} id - 单词ID
 * @property {string} word - 单词
 * @property {string} phonetic - 音标
 * @property {string} pos - 词性
 * @property {string} meaning - 释义
 * @property {number} deck_id - 词库ID
 * @property {string} status - 状态（new/learning/reviewing/mastered）
 * @property {number} ease_factor - 难度因子
 * @property {number} interval - 间隔（天）
 * @property {number} reps - 复习次数
 * @property {number} lapses - 遗忘次数
 * @property {string} due_date - 下次复习日期
 * @property {string} last_review - 上次复习日期
 * @property {Array} review_history - 复习历史
 */

/**
 * @typedef {Object} WordDeck
 * @property {number} id - 词库ID
 * @property {string} name - 词库名称
 * @property {string} description - 描述
 * @property {number} word_count - 单词数量（动态计算）
 */

/**
 * @typedef {Object} Flashcard
 * @property {number} id - 卡片ID
 * @property {string} front - 正面
 * @property {string} back - 背面
 * @property {number} knowledge_point_id - 知识点ID
 * @property {string} next_review - 下次复习时间
 * @property {number} review_count - 复习次数
 * @property {number} interval - 间隔
 * @property {number} ease_factor - 难度因子
 * @property {string} mastery - 掌握状态（new/learning/review/mastered）
 */

/**
 * @typedef {Object} ErrorRecord
 * @property {number} id - 错题ID
 * @property {number} question_id - 题目ID
 * @property {string} content - 题目内容
 * @property {string} my_answer - 我的答案
 * @property {string} correct_answer - 正确答案
 * @property {string} error_reason - 错误原因
 * @property {string} subject - 科目
 * @property {number} accuracy - 准确率（0-1）
 * @property {number} review_count - 复习次数
 * @property {string} last_review - 上次复习时间
 * @property {string} next_review - 下次复习时间
 * @property {string} status - 状态（active/graduated）
 * @property {Array} tags - 标签
 * @property {string} analysis - 解析
 */

/**
 * @typedef {Object} QuizQuestion
 * @property {number} id - 题目ID
 * @property {string} question - 题目
 * @property {Array} options - 选项
 * @property {string} answer - 正确答案
 * @property {string} explanation - 解析
 * @property {string} subject - 科目
 * @property {string} chapter - 章节
 * @property {string} difficulty - 难度
 * @property {string} question_type - 题型（single/multiple/judge/fill/essay）
 */

/**
 * @typedef {Object} Document
 * @property {number} id - 文档ID
 * @property {string} title - 标题
 * @property {string} file_type - 文件类型（pdf/docx/pptx/txt/md）
 * @property {number} file_size - 文件大小
 * @property {string} content - 内容（解析后）
 * @property {string} status - 状态（pending/parsing/parsed/failed）
 * @property {number} chunk_count - 分块数量
 * @property {string} created_at - 创建时间
 * @property {string} parsed_at - 解析时间
 */

/**
 * @typedef {Object} StudySession
 * @property {number} id - 会话ID
 * @property {string} date - 日期
 * @property {number} duration - 时长（分钟）
 * @property {string} subject - 科目
 * @property {string} task_type - 任务类型
 * @property {string} remark - 备注
 */

/**
 * @typedef {Object} DashboardStats
 * @property {number} today_duration - 今日学习时长（分钟）
 * @property {number} week_duration - 本周学习时长（分钟）
 * @property {Object} subject_durations - 各科目学习时长
 * @property {number} weekly_completed_tasks - 本周完成任务数
 * @property {number} active_errors - 活跃错题数
 * @property {Array} daily_trend - 7天学习趋势
 */

/**
 * @typedef {Object} AIProvider
 * @property {number} id - 服务商ID
 * @property {string} name - 名称
 * @property {string} provider_type - 类型（doubao/deepseek/qwen/ollama/custom）
 * @property {string} base_url - API地址
 * @property {string} model - 模型名称
 * @property {boolean} has_api_key - 是否有API密钥（不返回密钥本身）
 * @property {boolean} is_active - 是否启用
 * @property {number} priority - 优先级
 */

/**
 * @typedef {Object} ChatMessage
 * @property {string} role - 角色（system/user/assistant）
 * @property {string} content - 内容
 * @property {Array} [sources] - 引用来源（RAG）
 * @property {string} [model] - 使用的模型
 * @property {number} [tokens] - token消耗
 */

/**
 * @typedef {Object} NetdiskFile
 * @property {number} id - 文件ID
 * @property {string} file_name - 文件名
 * @property {string} file_type - 文件类型
 * @property {number} file_size - 文件大小
 * @property {string} path - 网盘路径
 * @property {string} status - 状态（synced/downloading/parsed/failed）
 * @property {string} synced_at - 同步时间
 */

/**
 * @typedef {Object} CustomLink
 * @property {number} id - 链接ID
 * @property {string} title - 标题
 * @property {string} url - 网址
 * @property {string} icon - 图标
 * @property {number} sort_order - 排序
 * @property {string} category - 分类
 */

/**
 * @typedef {Object} Semester
 * @property {number} id - 学期ID
 * @property {string} name - 学期名称
 * @property {string} start_date - 开始日期
 * @property {string} end_date - 结束日期
 * @property {number} current_week - 当前周
 */

/**
 * @typedef {Object} Course
 * @property {number} id - 课程ID
 * @property {number} semester_id - 学期ID
 * @property {string} name - 课程名称
 * @property {string} teacher - 教师
 * @property {string} location - 地点
 * @property {number} day_of_week - 星期几（1-7）
 * @property {number} start_period - 开始节次
 * @property {number} end_period - 结束节次
 * @property {string} start_time - 开始时间
 * @property {string} end_time - 结束时间
 * @property {string} color - 颜色
 * @property {Array} weeks - 上课周次
 */

// 导出（供 ESLint / JSDoc 工具识别）
export {}
