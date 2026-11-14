# GitHub Actions SATD 候选数据集

本项目收集 GitHub Actions 工作流 YAML 中可能表达自承认技术债务（Self-Admitted Technical Debt，SATD）的注释，供后续人工标注与实证分析使用。

## 数据概况

| 项目 | 数量或说明 |
|---|---|
| SATD 候选注释记录 | **1,046 条** |
| GitHub 仓库 | **300 个** |
| 包含候选的工作流 | **661 个** |
| 仓库主语言 | **21 种** |
| 数据观察截止日期 | **2026 年 3 月 26 日** |
| 文件格式 | CSV，UTF-8 with BOM |

这些记录是 **SATD 候选**，尚未经过人工语义确认。一条记录表示一次注释出现，不一定对应一项独立的技术债务。

## 文件说明

```text
code/                     数据处理代码与运行说明
dataset/
  satd_comments.csv       1,046 条候选注释
  projects.csv            对应的 300 个仓库及其指标
  README.md               字段说明
  checksums.json          数据文件校验值
```

- [候选注释数据](dataset/satd_comments.csv)
- [项目清单](dataset/projects.csv)
- [字段说明](dataset/README.md)
- [代码说明](code/README.md)

候选表包含九个字段：`satd_comment_id`、`name`、`file_hash`、`comment_text`、`normalized_text`、`matched_keywords`、`line_start`、`line_end` 和 `satd_location`。

数据与参考代码的来源、署名和使用许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
