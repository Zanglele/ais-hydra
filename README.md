# AIS 航迹聚类与 HYDRA 异常检测实验

使用 Svalbard 公开 AIS 数据，探索路线聚类与联合窗口 HYDRA 异常评分。当前输出为离线异常候选，不代表事故、保险赔案或已校准的风险概率。

## 目录

- `HYDRA/`：上游算法子模块，固定源码版本，未修改。
- `data/svalbard/code/`：数据检查、路线聚类、联合窗口评分和测试。
- `data/svalbard/README.md`：参数、输出字段及方法限制。
- `experiments/svalbard/`：前期独立数据检查脚本。
- `data/stocks/`：预留目录，尚未实现股票实验。
- `ENVIRONMENT.md`、`requirements-lock.txt`：环境说明及已安装依赖版本。

## 获取与运行

克隆本仓库时使用 `git clone --recurse-submodules <本仓库地址>`；如果已经普通克隆，可执行 `git submodule update --init --recursive`。

使用 Python 3.11 创建项目虚拟环境，并安装依赖：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

`hnswlib` 在Windows上可能需要C++编译工具。当前机器已配置的环境可直接使用，无需重新安装。

从 https://doi.org/10.11583/dtu.28553462.v3 下载 `formatted_trajectories.json` 和 `df_ships.json`，放到 `data/svalbard/raw/`。原始数据、虚拟环境、处理产物和运行结果不提交到Git。

```powershell
# 小样本
.\.venv\Scripts\python.exe data\svalbard\code\run_pipeline.py --limit 120 --clusters 4 --stride 10

# 全部符合质量与长度条件的航迹
.\.venv\Scripts\python.exe data\svalbard\code\run_pipeline.py --limit 0 --clusters 16 --window 20 --stride 10 --backend hnsw

# 关键检查
.\.venv\Scripts\python.exe data\svalbard\code\test_pipeline.py
```

每次运行在 `data/svalbard/results/` 新建目录。`anomaly_points.csv` 提供候选窗口覆盖点的UTC/北京时间、经纬度及分数；`run_summary.json` 的 `run_status=completed` 表示评分流程完整结束。

## 研究边界

当前方法改变了上游HYDRA的窗口集合和标准化范围，属于扩展实验；不是原论文结果的直接复现。标签仅用于输出附注，尚未完成独立测试集效果评价。类内最高约1%的窗口是复核候选，不是确认异常；轨迹标签不能当作逐点标签。详细规则见AIS模块说明。

上游代码按其自身LICENSE使用，引用算法及数据时请遵循各自的引用与许可要求。
