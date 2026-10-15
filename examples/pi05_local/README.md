# PI0.5 本地量化推理与 MuJoCo 仿真

已在 WSL Ubuntu 24.04 / RTX 5060 Ti 8GB 上完成 **Meta-World 专用 PI0.5 权重 → NF4 量化 → 离线推理 → MuJoCo 动作反馈 → 录像与评测**。
当前推荐使用下面的专用模型入口。后半部分保留早期 pi05_base 实验记录。

## 实时可视化与训练监控

已接入 Rerun 0.33.1、TensorBoard 2.20.0 和 MuJoCo WSLg 交互窗口。
Windows 项目目录运行：

```powershell
# 启动本地面板并执行 reach-v3、seed 0，可在浏览器实时查看
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\run_visual.ps1
# 同时打开可旋转视角的 MuJoCo 三维窗口（执行期间可见）
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\run_visual.ps1 --viewer
# 换任务或种子
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\run_visual.ps1 --tasks push-v3 --seeds 0
```

打开 [Rerun 推理面板](http://localhost:9090/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A18766%2Fproxy)
和 [TensorBoard 指标](http://localhost:6006)。服务绑定本地地址，运行结束后保留，直到手动停止或 WSL 关闭。
Windows 保留了 9798–9897 端口范围，所以 Rerun 数据端口使用 18766。

Rerun 面板包括：相机画面、实际观测的末端三维轨迹、执行动作、XYZ/夹爪状态、奖励/成功标记、推理耗时、5 步预测动作和去噪中间张量。
底部时间轴可暂停、拖动、逐步回放；如果面板折叠，点击窗口右上角面板按钮展开。
`step=0` 是稳定场景后的初始观察，`step=N` 对应第 N 个动作执行后的观察和奖励；该时刻的预测使用这帧观察。
模型内部 flow 张量为 `[6,5,4]`，表示初始噪声/中间值到最终动作的六个阶段、五个未来动作、四个动作维度；它们不是机器人空间位置。完整 32 维原始数据保存在 NPZ。

每次运行在 `outputs/pi05-metaworld-时间戳/` 下新增：

- `任务-seed编号.rrd`：完整时间轴，可离线加载；将文件拖入本地 Rerun 网页即可回放。
- `任务-seed编号-denoising.npz`：每次预测的去噪中间值及时间。
- `tensorboard/任务-seed编号/`：实际评测奖励、成功标记和推理延迟事件日志。
- 原有 MP4、逐步 JSON 与汇总报告。

窗口模式自动使用 GLFW，普通无窗口模式仍用 EGL。窗口展示独立复制的模型/物理状态，鼠标操作不会改变评测中的机器人。
已修复 MuJoCo 3.8.1 关闭窗口后渲染线程仍存活的问题，关闭环境前等待窗口线程结束。
面板会增加记录和渲染开销；耗时不再是纯无可视化基准，不保证实时控制。

本机验收：浏览器流式记录与 MuJoCo 窗口同时开启，reach-v3 / seed 0 在 96 步成功，
动作输出与原始无可视化结果逐项一致（最大差 0），20 次预测均记录六阶段去噪数据。
动作块推理中位数约 0.263 秒；10 项测试、Rerun 文件完整性检查及训练入口 `--help` 均通过。
Windows 验收文件在 `outputs/pi05-visual-live-final/`，`dashboard-preview.png` 是较早十步窗口测试的面板截图。

```powershell
# 只启动/查询/停止本项目创建的面板服务
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\dashboard.ps1 start
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\dashboard.ps1 status
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\dashboard.ps1 stop
```

WSL 等价命令与文件回放：

```bash
cd ~/workspace/lerobot
bash examples/pi05_local/run_visual.sh --viewer
uv run --no-sync rerun outputs/pi05-visual-validation/reach-v3-seed0.rrd --port auto
# 仅记录，不启动浏览器服务
bash examples/pi05_local/run_metaworld.sh --visualize --tasks reach-v3 --seeds 0
```

训练入口 `train_visual.py` 能将 LeRobot 真正输出的 MetricsTracker（loss、梯度、学习率等）及验证 loss 写入本地 TensorBoard。
使用既有训练配置启动，示例中的配置路径需替换为真实文件，并先准备对应训练依赖和数据集：

```bash
uv run --no-sync python -m examples.pi05_local.train_visual \
  --tensorboard-dir outputs/my-training/tensorboard \
  --config_path=/absolute/path/to/train_config.json --wandb.enable=false
```

这里只部署了训练指标记录适配器并用真实 MetricsTracker 类测试；**未启动 PI0.5 训练，也未完成真实训练任务的端到端验证**。
当前 TensorBoard 展示的是已完成的推理评测，不能当作训练学习曲线。8GB 显卡可运行本例量化推理，不代表能直接运行 PI0.5 全参数训练。

增量依赖安装（保留现有量化环境，不执行基础依赖自动同步）：

```bash
uv pip install rerun-sdk==0.33.1 tensorboard==2.20.0
uv run --no-sync python -m unittest examples.pi05_local.test_runtime examples.pi05_local.test_metaworld_sft examples.pi05_local.test_telemetry examples.pi05_local.test_training_metrics
```

## 专用策略启动（推荐）

Windows PowerShell，在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\run_metaworld.ps1
```

默认运行 reach-v3、push-v3、pick-place-v3，每个任务使用种子 0、1、2。
每次运行保存到 WSL 项目下带时间戳的 `outputs/pi05-metaworld-*` 目录。
单任务快速回放：

```powershell
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\run_metaworld.ps1 --tasks reach-v3 --seeds 0
```

WSL 中的等价入口（可指定新的输出目录，已有评测目录不会被覆盖）：

```bash
cd ~/workspace/lerobot
bash examples/pi05_local/run_metaworld.sh --tasks reach-v3 --seeds 0
# 可选：进程级隔离网络，不影响 Windows/WSL 其他程序
unshare -Urn bash examples/pi05_local/run_metaworld.sh --tasks reach-v3 --seeds 0
```

## 专用策略实测结果

固定三个任务 × 三个种子，15 步零动作稳定场景后，每轮最多执行 160 个策略动作。
每次推理预测 5 个动作、去噪 5 次，然后重新读取相机。使用训练配套的分位数统计还原前四个动作维度，裁剪到环境范围。
相机、图像缩放和提示词按 RLinf/OpenPI 约定；不把状态写入提示词。

| 任务 | seed 0 | seed 1 | seed 2 | 成功数 |
| --- | --- | --- | --- | --- |
| 到达 reach-v3 | 成功，96 步 | 失败，160 步 | 成功，52 步 | 2/3 |
| 推动 push-v3 | 成功，51 步 | 失败，160 步 | 失败，160 步 | 1/3 |
| 抓取放置 pick-place-v3 | 失败，160 步 | 失败，160 步 | 失败，160 步 | 0/3 |

总计 **3/9**，这是小规模本地验收，不是 MT50 基准成绩。抓取放置尚未成功，当前策略不能视为稳定完成三类任务。

- 原始专用权重 7.47 GB；NF4 文件 4.83 GB，仅量化语言骨干的 126 个线性层。
- 峰值 PyTorch CUDA allocated / reserved：**4.72 / 4.94 GiB**，不包含桌面、驱动和渲染上下文。
- 每 5 步动作块推理耗时中位数 **0.243 秒**；MP4 的 20 FPS 只用于回放，不代表实时控制速度。
- 首次量化结果与量化文件重载结果，在 seed 0 的完整 96 步轨迹上输出差为 **0**。
- 用 `unshare -Urn` 隔离网络后再次加载并完成 reach-v3；相同轨迹输出差仍为 **0**。
- 7 项针对性测试通过，包含动作约定、提示词、缓存来源校验和 GPU NF4 数值/序列化测试。
- 尚未比较全精度策略，因此不能把失败归因于量化，也未证明量化无任务精度损失。

报告、全部九段录像和动作轨迹位于 Windows 项目 `outputs/pi05-metaworld-sft/`；
`report.json` 是汇总，`verification.json` 记录重载和隔离网络校验，`preview.png` 展示成功场景。
WSL 原始目录同名。程序采用 EGL 无窗口渲染，通过 MP4 查看；未部署交互式 GUI。

专用模型本地路径：

```text
~/.local/share/lerobot-pi05/pi05-metaworld-sft-nf4/model.safetensors
~/.local/share/lerobot-pi05/pi05-metaworld-sft-nf4/manifest.json
~/.cache/huggingface/hub/models--RLinf--RLinf-Pi05-MetaWorld-SFT/snapshots/60b2d0309af8bb087c9e9b250f8c7f9db50c0f8e/
```

运行还依赖原 base 缓存中的 config.json、专用模型缓存中的 norm_stats.json 和已缓存 tokenizer；无需登录或联网。
来源、固定 revision 和适配依据见 [SOURCES.md](SOURCES.md)。量化文件是本示例格式，使用专用启动器加载。

```bash
uv run --no-sync python -m unittest examples.pi05_local.test_runtime examples.pi05_local.test_metaworld_sft
uv run --no-sync ruff check examples/pi05_local
```

## 早期基础模型实验（保留记录）

以下 pi05_base 未针对 Meta-World 微调，仅验证部署链路，不应替代上面的专用策略入口。

## 启动

PowerShell 在本项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\examples\pi05_local\run.ps1
```

或在 Ubuntu 中：

```bash
cd ~/workspace/lerobot
bash examples/pi05_local/run.sh --steps 100 --output outputs/pi05-local
```

脚本设置 MUJOCO_GL=egl、HF_HUB_OFFLINE=1、TRANSFORMERS_OFFLINE=1。
必须保留启动器中的 uv run --no-sync，否则 uv 自动同步基础依赖时可能移除额外安装的 bitsandbytes。
无窗口渲染生成 MP4 回放；未部署实时 GUI、网络服务或普通 lerobot-rollout 接口。
所有模型、tokenizer、场景资源已缓存，运行不需要登录和网络。

## 量化产物

126 个语言解码器线性层采用 NF4 双重量化，BF16 计算和打包容器。
视觉、动作专家、嵌入和归一化层保持 LeRobot 的 BF16/FP32 配置。
去除动作推理不调用的文本生成输出头，保留 PaliGemma 嵌入所需权重。
逐张量严格检查名称、形状和覆盖；原始模型不修改。

```text
/home/yuxun/.local/share/lerobot-pi05/pi05-nf4/model.safetensors
/home/yuxun/.local/share/lerobot-pi05/pi05-nf4/manifest.json
/home/yuxun/.local/share/lerobot-pi05/paligemma_tokenizer.model
```

量化文件约 **4.83 GB**，原始文件 14.47 GB。
首次没有产物时从原始缓存量化，加 --export 保存；后续自动加载量化文件。
仍需要原始 checkpoint 的 config.json。量化格式为本示例专用，不能直接给普通 lerobot-eval。
未实现 CPU offload，实测当前 GPU 可以完整容纳活动推理权重。

## 验收结果

| 项目 | 实测 |
| --- | --- |
| 来源 | lerobot/pi05_base，revision 22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0 |
| 加载 | 811 个参数张量，严格匹配 |
| 仿真 | Meta-World reach-v3 / MuJoCo 3.8.1 |
| 反馈 | 100 步，10 次重新观测和推理 |
| 配置 | batch=1，chunk=50，10 次去噪；每次执行前 10 个动作 |
| 峰值 CUDA allocated / reserved | 4.72 / 4.95 GiB，不含驱动、桌面、渲染上下文 |
| 热身后动作块预测 | 约 0.30–0.47 秒，不能当作单步控制频率 |
| 首次量化加载 / 产物重载 | 约 10.86 / 1.53 秒，不含 Python 启动 |
| 重载一致性 | 相同 seed 前 20 步动作最大差为 0 |
| 任务成功 | false |

WSL 报告和视频在 ~/workspace/lerobot/outputs/pi05-final/，
重载验证在 outputs/pi05-reloaded/。
Windows 副本在项目 outputs/pi05-local-validation/。
MP4 以 20 FPS 编码供观看，不表示实时控制速度。

## 适配边界

单视角映射到 base camera，另外两路由 PI05 填充并屏蔽。
四维状态裁剪到 [-1,1] 后补零到 32 维，采用 OpenPI 离散状态提示词和公开 SentencePiece tokenizer。
输出取 [0,1,2,6] 并裁剪为 XYZ/夹爪命令。
这些是实验性约定，没有匹配训练集的状态/动作统计，不代表正确的机器人动作语义。
量化序列化一致性已测，未测与全精度模型的端到端精度损失。
需要任务成功率时，应使用匹配 Meta-World 的微调权重和统计，或改用有 PI0.5 微调权重的 LIBERO。

## 重建和测试

```bash
uv sync --locked --extra pi --extra metaworld --extra accelerate-dep
uv pip install bitsandbytes==0.50.2 ruff==0.16.10
uv run --no-sync python -m unittest examples.pi05_local.test_runtime
uv run --no-sync ruff check examples/pi05_local
mkdir -p ~/.local/share/lerobot-pi05
curl -fsSL https://storage.googleapis.com/big_vision/paligemma_tokenizer.model \
  -o ~/.local/share/lerobot-pi05/paligemma_tokenizer.model
```

完整环境版本在验收目录 environment.txt。
Tokenizer 来源为 OpenPI 官方代码使用的公开 Google Big Vision 地址。
SHA256: 8986bb4f423f07f8c7f70d0dbe3526fb2316056c17bae71b1ea975e77a168fc6。
