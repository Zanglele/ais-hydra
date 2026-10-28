# Svalbard AIS 数据准备

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe experiments\svalbard\prepare_data.py --prepare
```

省略 `--prepare` 只生成检查报告。原始文件始终保留，不会被改写。

## 本次数据检查

- 35,055 条航迹、372 艘船、6,537,024 个点。
- 正常标签 35,039 条，异常标签 16 条，异常比例约 0.0456%。
- 55 条航迹只有一个点；实际文件并非所有航迹都满足介绍页的最短时长。
- 2,364 条航迹存在航向值 360，共 104,738 个这样的点。没有将其擅自当作 0 度；其含义需结合数据说明或来源确认。
- 494 条航迹存在航速 >60 的点，4 条存在约 102.2 的航速值。这些只是复核标记，不作为自动排除条件。
- 初版保守排除 2,419 条结构/范围不合要求的航迹，均为正常标签；16 条异常全部保留。排除并不表示这些航迹应被视为行为异常。
- 16 条异常只涉及两个 MMSI，长度均为 359–361 点，时长 716–720 分钟。长度和船舶身份可能造成混杂，后续应增加长度匹配正常对照和按船分组评价。

## 文件

- `outputs/svalbard/data_summary.json`：汇总统计、排除原因、窗口可用数量。
- `outputs/svalbard/trajectory_inventory.csv`：全部航迹的检查清单。
- `outputs/svalbard/labelled_anomalies.csv`：16 条异常航迹清单。
- `data/svalbard/processed/features.npz`：32,636 条航迹、6,068,075 行五维特征。
- `data/svalbard/processed/metadata.json`：特征定义、单位和边界约定。

## 特征与边界

五维特征依次为局部球面近似计算的东西向速度、南北向速度（米/秒）、原始 SOG（节）、sin(COG)、cos(COG)。前两项由相邻位置和时间差计算，属于球面局部近似，不是椭球精密测地计算。为避免制造首点位移，每条航迹第一点不生成特征。

```python
import numpy as np

z = np.load('data/svalbard/processed/features.npz')
i = 0
start, stop = z['offsets'][i:i + 2]
X = z['features'][start:stop]  # 只取一条航迹
label = z['labels'][i]        # 只用于后续评价
```

`features` 是为高效存储而拼接的矩阵，**禁止将整个矩阵直接输入 HYDRA**，否则窗口会跨越航迹边界。标签、MMSI、航迹编号分别存储，均不属于模型输入。

这里没有额外标准化；原始 HYDRA 会对一次输入的多变量通道逐列标准化，并在集成时按层标准化窗口分数。因此，分别运行不同航迹的结果不能默认直接比较。此文件只是输入适配，尚未解决跨航迹评分校准，也不代表完成了异常检测有效性评价。

后续若用标签选择参数，应先固定验证/测试方案。不能将轨迹标签复制成逐点真值，不应直接使用原始 main.py 的逐点评价指标评价此数据集。
