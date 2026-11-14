# 最终数据：1,046 条候选

本目录只有最终候选表、对应项目表及校验值，不包含其他候选版本或中间筛选表。

- [satd_comments.csv](satd_comments.csv)：1,046 行，九个字段。
- [projects.csv](projects.csv)：对应的 300 个仓库及综合排名。
- [checksums.json](checksums.json)：两张表的 SHA-256。

## 候选表九字段

| 字段 | 含义 |
|---|---|
| satd_comment_id | 文件内容版本中某处注释的标识；相同内容被多个工作流使用时可能重复 |
| name | 仓库名称的 JSON 数组，本表每行只关联一个仓库 |
| file_hash | 对应 YAML 内容版本的哈希 |
| comment_text | 注释原文，可能含换行 |
| normalized_text | 正文的小写及空白归一化结果，不用于跨项目合并 |
| matched_keywords | 命中的关键词，JSON 数组 |
| line_start | 原 YAML 起始行号，从 1 开始 |
| line_end | 原 YAML 结束行号，包含此行 |
| satd_location | YAML 树路径，下标从 0 开始；无法确定为 unknown |

一行是候选出现记录，不保证是一项独立且真实的技术债务。相同注释在不同工作流中的出现保留。九字段表不带 workflow uid，不能仅凭文本或 ID 判断债务实体。

## 项目表字段

| 字段 | 含义 |
|---|---|
| rank / name / language | 综合排名 / 仓库名 / 主语言 |
| codelines / age_years / stars | 代码行数 / 截至归档期的年龄 / stars |
| contributors / commits | 累计贡献者数 / 累计提交数 |
| workflow_commits_12m | 指定 12 个月内不同的工作流修改提交数 |
| workflow_max_consecutive_months_12m | 该窗口内最长连续工作流活跃月份数 |
| satd_candidate_count | 此仓库在最终表中的候选数量，不参与排名 |
| size_percentile / age_percentile / stars_percentile | 在 401 个合格仓库中计算的三项百分位分 |
| composite_score | 三项百分位分的等权平均值 |

文件为 UTF-8 with BOM。先用 CSV 解析器读取，再对 JSON 数组字段解析。项目概况见 [仓库首页](../README.md)，运行说明见 [code/README.md](../code/README.md)。
