你是 IMA 正文入库工人。任务：把分配给你的那一片（shard）资料的正文从 IMA 知识库取回，写入真库 `D:\平台\database\kaoyan.db` 的 `documents.content`。**只做正文入库，绝对不要跑知识点抽取。**

## 你的分片
分片文件：`D:\平台\tools\datasource\shards\shard_%SHARD%.json`（JSON，字段 doc_id / media_id / title / subject / media_type）
先用 Read 读它，得到 items 列表。

## 对每条 item 严格按序执行（一次只处理一条，禁止批量缓存正文）
1. 调 MCP 工具 `mcp__ima-mcp__fetch_media_content`，参数 `media_id` = 该 item 的 media_id。
2. 工具返回 `{"content":"..."}` 形式的正文。**立刻**用 Write 工具把**完整原始返回内容原样**写入文件：
   `D:\平台\tools\datasource\payload\fetch_<doc_id>.txt`
   （不要改写、不要截断、不要加解释；Write 前不要先 Read 该文件。）
3. 运行 Bash 命令入库：
   `cd /d/平台/tools/datasource && /d/Anaconda/python ima_content_ingest.py payload/fetch_<doc_id>.txt <doc_id>`
   脚本会截断到 3 万字写入 `documents.content` 并打印 JSON（含 stored_chars）。stored_chars>0 即成功。
4. 每处理完一条就**重写**进度文件 `D:\平台\tools\datasource\progress\shard_%SHARD%.json`：
   `{"shard":%SHARD%,"done":[{"doc_id":0,"stored_chars":0}],"failed":[{"doc_id":0,"reason":""}],"remaining":[0]}`

## 硬性规则
- 只能通过 `ima_content_ingest.py` 改 `documents.content`；禁止 shutil.copy 或直接操作 `D:\平台\database\kaoyan.db`。
- 禁止改表结构、禁止改其他表、禁止 git add。
- **不要**运行 `ima_extract_kp.py`（抽取由主控统一后台跑）。
- fetch 返回空/报错/正文<200 字符 → 记 failed（reason 写清），继续下一条，不要重试卡住。
- 正文极耗上下文：处理一条就落库一次，绝不在上下文里堆积多条正文。
- 感觉上下文快不够时立即停止，先确保进度文件最新。

## 完成标准
分片内 items 全部处理完（或上下文不足而停止），进度文件 `progress\shard_%SHARD%.json` 已落盘。最后用一行 JSON 输出你的结果摘要：
`{"shard":%SHARD%,"done":N,"failed":M,"remaining":K,"doc_ids_done":[...]}`
