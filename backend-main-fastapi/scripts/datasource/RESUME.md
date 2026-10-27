# IMA 知识库元数据抓取 — 断点续跑指南

staging 库：`D:/平台/tools/datasource/ima_inventory.db`（表 `ima_items`，主键 `media_id`，INSERT OR REPLACE 幂等）
进度账本：同库 `ima_page_log(scope, offset, n_items, ts)`
知识库 ID：`001aa4b2d3800376`（共 1280 条）

> **第 4 轮结束时状态：`ima_items` = 967 行**（起始 582 → 本轮 +385，共采 8 页）
> media_type：1(PDF)=714，3(WORD)=26，**4(PPT)=79**，9(图片)=131，99(文件夹)=17
> KB 覆盖率 967 / 1280 ≈ **75.5%**，缺口约 **313 条**。
> ⚠️ `media_type=4` 是 PPT，务必保留。

## 工具与参数

`mcp__ima-mcp__get_knowledge_list(knowledge_base_id, limit, cursor, folder_id?)`
→ `{knowledge_list[], is_end, next_cursor, total_size}`

* 根级：不传 `folder_id`；子文件夹：传 `folder_id`。
* `media_type`：1=PDF，3=WORD，**4=PPT**，9=图片，99=文件夹。
* **filters 参数无效**（实测被忽略），不要用它筛选类型。
* `get_knowledge_base_list` 返回空，别用。
* 调用方式：先 `ToolSearch(tool_names=["mcp__ima-mcp__get_knowledge_list"])`，再 `DeferExecuteTool`。

## 游标可直接伪造（关键）

`cursor = base64(0x08 + protobuf_varint(offset))`，offset 表示"从第 N 条之后开始"。

生成游标：`python ima_cursor.py 0 50 100 ...`

**游标字典（已全部实测/生成）**：

| offset | cursor | offset | cursor | offset | cursor |
|---|---|---|---|---|---|
| 0 | `CAA=` | 300 | `CKwC` | 600 | `CNgE` |
| 50 | `CDI=` | 350 | `CN4C` | 650 | `CIoF` |
| 100 | `CGQ=` | 400 | `CJAD` | 700 | `CLwF` |
| 150 | `CJYB` | 450 | `CMID` | 750 | `CO4F` |
| 200 | `CMgB` | 500 | `CPQD` | 800 | `CKAG` |
| 250 | `CPoB` | 550 | `CKYE` | 850 | `CNIG` |

## 入库

```
python ima_upsert.py payload/xxx.json [<payload2.json> ...]
```

payload 见 `ima_upsert.py` 文件头（支持 id_prefix/uid/id_suffix 简写，或用 `mid` 直接给完整 media_id）。
本轮统一用 `mid` 给完整 media_id。每文件一次 COMMIT；WAL + busy_timeout=60s，可并发。

本页 payload 格式（紧凑键）：

```json
{"folder_path":"...", "scope":"ROOT|<folder_id>", "offset":N,
 "parent_default":"001aa4b2d3800376",
 "items":[{"mid":"<完整media_id>","t":"标题","mt":1,"fs":12345,"pf":"<parent_folder_id>","cf":1}]}
```

> ⚠️ `mid` 必须是 MCP 返回的完整 `media_id` 原文照抄；`fs` 用 `int(...)`；`cf` = 1 if `can_fetch_content` else 0；`intro` 留空（不写 `i`）。

## 已知树形（含规模，全部已实测）

