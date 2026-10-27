# -*- coding: utf-8 -*-
"""构建「考研熟词僻义」内置模板词库（user_id=1 模板，KyleBing 多义项精选）。

- 词库：word_decks.user_id=1, name='考研熟词僻义', source='KyleBing'
- 词条：从既有 考研核心词汇（deck1/user1 或 deck5/user10）复制内容，
  释义追加「僻义」提示，extra 挂 KyleBing senses（多义项）。
- 新用户由 routers/words._ensure_personal_wordbook 克隆该模板词库。
- 既有用户由本脚本末尾的 backfill 逻辑克隆。
"""
import json
import os
import re
import sys

import psycopg

DB = dict(host='127.0.0.1', port=5432, user='kaoyan', password='kaoyan_dev_2026', dbname='kaoyan')
DECK_NAME = '考研熟词僻义'
DECK_DESC = '考研英语熟词僻义专题：基于 KyleBing 多义项数据精选，标注考研真题中的僻义用法'
DECK_SOURCE = 'KyleBing'

# (word, 僻义提示)
SEED = [
    ('address', '处理；向…致辞'),
    ('book', '预订'),
    ('champion', '拥护，支持'),
    ('coat', '覆盖，涂上'),
    ('desert', '抛弃，遗弃'),
    ('novel', '新颖的'),
    ('subject', '使遭受；易受…的'),
    ('minute', '微小的，细致的'),
    ('second', '赞成，支持'),
    ('table', '提交（议案）讨论'),
    ('screen', '审查，筛选'),
    ('doctor', '篡改，伪造'),
    ('plant', '工厂，设备'),
    ('interest', '利息；利益'),
    ('capital', '首都；资本；大写的'),
    ('check', '控制，抑制；支票'),
    ('figure', '认为；数字；人物'),
    ('fine', '罚款；精细的'),
    ('pool', '联营；集中（资金）'),
    ('season', '使适应；调味'),
    ('sentence', '判决'),
    ('spring', '弹簧；泉水；涌现'),
    ('train', '培训；训练'),
    ('account', '解释（account for）'),
    ('act', '法案；起作用'),
    ('advance', '提出；预付款'),
    ('air', '播出；神态'),
    ('ball', '舞会'),
    ('bank', '河岸，堤'),
    ('bar', '律师界；阻止'),
    ('beam', '微笑；横梁'),
    ('bear', '忍受；生育'),
    ('bill', '法案；账单'),
    ('block', '街区；阻塞'),
    ('board', '董事会；登机'),
    ('bond', '债券；纽带'),
    ('branch', '分支；分部'),
    ('bridge', '弥合（鸿沟）'),
    ('brief', '简短的；作简报'),
    ('call', '需求'),
    ('campaign', '战役；运动'),
    ('case', '案件；情况'),
    ('cast', '演员表；投掷'),
    ('cause', '事业；原因'),
    ('cell', '电池；细胞'),
    ('chair', '主持'),
    ('change', '零钱'),
    ('charge', '指控；收费；充电'),
    ('claim', '索赔；声称'),
    ('close', '亲密的；关闭'),
    ('company', '陪伴'),
    ('conduct', '进行；行为'),
    ('contract', '收缩；合同'),
    ('count', '伯爵'),
    ('court', '球场；法院'),
    ('cover', '报道；覆盖'),
    ('credit', '学分；信用'),
    ('custom', '海关（customs）'),
    ('deal', '处理；交易'),
    ('degree', '程度；度数'),
    ('deposit', '存款；押金'),
    ('design', '意图；设计'),
    ('develop', '发展；冲洗（胶卷）'),
    ('device', '手段；装置'),
    ('drive', '驱动；驾驶'),
    ('economy', '节约；经济'),
    ('employ', '使用；雇用'),
    ('exercise', '运用；锻炼'),
    ('express', '快递；表达'),
    ('fair', '展览会；公平的'),
    ('fashion', '方式；时尚'),
    ('father', '创立'),
    ('fault', '断层；过错'),
    ('favor', '恩惠；赞成'),
    ('feature', '以…为特色'),
    ('file', '归档；文件'),
    ('firm', '公司；坚定的'),
    ('fit', '安装；适合'),
    ('flat', '公寓；平的'),
    ('fold', '羊圈；折叠'),
    ('frame', '陷害；框架'),
    ('fresh', '淡水的；新鲜的'),
    ('function', '运转；功能'),
    ('fund', '资助；基金'),
    ('game', '猎物'),
    ('general', '将军；一般的'),
    ('gift', '天赋；礼物'),
    ('grade', '评分；等级'),
    ('grain', '谷物；纹理'),
    ('grant', '授予；补助金'),
    ('ground', '理由；地面'),
    ('hand', '交给；手'),
    ('handle', '处理；把手'),
    ('head', '朝…前进'),
    ('heart', '中心；心脏'),
    ('hide', '兽皮'),
    ('host', '主持；主人'),
    ('house', '容纳'),
    ('inch', '缓慢移动'),
    ('industry', '勤奋；工业'),
    ('iron', '熨烫；铁'),
    ('judge', '判断；法官'),
    ('kind', '种类；友善的'),
    ('land', '着陆'),
    ('last', '持续'),
    ('lay', '放置；产卵'),
    ('lead', '铅；领导'),
    ('lecture', '训斥；讲座'),
    ('lesson', '教训；功课'),
    ('light', '轻的；点燃'),
    ('live', '现场的；居住'),
    ('long', '渴望'),
    ('look', '外表'),
    ('lot', '抽签'),
    ('manage', '设法；管理'),
    ('manner', '方式；礼貌'),
    ('march', '三月；行军'),
    ('mark', '打分；标记'),
    ('match', '火柴；比赛'),
    ('master', '掌握；主人'),
    ('matter', '要紧'),
    ('mean', '吝啬的'),
    ('measure', '措施；测量'),
    ('meet', '满足'),
    ('might', '力量'),
    ('mind', '介意；头脑'),
    ('mine', '矿'),
    ('miss', '想念；错过'),
    ('model', '模特；模型'),
    ('move', '感动'),
    ('note', '注意；笔记'),
    ('notice', '注意到；通知'),
    ('object', '反对；物体'),
    ('order', '订单；命令'),
    ('paper', '论文；纸'),
    ('park', '停车'),
    ('part', '角色；部分'),
    ('party', '政党；聚会'),
    ('pass', '通过；传球'),
    ('perform', '执行；表演'),
    ('period', '句号；时期'),
    ('picture', '想象'),
    ('piece', '作品；片'),
    ('plane', '平面'),
    ('play', '戏剧'),
    ('point', '指出'),
    ('post', '职位；邮件'),
    ('pound', '重击；英镑'),
    ('present', '呈现；礼物'),
    ('press', '新闻界'),
    ('pretty', '相当'),
    ('produce', '农产品'),
    ('question', '质疑'),
    ('race', '种族；赛跑'),
    ('raise', '筹集；举起'),
    ('range', '山脉；范围'),
    ('rate', '评价；比率'),
    ('reason', '推理；原因'),
    ('record', '唱片；记录'),
    ('refuse', '垃圾'),
    ('regard', '认为'),
    ('rest', '剩余；休息'),
    ('result', '导致'),
    ('return', '归还'),
    ('review', '评论；复习'),
    ('right', '权利'),
    ('ring', '打电话；戒指'),
    ('rise', '加薪；上升'),
    ('rock', '摇滚'),
    ('roll', '名册'),
    ('room', '空间'),
    ('round', '回合'),
    ('row', '排；划船'),
    ('rule', '统治；规则'),
    ('run', '经营；跑'),
    ('safe', '保险箱'),
    ('scale', '规模；秤'),
    ('school', '学派'),
    ('score', '二十；分数'),
    ('sense', '意义；感觉'),
    ('serve', '发球；服务'),
    ('service', '维修'),
    ('set', '集合'),
    ('settle', '定居；解决'),
    ('share', '股份'),
    ('ship', '运送'),
    ('shoot', '射击；发芽'),
    ('show', '演出'),
    ('side', '支持'),
    ('sight', '景象；视力'),
    ('sign', '签署；标志'),
    ('sink', '水槽'),
    ('soil', '弄脏'),
    ('solid', '坚实的；固体'),
    ('sort', '整理'),
    ('sound', '健全的；听起来'),
    ('spot', '发现；地点'),
    ('stage', '阶段；舞台'),
    ('stand', '忍受'),
    ('star', '主演'),
    ('state', '陈述；州'),
    ('station', '驻扎'),
    ('steep', '陡峭的'),
    ('stick', '坚持'),
    ('still', '静止的'),
    ('strike', '罢工；打击'),
    ('string', '弦；线'),
    ('subject2', None),  # 占位（不会命中）
    ('support', '支持'),
    ('surface', '表面'),
    ('swing', '秋千'),
    ('tear', '撕破；眼泪'),
    ('tell', '分辨'),
    ('term', '术语；学期'),
    ('tie', '平局；系'),
    ('time', '次数'),
    ('tip', '小费；提示；尖端'),
    ('title', '头衔'),
    ('tone', '语气'),
    ('tongue', '语言'),
    ('top', '最好的'),
    ('total', '总计'),
    ('touch', '联系'),
    ('trip', '绊倒'),
    ('trust', '信任'),
    ('type', '打字'),
    ('value', '珍视'),
    ('view', '看待'),
    ('voice', '表达'),
    ('want', '需要'),
    ('watch', '手表'),
    ('water', '浇水'),
    ('wave', '挥手'),
    ('way', '方式'),
    ('wear', '磨损'),
    ('well', '井'),
    ('while', '一会儿'),
    ('will', '意志'),
    ('wind', '缠绕'),
    ('wire', '发电报'),
    ('wonder', '想知道'),
    ('wood', '树林'),
    ('word', '消息'),
    ('work', '运转'),
    ('wound', '伤害'),
    ('yard', '院子'),
]


