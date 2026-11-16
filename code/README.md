# 数据处理代码

入口脚本按 `01 -> 02 -> 03 -> 04` 排列：先确定研究项目，再提取和筛选候选，最后从关键词未命中组抽样。

```text
code/
|-- 01_select_projects.py      # 计算工作流活跃度，筛选并排名 Top 300 项目
|-- 02_extract_candidates.py   # 提取 YAML 注释，匹配 73 个关键词，排除问题文件
|-- 03_select_latest.py        # 关联工作流历史，保留观察截止时的最新状态
|-- 04_sample_nonhit.py        # 对关键词未命中组进行可复现随机抽样
|-- verify_dataset.py          # 校验发布数据
|-- keywords.txt               # 73 个 SATD 关键词
|-- requirements.txt           # Python 依赖
`-- utils/                     # 四个入口调用的实现
```

## 原始输入

```text
external/raw/
|-- repositories.csv
|-- workflows.csv
`-- workflows/                 # 以 file_hash 命名的工作流内容
```

原始输入不随本仓库分发。完整处理使用 Python 3.12，依赖安装命令为：

```sh
python -m pip install -r code/requirements.txt
```

## 01：选择项目

项目选择只读取完整仓库元数据和工作流变更记录，不读取注释或 SATD 候选。

```sh
python code/01_select_projects.py activity \
  --workflows external/raw/workflows.csv \
  --repositories external/raw/repositories.csv \
  --output output/project_selection/workflow_activity_monthly.csv

python code/01_select_projects.py select \
  --repositories external/raw/repositories.csv \
  --activity output/project_selection/workflow_activity_monthly.csv \
  --output output/project_selection/results
```

输出包括全部合格项目、Top 300 项目和项目选择报告。

## 02：提取候选

```sh
python code/02_extract_candidates.py extract \
  --dataset-dir external/raw \
  --output-dir output/candidates \
  --workers 8

python code/02_extract_candidates.py filter \
  --state PATH_TO_STATE_SQLITE \
  --output-dir output/candidates
```

第二条命令中的检查点路径由第一条命令输出。`filter` 会排除读取、编码或解析存在问题的整个文件。

## 03：保留最新状态

```sh
python code/03_select_latest.py link \
  --candidates output/candidates/satd_comments.csv \
  --history external/raw/workflows.csv \
  --state PATH_TO_STATE_SQLITE \
  --output output/history

python code/03_select_latest.py select \
  --versions output/history/workflow_versions.csv.gz \
  --occurrences output/history/satd_occurrences.csv \
  --output output/latest

python code/03_select_latest.py export \
  --input output/latest/latest_satd_comments.csv \
  --output output/latest/satd_comments.csv
```

最新状态按照原始工作流历史顺序确定。已删除、存在问题或历史关系不明确的最新状态不会回退到旧版本。

## 04：抽取未命中样本

```sh
python code/04_sample_nonhit.py \
  --input external/review/nonhit_population.json.gz \
  --output output/nonhit_sample.csv \
  --expected-population 33003
```

脚本采用 95% 置信水平、正负 5 个百分点误差和最保守比例 `p=0.5`，使用有限总体修正计算样本量。默认随机种子为 `20261116`。

## 查看参数

```sh
python code/01_select_projects.py --help
python code/02_extract_candidates.py --help
python code/03_select_latest.py --help
python code/04_sample_nonhit.py --help
```
