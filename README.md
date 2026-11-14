# GitHub Actions SATD 数据集

本项目收集 GitHub Actions 工作流 YAML 中表达自承认技术债务（Self-Admitted Technical Debt，SATD）的注释，提供原始候选和复核后的版本，供实证分析使用。

## 数据概况

| 数据版本 | 注释记录 | 仓库 | 工作流 |
|---|---:|---:|---:|
| 原始候选 | **1,046** | **300** | **661** |
| 人工复核确认版 | **870** | **263** | **548** |

数据观察截止日期为 **2026 年 3 月 26 日**；复核确认日期为 **2026 年 11 月 14 日**。文件为 CSV，UTF-8 with BOM。一条记录表示一次注释出现，不一定对应一项独立的技术债务。

## 人工复核确认版

复核采用 **AI 辅助上下文初审、研究者确认待定项**：AI 结合注释及周围 YAML 检查全部 1,046 条，初审及进一步上下文检查后保留 793 条、排除 175 条，另有 78 条待确认；研究者随后确认保留其中 77 条、排除 1 条，最终得到 **870 条**。

本版不代表每条记录均由人工独立重新标注，也未进行双人独立标注或关键词未命中评论的漏检抽样。原始候选文件同时保留，两个版本使用相同的九个字段。

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
