# 备份恢复演练（每季度）

> 最后核对：2026-11-20 · 维护人：pyy
> 依据：完善方案 05 §3.5 / 09 §3.2。**没验证过恢复的备份 = 薛定谔的备份。**

## 1. 前置

- 最新加密备份：`/opt/kaoyan/backups/kaoyan_<ts>.dump.enc`
- 密钥 `KAOYAN_SECRET_KEY` 从密码管理器/纸质离线介质取（**不在备份同机**）
- 目标：临时库 `kaoyan_restore_drill`（绝不覆盖生产库）

## 2. 步骤

```bash
# 1) 解密
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in kaoyan_<ts>.dump.enc -out /tmp/restore.dump -pass "pass:$KAOYAN_SECRET_KEY"

# 2) 建临时库并恢复
createdb -h 127.0.0.1 -U kaoyan kaoyan_restore_drill
pg_restore -h 127.0.0.1 -U kaoyan -d kaoyan_restore_drill --no-owner /tmp/restore.dump

# 3) 关键表校验
psql -h 127.0.0.1 -U kaoyan -d kaoyan_restore_drill -c "
SELECT 'quiz_questions' t, count(*) FROM quiz_questions
UNION ALL SELECT 'knowledge_chunks', count(*) FROM knowledge_chunks
UNION ALL SELECT 'schema_migrations', count(*) FROM schema_migrations;"

# 4) 收尾
dropdb -h 127.0.0.1 -U kaoyan kaoyan_restore_drill
shred -u /tmp/restore.dump
```

## 3. 验收项（全部通过才算演练成功）

- [ ] 密文可解密（密钥可用、未被截断）
- [ ] `pg_restore` 无 error（warning 需逐条判断）
- [ ] 关键表行数与生产同量级（允许备份时点差）
- [ ] `schema_migrations` 完整（账本行数 = 已执行脚本数）
- [ ] `/api/health` 能从恢复库起服务（可选，验证数据可用性）

## 4. 留档

报告写到 `docs/reports/restore-drill-<YYYYMMDD>.md`，记录：备份文件名、大小、恢复耗时、
关键表行数、异常与处置。**演练日期进日历，每季度一次。**

## 5. 记录

| 日期 | 备份文件 | 结果 | 报告 |
|---|---|---|---|
| （首次演练待执行） | — | — | — |
