# 真实官网公告字段准确性评估（2026-07）

## 评估范围

2026-07-23 使用正式 User-Agent 从电子科技大学两个官方域名抓取 11 条公告：信息与通信工程学院 `sice.uestc.edu.cn` 6 条，研究生招生网 `yz.uestc.edu.cn` 5 条。所有详情页 HTTP 状态均为 200，URL 均属于配置的官方允许域名。

## 结果摘要

| 字段/检查项 | 结果 | 结论 |
|---|---:|---|
| 官方 URL 与 HTTP 200 | 11/11 | 通过 |
| 标题存在且内容哈希为 SHA-256 | 11/11 | 通过 |
| `notice_type` 人工复核 | 11/11 | 通过；修正了正文引用“优本计划”导致夏令营误分类的问题 |
| `privacy_sensitive` 人工复核 | 11/11 | 通过；3 条名单/结果公告均被隔离，8 条普通公告未误报 |
| 详细字段复核（16512、16511） | 12/12 | 通过；日期、年级、培养类型、活动形式及可提取时间字段与正文一致 |
| 未在公告中出现的门槛字段 | 7 个 | 保持 `null`/`missing_fields`，不猜测、不当作低门槛 |

## 逐条记录

| 公告 | 类型 | 敏感 | 关键抽取结果/处理 |
|---|---|---|---|
| [16512](https://www.sice.uestc.edu.cn/info/1142/16512.htm) | `summer_camp_notice` | 否 | 2023 级；硕士/直博；线上；报名截止 2026-07-06 10:00；活动 2026-07-07；人工审核后发布 |
| [16511](https://www.sice.uestc.edu.cn/info/1142/16511.htm) | `selection_notice` | 否 | 2023 级；硕士；线上报名+现场考核，标记为 `hybrid` |
| [16565](https://www.sice.uestc.edu.cn/info/1142/16565.htm) | `interview_list` | 是 | 不生成 draft；不持久化名单正文 |
| [16453](https://www.sice.uestc.edu.cn/info/1142/16453.htm) | `proposed_admission_list` | 是 | 不生成 draft；不持久化名单正文 |
| [16313](https://www.sice.uestc.edu.cn/info/1142/16313.htm) | `proposed_admission_list` | 是 | 不生成 draft；不持久化名单正文 |
| [16225](https://www.sice.uestc.edu.cn/info/1142/16225.htm) | `other` | 否 | 导师双选通知；未猜测项目门槛 |
| [5904](https://yz.uestc.edu.cn/info/1081/5904.htm) | `summer_camp_notice` | 否 | 2027 级；直博；提取到 2026-07-24 09:30–11:30 活动时间；营地与线上宣讲并存，活动形式保留人工复核空间 |
| [5886](https://yz.uestc.edu.cn/info/1081/5886.htm) | `summer_camp_notice` | 否 | 全国夏令营通知；硕士/直博；线上 |
| [5884](https://yz.uestc.edu.cn/info/1081/5884.htm) | `summer_camp_notice` | 否 | 2027 级；硕士/直博字段按正文出现的培养类型提取 |
| [5895](https://yz.uestc.edu.cn/info/1081/5895.htm) | `summer_camp_notice` | 否 | 各学院活动汇总；未把汇总页猜成单一项目 |
| [5526](https://yz.uestc.edu.cn/info/1064/5526.htm) | `summer_camp_notice` | 否 | 各学院活动汇总；未猜测学院级门槛 |

## 发布与推荐兼容性

真实项目为 `PUB-000001`，来源为 [16512 官方公告](https://www.sice.uestc.edu.cn/info/1142/16512.htm)。`published_programs` 中只有这一条活跃记录，`is_demo=false`。公告没有给出排名线、英语分数线、项目层次、科研门槛、竞争强度和综合门槛，因此这些字段保持 `null`，`missing_fields_json` 明确记录 7 项缺失。

推荐器可以读取该记录并返回结果，但会将其标记为 `data_complete=false`、`冲刺`，降低置信度并展示“不能视为低门槛”的风险说明；不会将 `null` 转成 0 或放宽筛选。真实学生背景测试返回 1 条该官方项目，`is_demo=false`，来源 URL 可回溯。

## 结论与限制

本次 11 条公告足以验证官网来源、分类、隐私隔离、未知字段处理和发布—推荐兼容性。时间、培养类型和活动形式的字段仍需在更多学校、PDF 附件和跨页面公告上继续人工抽样；当前评估不宣称抽取器对所有官网模板都达到 100% 准确。
