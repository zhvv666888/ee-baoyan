# 官方网站采集系统

## 公告到已发布项目

采集器和推荐器之间有明确的审核闸门：

```text
官方列表页 → 候选公告 → notices → 自动字段提取 → program_drafts(pending)
→ /admin/review 人工编辑与审核 → published_programs → published 模式推荐
```

`notices` 保存公告级原始证据和抽取 facts；`program_drafts` 是可编辑草稿，缺失字段保持为空；`review_events` 记录每次保存、审核、驳回、发布和下架；`published_programs` 是推荐器在正式模式下唯一读取的表。raw、extracted、pending、rejected 均不会直接进入推荐结果。

公告入库后会自动尝试创建 draft，也可以在本地管理 API 中显式调用 `POST /api/admin/notices/{notice_id}/draft`。敏感公告不会创建 draft，`draft_generation_log` 会记录跳过原因。

最小本地流程：

```powershell
Copy-Item .env.example .env
python scripts/crawl_official.py --source uestc-sice --since 2023-01-01
uvicorn app.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000/admin/review，核对字段；能从官方材料确认的再补齐，无法确认的保持为空，然后完成审核、发布
# 发布后用 APP_DATA_MODE=published 启动应用
```

本地管理页顶部固定显示：`Local administration interface. Do not expose publicly without authentication.`

爬虫的目标不是自动生成“院校难度”，而是持续采集可追溯的官方证据，供人工审核后进入项目画像。

## 数据流

```text
官方列表页
  → 发现候选公告链接
  → robots.txt 检查与限速请求
  → 正文、日期、附件链接提取
  → 公告类型分类与规则字段抽取
  → SQLite 去重/版本检测
  → review_queue.csv 人工审核
  → 审核后的项目画像数据
```

爬虫采集结果不会自动写入 `programs.csv`。这是故意设计的安全闸门。

## 快速运行

先把 `config/sources.official.json` 中 `user_agent` 的项目地址和联系方式改成真实信息。

```bash
pip install -r requirements.txt
python scripts/crawl_official.py --list-sources
python scripts/crawl_official.py --source uestc-sice --since 2023-01-01
```

输出：

- `data/crawler/notices.sqlite3`：增量数据库；
- `data/crawler/review_queue.csv`：待审核字段；
- `data/crawler/last_run.json`：本次运行摘要；
- `data/crawler/cache/`：24 小时 HTTP 缓存。

全部启用源：

```bash
python scripts/crawl_official.py --since 2023-01-01
```

单独重新导出审核表：

```bash
python scripts/export_crawled_notices.py
```

## 新增学校

可以直接生成一个小规模配置骨架：

```bash
python scripts/scaffold_source.py \
  --source-id seu-radio \
  --school 东南大学 \
  --college 信息科学与工程学院 \
  --url https://radio.seu.edu.cn/mxkstz/list.htm
```

也可以复制 `template-college`，至少填写：

- `source_id`：稳定且唯一；
- `school`、`college`；
- `seed_urls`：学院研究生招生或通知公告列表；
- `allowed_domains`：只允许官方域名；
- `include_keywords` 和 `exclude_keywords`；
- `detail_url_patterns`：详情页 URL 正则；
- 正文、标题和日期 CSS 选择器。

先用较小上限试跑：

```json
"max_list_pages": 1,
"max_notices_per_run": 10
```

确认没有抓到新闻、课程通知等噪声后再扩大。

## 抽取字段

当前规则会尝试抽取：

- 公告日期和数据年份；
- 夏令营、优选计划、预推免、面试名单、优营名单、拟录取等类型；
- 报名截止时间；
- 活动或考核时间；
- 面向年级；
- 四六级明确分数；
- 明确出现的排名百分比；
- 明确招生人数；
- 硕士、直博培养类型；
- 线上、线下或混合形式；
- “申请条件”原文片段。

规则没有匹配到时保持为空，不猜测。

## 隐私与名单

`面试名单 / 优秀营员名单 / 拟录取名单` 会被标为 `privacy_sensitive=true`。

默认原则：

- 保存公告标题、官方 URL、发布日期和原始内容哈希；
- 名单类公告不持久化正文；普通公告会自动脱敏邮箱、电话、群号和证件号；
- 不把姓名、学号、手机号等写进推荐数据；
- 名单附件只作为官方证据链接，默认不持久化个人明细；
- 需要统计人数时，应在临时环境聚合后删除个人明细，并保留统计方法。

## 合规和稳定性

- 始终遵守 `robots.txt`；
- 默认同一主机请求间隔至少 2.5 秒；
- 不绕过验证码、登录、反爬或访问控制；
- 不并发轰炸学校网站；
- 页面异常只隔离单个来源，不影响其他来源；
- 内容哈希变化后自动重新进入审核队列；
- 官方网站才可配置为 A 级证据，搜索引擎摘要不能入库。

## 为什么暂不使用大模型直接抽取

网页结构化规则更便宜、可测试、可复现。后续可以把大模型放在审核辅助层：输出候选字段和原文定位，但不能无来源写入正式画像。

## 扩展队列

`config/source_backlog.csv` 列出了首批 11 所电子信息强校的接入状态。先小规模验证选择器，再将来源切换为 `active`，避免错误分页造成无关抓取。
