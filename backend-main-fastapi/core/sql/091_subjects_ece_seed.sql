-- =============================================================================
-- 091 电子通信考研核心科目补齐
-- 依赖：010（subjects / subject_chapters / subject_aliases）
--
-- 背景：迁移前 PG subjects 只有 6 行（数电/模电/数学/英语/政治/信号与系统），
-- 而用户要导入的 25 本教材覆盖 8 个科目方向。缺口最严重的是：
--   * 数字信号处理（DSP）—— 复试高频，全库零存在
--   * 电磁场与电磁波 —— 天线射频方向，全库零存在
--   * 通信原理 / 电路 —— PG 里完全没有（SQLite 侧也只有章级骨架）
--   * 计算机网络 —— 仅作为 408 子章节存在，未独立成科目
--
-- 本分片幂等（ON CONFLICT DO NOTHING），可重复执行。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 1. 补齐备考科目（subjects）
-- --------------------------------------------------------------------------- #
INSERT INTO subjects (code, name, short_name, category, exam_overlap, description, sort_order, is_custom)
VALUES
  ('communication_principles', '通信原理', '通原', 'professional',
   '与信号与系统在频谱分析、随机过程上有重叠',
   '电子通信考研最核心专业课之一，樊昌信/周炯槃等多套教材体系', 61, FALSE),
  ('circuit', '电路', '电路', 'professional',
   '与模拟电子技术在放大电路分析上重叠',
   '电路分析基础，邱关源/李瀚荪体系，多数院校初试必考', 62, FALSE),
  ('digital_signal_processing', '数字信号处理', 'DSP', 'professional',
   '与信号与系统共享 z 变换、采样定理基础',
   '复试高频科目，高西全/程佩青等多套教材体系', 63, FALSE),
  ('electromagnetic_field', '电磁场与电磁波', '电磁场', 'professional',
   '与普通物理电磁学部分重叠',
   '天线射频方向核心科目，谢处方教材为国内主流', 64, FALSE),
  ('computer_networks', '计算机网络', '计网', 'professional',
   '与 408 计算机网络部分考纲一致',
   '部分院校电子通信专业复试科目', 65, FALSE)
ON CONFLICT (code) DO NOTHING;

-- --------------------------------------------------------------------------- #
-- 2. 科目别名（收敛中文异写）
-- --------------------------------------------------------------------------- #
INSERT INTO subject_aliases (alias, subject_id, alias_source, is_primary)
SELECT a.alias, s.id, 'seed_catalog', TRUE
FROM (VALUES
  ('通信系统原理', 'communication_principles'),
  ('通信原理教程', 'communication_principles'),
  ('电路分析基础', 'circuit'),
  ('电路理论', 'circuit'),
  ('电工学', 'circuit'),
  ('数字信号处理', 'digital_signal_processing'),
  ('DSP', 'digital_signal_processing'),
  ('数字信号处理教程', 'digital_signal_processing'),
  ('电磁场', 'electromagnetic_field'),
  ('电磁场与电磁波理论基础', 'electromagnetic_field'),
  ('电磁场与波', 'electromagnetic_field'),
  ('计算机网络', 'computer_networks'),
  ('计网', 'computer_networks')
) AS a(alias, code)
JOIN subjects s ON s.code = a.code
ON CONFLICT (alias, subject_id) DO NOTHING;

-- --------------------------------------------------------------------------- #
-- 3. 章节大纲（subject_chapters）
--    章号与主流教材目录对齐，便于教材与知识点双向挂接。
-- --------------------------------------------------------------------------- #
-- 通信原理（樊昌信 第7版 13章体系）
INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 绪论', 1),
  ('ch02', '第2章 确知信号', 2),
  ('ch03', '第3章 随机过程', 3),
  ('ch04', '第4章 信道', 4),
  ('ch05', '第5章 模拟调制系统', 5),
  ('ch06', '第6章 数字基带传输系统', 6),
  ('ch07', '第7章 数字带通传输系统', 7),
  ('ch08', '第8章 新型数字带通调制技术', 8),
  ('ch09', '第9章 模拟信号的数字传输', 9),
  ('ch10', '第10章 数字信号的最佳接收', 10),
  ('ch11', '第11章 差错控制编码', 11),
  ('ch12', '第12章 正交编码与伪随机序列', 12),
  ('ch13', '第13章 同步原理', 13)
) AS c(code, title, ord)
WHERE s.code = 'communication_principles'
ON CONFLICT (subject_id, code) DO NOTHING;

-- 电路（邱关源 第6版 15章体系）
INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 电路模型和电路定律', 1),
  ('ch02', '第2章 电阻电路的等效变换', 2),
  ('ch03', '第3章 电阻电路的一般分析', 3),
  ('ch04', '第4章 电路定理', 4),
  ('ch05', '第5章 含运算放大器的电阻电路', 5),
  ('ch06', '第6章 储能元件', 6),
  ('ch07', '第7章 一阶电路和二阶电路的时域分析', 7),
  ('ch08', '第8章 相量法', 8),
  ('ch09', '第9章 正弦稳态电路的分析', 9),
  ('ch10', '第10章 含耦合电感的电路', 10),
  ('ch11', '第11章 电路的频率响应', 11),
  ('ch12', '第12章 三相电路', 12),
  ('ch13', '第13章 非正弦周期电流电路', 13),
  ('ch14', '第14章 线性动态电路的复频域分析', 14),
  ('ch15', '第15章 二端口网络', 15)
) AS c(code, title, ord)
WHERE s.code = 'circuit'
ON CONFLICT (subject_id, code) DO NOTHING;

