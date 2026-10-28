# AIS 航迹聚类 + HYDRA 异常候选记录

新入口统一放在本目录，现有 `experiments/svalbard/` 为前期检查脚本，不是新流程的依赖。上游 `HYDRA/` 源码未修改。

## 运行

在项目根目录 PowerShell 中：

```powershell
# 只检查数据并生成特征文件（可选，不是下一条命令的前置条件）
.\.venv\Scripts\python.exe data\svalbard\code\preprocessing.py --prepare

# 默认：不看标签随机抽取200条，8类，20点窗口，步长5
.\.venv\Scripts\python.exe data\svalbard\code\run_pipeline.py

# 更小的试运行
.\.venv\Scripts\python.exe data\svalbard\code\run_pipeline.py --limit 120 --clusters 4 --stride 10

# 全量实验示例：耗时和内存明显增加，建议先检查小样本结果及聚类地图
.\.venv\Scripts\python.exe data\svalbard\code\run_pipeline.py --limit 0 --clusters 16 --window 20 --stride 10 --backend hnsw

# 仅检查全量分组窗口数量，不执行HYDRA评分
.\.venv\Scripts\python.exe data\svalbard\code\run_pipeline.py --limit 0 --clusters 16 --window 20 --stride 10 --backend hnsw --plan-only

# 不聚类的对照：使用同样的limit、seed、window和stride，将所有轨迹放一个组
.\.venv\Scripts\python.exe data\svalbard\code\run_pipeline.py --clusters 1
```

可选的独立预处理报告保存到 `reports/`，特征保存到 `processed/`。聚类检测入口会自行读取原始数据，记录本次质量检查，并将所有本次结果放在 `results/`。

默认每次在 `results/` 创建 UTC 时间命名的新目录。`--output` 可以指定一个不存在的目录；已存在则拒绝覆盖。内存保护默认每类不超过200,000窗口，超出会明确停止，可调整步长、类数、样本数量或显式提高限制。即使limit较小，仍会读取和检查完整原始JSON，需一定内存。

## 数据质量

原始数据不变。单点轨迹、非有限值、字段长度不一致、时间间隔异常、坐标或航向范围不合要求的轨迹暂不参与模型分析，记录到数据质量表。航向360的含义尚未确认，暂不当作0度；这是一项保守处理规则，正式评价需要复核。

航速>60和约102.2仅标记复核，不自动排除。对模型来说，数值疑点也可能导致高异常分，因此候选记录需要结合质量标记复核。质量问题与航行行为异常不是同一概念。

## 方法及扩展范围

1. 每条航迹按路程进度采样16个位置，转换为地心坐标后展平，使用MiniBatchKMeans聚类。保留绝对位置和行进方向，不按MMSI聚类。初版不按船型分别建模，输出保留船型方便分析。这只是路线相似性的近似，固定K会强制分组，采样可能漏掉局部绕行，需检查聚类是否合理。
2. 五维运动输入：东西/南北向速度、SOG、sin(COG)、cos(COG)。位置差分丢弃首点，与预处理说明一致。
3. 类内共同估计通道均值/标准差，再对每条航迹独立提取窗口。窗口不会跨航迹；原始0基点索引和UTC时间用于回溯。
4. 将类内窗口共同交给上游HYDRA的层次压缩函数，复用其层级近邻分数及最大z分数集成。没有对拼接的假连续序列调用原始入口。这改变了原始算法的输入窗口集合和标准化范围，属于**联合窗口HYDRA扩展**，不能称为原始算法直接复现。
5. 默认将类内高于99%分位数的窗口记录为异常候选（严格大于，因此平分可能少于1%）；同时保存所有窗口分数。99%是人工复核预算，不是估计出的真实异常率，也不保证检测到那16条标注异常。不同类的原始分数不能直接全局排名。

## 输出