def load_kylebing_senses():
    """KyleBing 考研词库 translations（word -> senses list）"""
    path = r'D:\平台\data_sources\english-vocabulary\english-vocabulary-master\json\5-考研-顺序.json'
    data = json.load(open(path, encoding='utf-8'))
    return {item['word'].lower(): item.get('translations', []) for item in data}


def find_source_word(cur, word):
    """从 deck1/user1、deck5/user10、deck6/public 找已有词条。"""
    for deck_id, uid in ((1, 1), (5, 10), (6, None)):
        if uid is None:
            cur.execute(
                'SELECT id, deck_id, phonetic, pos, meaning, root, example, example_cn, tag, extra '
                'FROM words WHERE word=%s AND deck_id=%s AND user_id IS NULL LIMIT 1',
                (word, deck_id),
            )
        else:
            cur.execute(
                'SELECT id, deck_id, phonetic, pos, meaning, root, example, example_cn, tag, extra '
                'FROM words WHERE word=%s AND deck_id=%s AND user_id=%s LIMIT 1',
                (word, deck_id, uid),
            )
        row = cur.fetchone()
        if row:
            return row
    return None


def main():
    conn = psycopg.connect(**DB)
    cur = conn.cursor()

    # 1) 创建模板词库（user_id=1 内置模板）
    cur.execute("SELECT id FROM word_decks WHERE user_id=1 AND name=%s", (DECK_NAME,))
    row = cur.fetchone()
    if row:
        deck_id = row[0]
        print('deck exists:', deck_id, flush=True)
    else:
        cur.execute("""
            INSERT INTO word_decks (user_id, name, description, source, word_count)
            VALUES (1, %s, %s, %s, 0) RETURNING id
        """, (DECK_NAME, DECK_DESC, DECK_SOURCE))
        deck_id = cur.fetchone()[0]
        print('deck created:', deck_id, flush=True)

    senses_map = load_kylebing_senses()

    # 2) 插入词条（幂等：同 deck+word 已存在则更新）
    added = 0
    for word, piyi in SEED:
        if not piyi or word == 'subject2':
            continue
        src = find_source_word(cur, word)
        if not src:
            print(f'  [skip] {word} 不在既有词库', flush=True)
            continue
        src_id, _src_deck, phonetic, pos, meaning, root, example, example_cn, tag, extra = src
        senses = senses_map.get(word.lower(), [])
        extra_dict = dict(extra) if isinstance(extra, dict) else {}
        extra_dict['source'] = 'KyleBing'
        extra_dict['shuci_piyi'] = piyi
        if senses:
            extra_dict['senses'] = senses
        new_meaning = f"{meaning} ｜僻义：{piyi}" if piyi and piyi not in (meaning or '') else meaning
        cur.execute("""
            SELECT id FROM words WHERE user_id=1 AND deck_id=%s AND word=%s
        """, (deck_id, word))
        existing = cur.fetchone()
        if existing:
            cur.execute("""
                UPDATE words SET phonetic=%s, pos=%s, meaning=%s, root=%s,
                       example=%s, example_cn=%s, tag=%s, extra=%s
                WHERE id=%s
            """, (phonetic, pos, new_meaning, root, example, example_cn, '熟词僻义',
                  json.dumps(extra_dict, ensure_ascii=False), existing[0]))
        else:
            cur.execute("""
                INSERT INTO words (user_id, deck_id, word, phonetic, pos, meaning, root,
                                   example, example_cn, tag, status, ease_factor, interval_days,
                                   reps, lapses, due_date, last_review, review_history, extra)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, '熟词僻义', 'not_mastered', 2.5, 0,
                        0, 0, NULL, NULL, '[]'::jsonb, %s)
            """, (deck_id, word, phonetic, pos, new_meaning, root, example, example_cn,
                  json.dumps(extra_dict, ensure_ascii=False)))
        added += 1

    cur.execute("SELECT count(*) FROM words WHERE user_id=1 AND deck_id=%s", (deck_id,))
    word_count = cur.fetchone()[0]
    cur.execute("UPDATE word_decks SET word_count=%s WHERE id=%s", (word_count, deck_id))
    conn.commit()
    print(f'DONE: deck={deck_id} words={word_count} added={added}', flush=True)

    # 3) Backfill：为已有人词库的既有用户克隆缺失的模板词库
    cur.execute("SELECT DISTINCT user_id FROM word_decks WHERE user_id IS NOT NULL AND user_id != 1 ORDER BY user_id")
    user_ids = [r[0] for r in cur.fetchall()]
    cloned_users = 0
    for uid in user_ids:
        # 该用户是否已有本词库副本
        cur.execute("SELECT id FROM word_decks WHERE user_id=%s AND name=%s", (uid, DECK_NAME))
        if cur.fetchone():
            continue
        # 克隆 deck + words
        cur.execute("""
            INSERT INTO word_decks (user_id, name, description, source, word_count)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (uid, DECK_NAME, DECK_DESC, DECK_SOURCE, word_count))
        user_deck_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO words (user_id, deck_id, word, phonetic, pos, meaning, root,
                               example, example_cn, tag, status, ease_factor, interval_days,
                               reps, lapses, due_date, last_review, review_history, extra)
            SELECT %s, %s, word, phonetic, pos, meaning, root,
                   example, example_cn, tag, 'not_mastered', 2.5, 0, 0, 0, NULL, NULL,
                   '[]'::jsonb, extra
            FROM words WHERE user_id=1 AND deck_id=%s
        """, (uid, user_deck_id, deck_id))
        cloned_users += 1
    conn.commit()
    print(f'backfill: cloned to {cloned_users} existing users', flush=True)
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())