-- 数字信号处理（高西全/程佩青 通用体系）
INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 离散时间信号与系统', 1),
  ('ch02', '第2章 z变换与离散时间傅里叶变换', 2),
  ('ch03', '第3章 离散傅里叶变换 DFT', 3),
  ('ch04', '第4章 快速傅里叶变换 FFT', 4),
  ('ch05', '第5章 数字滤波器的基本结构', 5),
  ('ch06', '第6章 无限长单位冲激响应 IIR 数字滤波器设计', 6),
  ('ch07', '第7章 有限长单位冲激响应 FIR 数字滤波器设计', 7),
  ('ch08', '第8章 多采样率数字信号处理', 8),
  ('ch09', '第9章 数字信号处理中的有限字长效应', 9)
) AS c(code, title, ord)
WHERE s.code = 'digital_signal_processing'
ON CONFLICT (subject_id, code) DO NOTHING;

-- 电磁场与电磁波（谢处方 第5版体系）
INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 矢量分析', 1),
  ('ch02', '第2章 电磁场的基本规律', 2),
  ('ch03', '第3章 静态电磁场及其边值问题的解', 3),
  ('ch04', '第4章 时变电磁场', 4),
  ('ch05', '第5章 均匀平面波在无界空间中的传播', 5),
  ('ch06', '第6章 均匀平面波的反射与透射', 6),
  ('ch07', '第7章 导行电磁波', 7),
  ('ch08', '第8章 电磁辐射', 8)
) AS c(code, title, ord)
WHERE s.code = 'electromagnetic_field'
ON CONFLICT (subject_id, code) DO NOTHING;

-- 计算机网络（谢希仁 体系）
INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 概述', 1),
  ('ch02', '第2章 物理层', 2),
  ('ch03', '第3章 数据链路层', 3),
  ('ch04', '第4章 网络层', 4),
  ('ch05', '第5章 运输层', 5),
  ('ch06', '第6章 应用层', 6),
  ('ch07', '第7章 网络安全', 7),
  ('ch08', '第8章 互联网上的音频视频服务', 8)
) AS c(code, title, ord)
WHERE s.code = 'computer_networks'
ON CONFLICT (subject_id, code) DO NOTHING;

-- 信号与系统补章节（PG 中该科目此前无章节）
INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 信号与系统概述', 1),
  ('ch02', '第2章 连续时间系统的时域分析', 2),
  ('ch03', '第3章 傅里叶变换', 3),
  ('ch04', '第4章 拉普拉斯变换与s域分析', 4),
  ('ch05', '第5章 傅里叶级数与频谱', 5),
  ('ch06', '第6章 离散时间系统的时域分析', 6),
  ('ch07', '第7章 z变换与z域分析', 7),
  ('ch08', '第8章 系统的状态变量分析', 8),
  ('ch09', '第9章 采样定理与信号重建', 9)
) AS c(code, title, ord)
WHERE s.code = 'signals_systems'
ON CONFLICT (subject_id, code) DO NOTHING;

-- 数电 / 模电补章节（对齐 834 考试口径教材目录）
INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 数制和码制', 1),
  ('ch02', '第2章 逻辑代数基础', 2),
  ('ch03', '第3章 门电路', 3),
  ('ch04', '第4章 组合逻辑电路', 4),
  ('ch05', '第5章 半导体存储电路', 5),
  ('ch06', '第6章 时序逻辑电路', 6),
  ('ch07', '第7章 脉冲波形的产生和整形', 7),
  ('ch08', '第8章 数模与模数转换', 8)
) AS c(code, title, ord)
WHERE s.code = 'digital_electronics'
ON CONFLICT (subject_id, code) DO NOTHING;

INSERT INTO subject_chapters (subject_id, code, title, sort_order)
SELECT s.id, c.code, c.title, c.ord
FROM subjects s,
(VALUES
  ('ch01', '第1章 常用半导体器件', 1),
  ('ch02', '第2章 基本放大电路', 2),
  ('ch03', '第3章 多级放大电路', 3),
  ('ch04', '第4章 集成运算放大电路', 4),
  ('ch05', '第5章 放大电路的频率响应', 5),
  ('ch06', '第6章 放大电路中的反馈', 6),
  ('ch07', '第7章 信号的运算和处理', 7),
  ('ch08', '第8章 波形的产生和信号的转换', 8),
  ('ch09', '第9章 功率放大电路', 9),
  ('ch10', '第10章 直流电源', 10)
) AS c(code, title, ord)
WHERE s.code = 'analog_electronics'
ON CONFLICT (subject_id, code) DO NOTHING;
