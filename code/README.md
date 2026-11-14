# 代码入口与外部输入

本仓库只保存最终数据。完整重建需要外部的原始 `repositories.csv`、保持原行序的 `workflows.csv` 和 `workflows/` YAML 内容目录；可从工作流历史数据来源获取对应归档。不要把最终 300 项目的元数据当作全部原始输入。

## 只检查最终数据

Python ≥3.11：

```sh
python code/verify_dataset.py
python -m unittest discover -s code -p "test_*.py"
```

不需要第三方依赖。检查文件行数、字段、项目关联和 SHA-256；不重新构建数据。

## 从原始文件重建

以下命令从仓库根目录执行。`external/raw/`、`external/selection/` 和 `output/` 均为运行者准备或生成的本地目录，不随仓库分发。`external/raw/` 须包含原始 `workflows.csv`、`repositories.csv` 和 `workflows/`。

安装解析依赖，原提取环境为 Python 3.12；提取 PowerShell 注释另需可用的 PowerShell 解析器：

```sh
python -m pip install -r code/internal/requirements-satd.txt
```

### 提取注释、匹配关键词并排除问题文件

```sh
python code/run.py extract --dataset-dir external/raw --output-dir output/extraction --workers 8
python code/run.py export-readable --state PATH_TO_STATE_SQLITE --output-dir output/candidates
```

`PATH_TO_STATE_SQLITE` 替换为提取程序打印的 checkpoint 路径。导出文件 `output/candidates/satd_comments.csv` 是完成整文件质量检查后的候选表。

### 关联工作流历史并选最新状态

```sh
python code/run.py link-history --candidates output/candidates/satd_comments.csv --history external/raw/workflows.csv --state PATH_TO_STATE_SQLITE --output output/history
python code/run.py select-latest --versions output/history/workflow_versions.csv.gz --occurrences output/history/satd_occurrences.csv --output output/latest
python code/run.py export-nine-columns --input output/latest/latest_satd_comments.csv --output external/selection/latest_candidates.csv
```

历史关联脚本默认核对本研究冻结候选表的 SHA-256，防止无意替换输入。若研究不同版本，必须显式指定其 `--expected-sha`，不能把变更后结果当作本版精确复现。

### 统计持续维护并选择项目

将原始仓库元数据复制为 `external/selection/repositories.csv`，然后执行：

```sh
python code/build_activity.py --workflows external/raw/workflows.csv --repositories external/selection/repositories.csv --output external/selection/workflow_activity_monthly.csv
python code/select_projects.py --inputs external/selection --output output/final
```

项目选择程序读取这三份外部表：

| 外部输入 | 用途 |
|---|---|
| latest_candidates.csv | 11,095 条最新候选，九字段 |
| repositories.csv | 仓库年龄、提交数、贡献者、代码量和 stars |
| workflow_activity_monthly.csv | name、month、workflow_commits；未出现的月份计零 |

程序重新执行资格条件、三项百分位排名、等权合成和 Top 300 选择，并与 `dataset/` 的最终表逐字段比较。相同输入应得到 300 个仓库和 1,046 条候选。无需写输出时添加 `--verify-only`。输入不一致或目标目录非空时停止，不覆盖原表。

## 文件职责

| 文件或目录 | 职责 |
|---|---|
| run.py | 将可读命令映射到原实现，传递参数 |
| build_activity.py | 根据提交哈希去重并按 UTC 月份统计工作流变化 |
| select_projects.py | 资格条件、并列平均排名、等权综合分及候选导出 |
| verify_dataset.py | 最终文件检查 |
| internal/scripts/ | YAML 和嵌入脚本注释提取、位置绑定、扫描 |
| internal/config/ | 原研究的 73 个关键词 |
| internal/reference/ | 固定上游实现、词表、许可和来源校验值 |
| internal/postprocess/ | 整文件过滤、历史关联和最新版本选择 |
| internal/tests/ | 提取与历史处理测试 |

查看每个底层命令的参数：`python code/run.py select-latest --help`。使用已安装解析依赖的环境运行底层测试：`python -m pytest code/internal/tests -q`。移动目录未改变底层筛选和匹配算法。