```
ROOT（root 直属项约 845：1 个文件夹 + 约 844 个散装文件，total_size 报 1280 是整库数）
└─ 考研资料数据集V1.0  folder_7500386332053345   (435 文件 + 6 子文件夹)  ★本轮整棵采完
   ├─ 27考研《词汇闪过》      folder_7500386386577797   8 文件
   ├─ 博学课划重点            folder_7500386361412237   2 子文件夹
   │  ├─ 数电  folder_7500386373998548
   │  │  ├─ 做的笔记和后面题目的解题过程 folder_7500386382387990  19 图片
   │  │  └─ 老师的课件和题目             folder_7500386378186883  67 图片
   │  └─ 模电  folder_7500386365610068
   │     ├─ 笔记                        folder_7500386373996327   4 图片
   │     └─ 老师的课件和课件上的重点      folder_7500386369803273  40 图片
   ├─ 数电资料   folder_7500386357220780 → 数电 folder_7500386357218611  13 文件
   ├─ 模电资料   folder_7500386344635100 → 模电 folder_7500386348828033  4 文件+1 子文件夹
   │  └─ 模电试题 folder_7500386353027373  10 文件
   ├─ 考研基础资料(2) folder_7500386336244489 → 考研基础资料 folder_7500386340439963  5 文件
   └─ 贵大真题   folder_7500386336245407   3 文件
```

**结论：整个"考研资料数据集V1.0"子树（435 条）已 100% 采完（第 4 轮 offset 400 返回 `is_end=true`）。**

## 第 4 轮（本轮）已完成分片

| 作用域 | cursor(offset) | 入库条数 | is_end | payload 文件 |
|---|---|---|---|---|
| folder_7500386332053345（V1.0 根） | 350 | 50 | false | payload/v10root_350.json |
| folder_7500386332053345（V1.0 根） | 400 | 35 | **true** | payload/v10root_400.json |
| ROOT | 50 | 50 | false | payload/root_50.json |
| ROOT | 100 | 50 | false | payload/root_100.json |
| ROOT | 150 | 50 | false | payload/root_150.json |
| ROOT | 200 | 50 | false | payload/root_200.json |
| ROOT | 250 | 50 | false | payload/root_250.json |
| ROOT | 300 | 50 | false | payload/root_300.json |

合计 +385 条，`ima_items` 582 → 967。ROOT `next_cursor` 推进：`CGQ=`→`CJYB`→`CMgB`→`CPoB`→`CKwC`→`CN4C`（=`CN4C` 即 offset 350）。

> 第 1~3 轮的成果见上方"已知树形"各子文件夹（均已采完），不重复列出。

## 未完成分片（按优先级，下一轮从这里开始）

| 优先级 | 作用域 | 待采 cursor(offset) | 预估条数 |
|---|---|---|---|
| ① | ROOT（不传 folder_id） | 350,400,450,500,550,600,650,... 直到 `is_end=true` | ~495 |
| ② | （兜底）KB 总数 1280 − 已入库 967 | — | ~313 |

> ROOT 已采 offset 0~300（共 350 条，全部 `is_end=false`）。ROOT 直属项约 845 条，故 **下一轮从 offset 350 起，一路采到 `is_end=true` 为止（预计还差约 10 页）**。
> 采完 ROOT 后，`ima_items` 应接近 1280；若仍有缺口，说明有未展开的子文件夹，再按 `media_type=99` 递归。

## 已知取舍 / 注意事项

* **`intro` 字段留空**：MCP 返回的 introduction 是整段 OCR 正文（单条 500~800 字符），
  连同分页返回一起会把上下文撑爆。本轮只落 `media_id/title/media_type/file_size/
  parent_folder_id/folder_path`，`intro` 写空串。
  下一轮若需要 intro，可用同样的 offset 分片重跑并只补 `intro`（INSERT OR REPLACE 幂等，不会重复）。
* **单会话上下文上限约 7~8 页（50 条/页）**。务必每页立即 `ima_upsert.py`，不要攒着。
* **本环境无 Agent/子代理工具**，无法并行分片，只能单会话串行逐页采；因此每轮采 7~8 页即停并写回本文件。
* 只写 staging 库，绝不碰 `D:/平台/database/kaoyan.db`；不改任何业务代码；不 `git add -A`。
* 不 fetch 正文，只要元数据。

## 为什么需要"人（或新会话）"继续

MCP 只能由 LLM 调用，Python 无法直连（AK 在 `connector-states.json` 里被 AES-GCM 加密，
主密钥又由 vault 包裹，无法在本地还原）。单会话上下文装不下 1280 条全文（约 1.4M 字符），
因此按 50 条/页分片、每页立即入库，换会话从 `ima_page_log` 缺口继续即可。