| 文件 | 内容 |
|---|---|
| `config.json` | 本次参数 |
| `data_quality.csv` | 全量数据质量清单 |
| `data_quality_flags.csv` | 需要复核的原始数据问题 |
| `cluster_membership.csv` | 样本航迹、MMSI、船型、类别、真实轨迹标签 |
| `route_clusters.npz` | 路线描述、类中心、类别与航迹编号 |
| `cluster_N_scores.npz` | 第N类的全部窗口分数、标记、类内百分位、窗口起点、所属轨迹索引、通道缩放参数 |
| `anomaly_candidates.csv` | 高分窗口的位置索引、UTC起止时间、分数、阈值及所属航迹 |
| `anomaly_points.csv` | 候选窗口覆盖的原始点：UTC/北京时间、经纬度、航速、航向、所属航迹、覆盖窗口最高分 |
| `trajectory_scores.csv` | 各航迹最高分、最高10%窗口均分、候选窗口数和比例 |
| `cluster_summary.csv` | 每类的样本量、窗口数、阈值、实际检索后端 |
| `run_summary.json` | 本次汇总和方法限制 |
| `execution_plan.csv` | 每类窗口数、窗口矩阵大小（不含其他内存开销）、是否满足窗口数量限制 |

## 时间与经纬度结果表

可直接使用Excel打开UTF-8 BOM编码的CSV。`anomaly_candidates.csv`一行是一个高分窗口，新增了起点/终点纬度和经度；`anomaly_points.csv`一行是一个被高分窗口覆盖的原始数据点，包含：

| 字段 | 含义 |
|---|---|
| `trajectory_id` / `mmsi` | 航迹编号、船舶编号 |
| `time_utc` | 原始数据使用的UTC时间，`+00:00` |
| `time_beijing` | 转换后的北京时间，`+08:00` |
| `latitude` / `longitude` | 原始纬度、经度（度），不是聚类中心或插值路线坐标 |
| `original_point_index` | 原始航迹中的0基点索引 |
| `max_covering_window_score` | 覆盖该点的候选窗口中最高的分数，并非独立逐点模型评分 |
| `covering_candidate_windows` | 覆盖该点的候选窗口数量 |
| `true_trajectory_label` | 原始整条航迹标签，不表示这个点是真异常 |

同一航迹的重叠候选窗口覆盖同一个点时只输出一行；不同航迹不合并。候选窗口覆盖的点不是逐点确认异常。首个位置只用于位移计算，不自动列入窗口覆盖点。

`--limit 0`表示不随机抽样，仍应用数据质量和最短窗口规则。20点窗口的配置会排除不足20行特征的短航迹；完整原始数据不被修改，排除数量在`run_summary.json`中列明。步长10表示每隔约20分钟取一个窗口，并额外保留每条航迹的最后窗口；不是逐个可能窗口全覆盖。

全量入口也可运行 `powershell -File data\svalbard\run_full.ps1`。若本机执行策略阻止脚本，使用前面的Python命令即可，不需要修改执行策略。运行成功后以控制台最后打印的`Results:`路径为准，且目录内应有`run_summary.json`、`run_status=completed`；中途出错的目录可能只包含部分表格，不应当作全量完成结果。

`owner_indices` 对应 `cluster_membership.csv` 的0基行号；`feature_start_indices` 对应丢弃首点后的特征数组。窗口原始起点=feature_start+1，原始终点=feature_start+window，原始索引均为0基。窗口时间覆盖window-1个采样间隔，位移特征还依赖窗口起点之前的一个原始点。

## 如何解释

- 当前是离线探索，全批次数据参与聚类、缩放、阈值计算，不是实时预测或独立测试。
- 抽样不读取标签，200条随机样本可能不包含任何人工标注异常。不会为了展示效果强行加入异常。
- 真实标签只在结果中附注；没有用于聚类、分数或阈值。标签属于整条航迹，不能评价哪个具体窗口真的异常。
- 相邻重叠窗口未设置时间排除区，保留原始实现的这种特性；多个候选窗口可能属于同一次行为，不能当作多个独立事件。
- 这里不推断天气、事故或其他原因，也不自动计算会误导的逐点准确率。
- 聚类后检测不一定比原始方法更好：聚类可能把异常模式吸收为一类。下一阶段应在固定样本上做有/无聚类对照，再设计按船和时间分组的正式评价。

## 已完成的试运行

`results/smoke_120/` 使用seed=42、120条随机航迹、4类、20点窗口、步长10。共2,561个窗口，记录28个候选窗口。抽样中人工异常标签为0，因此这只是流程验证，不能报告已知异常检出率。候选不是已确认的异常。

窗口边界、与单序列上游集成分数一致性、位置/方向描述三个检查可运行：

```powershell
.\.venv\Scripts\python.exe data\svalbard\code\test_pipeline.py
```
