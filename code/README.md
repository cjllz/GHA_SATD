# 数据处理代码

按 `01 → 02 → 03` 的顺序运行。三个编号文件是入口，具体实现集中在 `utils/`。每个入口包含几个子命令，按下面的顺序执行即可。

```text
code/
├── 01_extract_candidates.py   # 提取注释、关键词匹配、排除问题文件
├── 02_select_latest.py        # 关联历史、选择最新工作流、导出九字段
├── 03_select_projects.py      # 统计活跃度、筛选并排名项目
├── verify_dataset.py         # 校验最终数据
├── keywords.txt              # 原研究的 73 个关键词
├── requirements.txt          # Python 依赖
└── utils/                    # 上述入口实际调用的处理实现和解析工具
```

## 只查看和检查最终数据

仓库中的 `dataset/` 已包含最终 1,046 条候选和 300 个项目。使用 Python ≥3.11 即可校验，无需安装第三方依赖：

```sh
python code/verify_dataset.py
```

此命令检查行数、九个字段、项目关联和文件校验值，不从原始数据重新筛选。

## 重新运行处理流程

以下命令在仓库根目录执行。完整重建需要另外准备原始数据，最终的 300 项目表不能代替全量仓库表。

```text
external/raw/
  repositories.csv    原始全量仓库元数据
  workflows.csv       保持原行序的工作流历史
  workflows/          以 file_hash 命名的 YAML 内容文件
```

原运行环境为 Python 3.12；提取 PowerShell 脚本注释还需要可用的 PowerShell 解析器。安装依赖：

```sh
python -m pip install -r code/requirements.txt
```

### 01：提取候选

```sh
python code/01_extract_candidates.py extract --dataset-dir external/raw --output-dir output/candidates --workers 8
python code/01_extract_candidates.py filter --state PATH_TO_STATE_SQLITE --output-dir output/candidates
```

将 `PATH_TO_STATE_SQLITE` 替换为第一条命令打印的 `checkpoint` 路径。`filter` 使用同一个输出目录读取扫描报告并更新候选文件；必须完成此命令，才能得到排除了问题文件的 `output/candidates/satd_comments.csv`。

### 02：保留最新工作流

```sh
python code/02_select_latest.py link --candidates output/candidates/satd_comments.csv --history external/raw/workflows.csv --state PATH_TO_STATE_SQLITE --output output/history
python code/02_select_latest.py select --versions output/history/workflow_versions.csv.gz --occurrences output/history/satd_occurrences.csv --output output/latest
python code/02_select_latest.py export --input output/latest/latest_satd_comments.csv --output external/selection/latest_candidates.csv
```

这里继续使用同一个 `checkpoint`。最新版本按原始历史记录顺序选择；不会用较旧的有效版本替代被删除或存在问题的最新版本。

`link` 默认核对本研究冻结候选表的 SHA-256。处理其他数据时须显式指定对应的 `--expected-sha`；不同输入的结果不属于本版数据的精确复现。

### 03：选择项目

先将原始全量 `external/raw/repositories.csv` 复制为 `external/selection/repositories.csv`，然后运行：

```sh
python code/03_select_projects.py activity --workflows external/raw/workflows.csv --repositories external/selection/repositories.csv --output external/selection/workflow_activity_monthly.csv
python code/03_select_projects.py select --inputs external/selection --output output/final
```

`select` 读取最新候选、全量仓库元数据和月度工作流活动三张表，执行原有资格条件以及规模、年龄、stars 等权排名，并与 `dataset/` 逐字段比较。相同输入应得到 **300 个项目、1,046 条候选**；输出为 `output/final/projects.csv` 和 `output/final/satd_comments.csv`。只验证而不生成文件时添加 `--verify-only`。

`external/` 和 `output/` 是本地输入、输出目录，不随仓库分发。历史关联、最新选择、最终导出应使用新的输出目录；提取中断后可用 `extract --resume` 续跑同一检查点。目录整理改变了代码指纹，旧代码生成的提取检查点不能用于新代码的 `--resume`。

## 查看参数

每个子命令都支持 `--help`，例如：

```sh
python code/02_select_latest.py select --help
```

本目录只包含实际处理和校验所需的代码。原研究的 Maven 实现请访问上游仓库；来源和许可见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
