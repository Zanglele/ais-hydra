# HYDRA 项目环境

独立环境位于项目根目录 `.venv`，基础 Python 3.11.9 位于 `.tools/python311/tools`。移动项目后应重建环境。

在项目根目录使用 PowerShell：

```powershell
.\.venv\Scripts\python.exe --version
Set-Location HYDRA
..\.venv\Scripts\python.exe -m HYDRA.main
```

无需激活即可使用上述解释器。也可以运行 `.\.venv\Scripts\Activate.ps1` 激活环境；若本机执行策略禁止激活，直接使用解释器路径即可。

依赖以 `HYDRA/requirements.txt` 为基础。仓库根目录没有 `setup.py` 或 `pyproject.toml`，因此不执行 README 中的 `pip install -e .`；从仓库根目录通过 `python -m HYDRA.main` 运行。

`hnswlib` 为可选近似检索后端；未安装时核心代码自动使用 scikit-learn 后端。两种后端的性能和结果可能不同，应在实验记录中注明。

## 本次配置与验证

- Python 3.11.9，NumPy 1.26.4，PyTorch 2.3.0（CPU），hnswlib 0.8.0。
- 已按原始 requirements.txt 安装全部依赖，并补装 hnswlib。
- `python -m pip check` 通过。
- 官方 `python -m HYDRA.main` 在自带 NAB 数据上成功运行：AUC-PR 约 0.8535，AUC-ROC 约 0.9568。此结果只验证安装和运行，不代表 AIS 数据效果或完整复现论文。
- 完整安装版本保存在根目录 `requirements-lock.txt`。重建 Python 3.11 环境后，可使用 `python -m pip install -r requirements-lock.txt` 安装。
