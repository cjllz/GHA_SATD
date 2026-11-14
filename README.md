# GitHub Actions SATD 数据集

本项目收集 GitHub Actions 工作流 YAML 中表达自承认技术债务（Self-Admitted Technical Debt，SATD）的注释，提供原始候选和复核后的版本，供实证分析使用。

## 数据概况

| 数据版本 | 注释记录 | 仓库 | 工作流 |
|---|---:|---:|---:|
| 原始候选 | **1,046** | **300** | **661** |
| 人工复核确认版 | **876** | **263** | **548** |

数据观察截止日期为 **2026 年 3 月 26 日**；复核确认日期为 **2026 年 11 月 14 日**。文件为 CSV，UTF-8 with BOM。一条记录表示一次注释出现，不一定对应一项独立的技术债务。

## 人工复核确认版

我们对 1,046 条候选结合注释及周围 YAML 判断，人工审核得到 870 条记录。

随后，参考已有 SATD 研究中对关键词命中项与未命中项进行核验开展补充质量检查。固定随机种子进行可复现抽样，检查了 267 条保留记录、全部 176 条排除记录，以及 380 条关键词未命中的注释。两个抽样组的样本量按有限总体、95% 置信水平和 ±5 个百分点的目标误差确定。检查采用人工分析，最终确定876条记录作为最终数据集。
## 文件说明

```text
code/                     数据处理代码与运行说明
dataset/
  satd_comments.csv       1,046 条原始候选注释
  satd_comments_reviewed.csv  870 条人工复核确认版（AI 辅助）
  projects.csv            对应的 300 个仓库及其指标
  README.md               字段说明
  checksums.json          数据文件校验值
```

- [复核后的数据：870 条](dataset/satd_comments_reviewed.csv)
- [原始候选数据：1,046 条](dataset/satd_comments.csv)
- [项目清单](dataset/projects.csv)
- [字段说明](dataset/README.md)
- [代码说明](code/README.md)

候选表包含九个字段：`satd_comment_id`、`name`、`file_hash`、`comment_text`、`normalized_text`、`matched_keywords`、`line_start`、`line_end` 和 `satd_location`。

数据与参考代码的来源、署名和使用许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
