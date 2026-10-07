# SO-101 中文 Wiki：电机排错、夹爪测试、关节校准与相机配置

本文整理本次 macOS + LeRobot + SO-101 实机调试过程。命令从仓库根目录执行，适用于已安装 LeRobot 和 Feetech 依赖的环境。

当前进度：已验证电机通信、完成一次夹爪小幅往返测试；用户已确认完成关节校准与相机配置。此前相机索引 1 的短时读帧检查通过，报告 1920×1080、约 15 FPS，尚无长时间稳定性测试记录。此次协作没有录制训练数据集、训练模型或运行模型推理；后文的录制、训练和推理命令均为后续操作模板，没有实际执行。

## 1. 当前设备与操作顺序

本次使用的串口：

```text
/dev/cu.wchusbserial5CE51155781
```

对应的 `/dev/tty.wchusbserial5CE51155781` 也已验证可以通信。在 macOS 上，本文使用 `cu` 设备路径；它们对应同一块串口板，不能作为两条独立机械臂使用。

推荐顺序：确认主臂/从臂与串口 → 必要时设置电机编号 → 校准关节 → 测试夹爪 → 配置相机 → 遥操作与录制。

| 操作 | 接线要求 | 用途 |
| --- | --- | --- |
| `lerobot-setup-motors` | 每次只连接一个电机 | 设置电机 ID 和波特率 |
| `lerobot-calibrate` | 六个电机正常串联 | 设置关节零点和运动范围 |
| 夹爪测试脚本 | 整臂串联，ID 6 是夹爪 | 小幅往返验证通信和运动 |
| 相机检测 | 相机连接到电脑 | 检查索引、画面和分辨率 |

### 主臂与从臂不能混淆

- `so101_leader`：用手操作、向从臂提供动作的主臂，命令使用 `--teleop.*`。
- `so101_follower`：执行动作的从臂，命令使用 `--robot.*`。

本次同一个串口先后被用于 leader 和 follower 命令，但读取 STS3215 型号和电机 ID 不能确定它是哪一种实体机械臂。执行前按实际连接的机械臂选择类型；不要给同一条实体臂混用两套校准配置。

## 2. 电机编号与初始化

SO-101 的默认编号如下：

| ID | 名称 | 关节 |
| --- | --- | --- |
| 1 | `shoulder_pan` | 底座左右转动 |
| 2 | `shoulder_lift` | 大臂俯仰 |
| 3 | `elbow_flex` | 肘部弯曲、伸展 |
| 4 | `wrist_flex` | 手腕俯仰 |
| 5 | `wrist_roll` | 手腕轴向旋转 |
| 6 | `gripper` | 夹爪 |

### 报错：找不到 gripper

```text
RuntimeError: Motor 'gripper' (model 'sts3215') was not found. Make sure it is connected.
```

这表示扫描未得到可用的电机型号，不一定是串口不存在，也不一定需要修改代码。

本次只读探测发现：

- 在 1 Mbps 下，ID 1～6 均能单独回复，型号号为 777，即 STS3215。
- 广播 Ping 返回 `Incorrect status packet!`，其他被扫描的波特率没有响应。
- `tty` 和 `cu` 路径表现相同，切换路径没有消除广播错误。
- 当前总线上有多个电机响应，不满足初始化工具“只接一个电机”的要求。广播损坏的具体电气或协议原因没有进一步确认。

如果机械臂已由厂家配置好，并确认 ID 与实际关节符合上表，可以跳过初始化。仅检测到 ID 1～6 还不能证明物理关节对应关系正确。

如果必须重新设置编号：

1. 断电后，把控制板直接接到 gripper 电机。
2. 断开 gripper 与其他电机的串联线，确保总线上只有一个电机。
3. 恢复匹配电压的外接供电和 USB 连接，运行对应命令。
4. 按终端提示逐个更换电机，每次只有被指定的电机连接总线。
5. 全部完成后，断电并恢复整臂串联。

主臂初始化：

```bash
lerobot-setup-motors \
  --teleop.type=so101_leader \
  --teleop.port=/dev/cu.wchusbserial5CE51155781
```

从臂初始化：

```bash
lerobot-setup-motors \
  --robot.type=so101_follower \
  --robot.port=/dev/cu.wchusbserial5CE51155781
```

如果只接一个电机仍扫描不到，检查外接电源、三芯线、USB 和实际端口。USB 板被识别不代表舵机已获得供电。电源电压应匹配电机规格；如果使用 Waveshare 控制板，按官方说明检查两个跳帽是否位于 B（USB）通道。

## 3. 夹爪小幅开合测试

已保存的手动测试脚本：[tests/motors/manual_gripper.py](../tests/motors/manual_gripper.py)。脚本默认端口已设置为 `/dev/cu.wchusbserial5CE51155781`，不会被 pytest 自动收集执行。

在现有 Conda 环境下运行：

```bash
conda activate lerobot
python tests/motors/manual_gripper.py
```

如果使用已安装 Feetech 依赖的项目 uv 环境：

```bash
uv run python tests/motors/manual_gripper.py
```

需要覆盖端口时添加 `--port`：

```bash
python tests/motors/manual_gripper.py --port /dev/cu.wchusbserial5CE51155781
```

脚本只操作 ID 6，要求电机处于位置模式、扭矩已关闭、状态无错误，并有有效且符合实际机械结构的限位。执行前移开夹爪内的物品和手指。

测试行为：

- 向可用空间较大的一侧移动 200 个编码器刻度，约 18°，然后返回起点附近。
- 临时将速度设为 100、加速度设为 10，扭矩限制取原值与 150 中较小者（寄存器满量程为 1000）。
- 监测位置、负载、状态和温度；单段运动最多等待 6 秒。
- 退出时尝试关闭扭矩，恢复原扭矩限制、速度和加速度，然后关闭串口。通信中断时不能保证清理写入成功。

这是小幅往返测试，不是完全张开/闭合测试，也不用于设置电机 ID 或校准关节范围。

本次实测记录：目标 `1573 → 1773 → 1573`，两段到达时实测位置分别为 1760 和 1587，退出时扭矩为 0。脚本允许 15 个刻度的位置误差，因此返回位置不要求与起点完全相等。这些是当时的记录，重新校准后不能把旧位置数字直接作为动作目标。

## 4. 实际校准机械臂

### 4.1 准备并启动

固定底座，六个电机保持串联，接好匹配的电源和 USB，关闭其他占用串口的程序。校准会关闭扭矩，请扶稳机械臂，避免其因重力落下。

从臂命令：

```bash
lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port=/dev/cu.wchusbserial5CE51155781 \
  --robot.id=my_awesome_follower_arm
```

如果实际连接的是主臂，改用：

```bash
lerobot-calibrate \
  --teleop.type=so101_leader \
  --teleop.port=/dev/cu.wchusbserial5CE51155781 \
  --teleop.id=my_leader
```

`--robot.id` / `--teleop.id` 是机械臂校准配置名称，不是舵机编号。之后遥操作、录制时应使用相同的设备类型和配置名称。

如果提示已有校准文件：输入 `c` 再回车才会重新校准；直接回车会复用旧文件。

### 4.2 摆好中间姿态

看到以下提示时：

```text
Move ... to the middle of its range of motion (shown above) and press ENTER....
```

按终端示意图摆放：底座朝向运动范围中间，大臂大致竖直，小臂大致水平，手腕和夹爪处于中间姿态。不要把关节放在端点。

摆好并扶稳后，只按一次 Enter。程序设置零点偏移，使此时的位置读数接近 2047。

参考：[官方 SO-101 校准视频](https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/lerobot/calibrate_so101_2.mp4)。

### 4.3 表格出现后手动扫过范围

```text
Recording positions. Press ENTER to stop...
NAME            |    MIN |    POS |    MAX
```

此时程序已经开始记录，**不要立即回车，也不要等待电机自动运动**。需要你手动逐个移动：

1. `shoulder_pan`：底座左右转到允许范围两端。
2. `shoulder_lift`：大臂前后俯仰到两端。
3. `elbow_flex`：肘部弯曲、伸展到两端。
4. `wrist_flex`：手腕上下俯仰到两端。
5. `gripper`：完全张开并轻轻闭合。

动作要缓慢，到机械允许的边界即可，不硬顶限位，不拉扯线缆。观察对应行 `POS` 是否变化，`MIN`、`MAX` 是否扩大。只动一点虽然可能通过检查，但不能得到有效的完整运动范围。

当前版本不要求扫描 `wrist_roll`；代码会把它的范围设为 0～4095。

五个关节都完成后，才按 Enter 结束记录。不是每移动完一个关节就按一次 Enter。

### 4.4 确认保存

看到以下输出才算本次校准完成：

```text
Calibration saved to .../my_awesome_follower_arm.json
```

实际保存位置以终端输出为准，可受校准目录配置和环境变量影响。之后使用同一个 `--robot.id`，即可找到对应文件。

## 5. 报错：Some motors have the same min and max values

本次出现过：

```text
shoulder_pan    |   2047 |   2048 |   2049
shoulder_lift   |   2047 |   2047 |   2047
elbow_flex      |   2047 |   2047 |   2047
wrist_flex      |   2047 |   2047 |   2047
gripper         |   2047 |   2047 |   2047

ValueError: Some motors have the same min and max values:
['shoulder_lift', 'elbow_flex', 'wrist_flex', 'gripper']
```

含义：记录期间这些关节没有采集到位置变化，程序拒绝保存零宽度的范围。2047 本身是设置零点后的正常值；底座只有 2 个刻度的变化也不足以代表有效扫描。

失败后只读检查表明六个电机均可通信，扭矩为 0，状态码为 0。没有证据表明该报错由扭矩未关闭引起。

处理步骤：

1. 重跑校准命令，有旧文件时输入 `c`。
2. 中间姿态确认后，等表格出现再移动关节，避免连续按 Enter 提前结束。
3. 确认每个必需关节都记录了实际运动范围，再结束。
4. 如果手动移动后数字仍不变，检查是否连接、移动了同一条机械臂，以及 ID 与关节的对应关系，再排查反馈读取。
5. 如果关节掰不动，不要强掰，应进一步检查机械结构和扭矩状态。

失败发生在保存前，不代表生成了新校准文件；零点偏移可能已经写入电机。完成重新校准前，不应依赖旧位置数字运行夹爪测试或其他动作。

## 6. 相机检测与是否需要标定

### 6.1 本次检测结果

| 相机索引 | 读帧结果 | 报告分辨率 | 报告帧率 |
| --- | --- | --- | --- |
| 0 | 可以打开，但单次读帧失败 | 1920×1080 | 1 FPS |
| 1 | 成功读取一帧 | 1920×1080 | 15 FPS |

当前使用索引 1（1920×1080、约 15 FPS）。这些是短时探测结果，不代表长时间录制稳定性；索引 0 也不能据此认定损坏。索引可能因插拔或设备变化而改变，使用前应查看画面，确认是哪一台物理相机。

检测并保存预览图：

```bash
lerobot-find-cameras opencv \
  --output-dir outputs/captured_images \
  --record-time-s 2
```

macOS 若提示相机访问未授权，在系统设置的“隐私与安全性 → 相机”中允许运行命令的应用访问，或者接受系统弹窗后重新执行。

索引 1 对应的相机参数片段如下，可用于支持 `--robot.cameras` 的录制、遥操作命令；它本身不是完整命令：

```bash
--robot.cameras="{front: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}}"
```

正式录制前应验证所选分辨率和帧率能稳定工作，再按训练需求选择参数。

### 6.2 用 LeRobot 模仿学习通常不必先标定相机

如果流程是录制示范、训练 ACT / SmolVLA，再从图像预测动作，通常不需要显式的相机内参或手眼标定。先完成机械臂关节校准，保证画面可用即可。

录制和部署时保持相机位置、朝向、分辨率、裁剪方式及预处理一致。对于腕部相机，要保持它相对机械臂的安装关系固定。

| 任务 | 通常需要的相机标定 |
| --- | --- |
| 普通 RGB 模仿学习 | 通常不要求显式几何标定 |
| 镜头畸变校正、几何测量 | 相机内参和畸变参数；测量还需相应尺度或几何约束 |
| 把图像目标转换为机器人抓取坐标 | 内参、深度或平面等几何信息，以及相机与机器人间的坐标变换 |
| 腕部相机与末端坐标对齐 | 手眼标定 |
| 双目估计深度 | 两台相机内参、畸变与相对外参 |

仓库当前没有现成的棋盘格/ChArUco 内参标定命令。需要内参标定时，应先确定相机、采集分辨率、标定板类型与尺寸，再采集不同位置、距离和倾角的图像求解并检查重投影误差。手眼标定还需要对应的机器人位姿。

**`lerobot-calibrate` 用于机械臂关节校准，不会标定相机。本次已完成机械臂关节校准，并完成相机访问与读帧配置确认；没有生成相机内参或手眼标定结果，因为当前 RGB 模仿学习流程通常不要求它们。**

## 7. 从安装到训练的完整实践流程

本节吸收本地剪藏文章《[LeRobot SO-101 机械臂实践](https://blog.xiadengma.com/posts/lerobot-so-101-%E6%9C%BA%E6%A2%B0%E8%87%82%E5%AE%9E%E8%B7%B5/)》中的硬件连接、数据录制、ACT 训练和推理经验，并按当前仓库代码（当前检出版本 `ca69a206`）改写命令。剪藏文章记录的是 2025 年版本；LeRobot CLI 变化很快，遇到参数不识别时应以当前 `--help` 和仓库代码为准。

### 7.1 成品机械臂的硬件注意事项

成品 WOWROBO / SO-ARM101 通常已经完成舵机 ID、波特率和出厂中位设置。确认成品说明书后，优先从校准开始，不要为了“重新初始化”而随意运行 `lerobot-setup-motors`。只有在明确需要重设参数时，才按本文第 2 节的单电机接线流程操作。

剪藏文章给出的成品供电示例是：主臂 5 V / 6 A，从臂 12 V / 8 A。实际电压必须以你的电机和电源铭牌为准，不要把不同版本的电源互换。电源不足、线缆接触不良或电压错误，会表现为舵机掉线、灯闪烁、通信超时或运动中断。

第一次遥操作时，要逐个观察六个关节的运动方向，尤其注意从臂的 3 号舵机。方向相反时立即按 `Ctrl+C`，重新检查主臂/从臂类型、校准文件和 `drive_mode`，不要让舵机持续顶住机械限位。建议最大负载约 400 g 只是成品说明中的参考值；应以具体型号说明书和机械结构为准，避免超载。

相机尽量直接连接电脑，机械臂控制板可以使用可靠的 USB 集线器。腕部相机线缆要留出随关节运动的余量，用扎带固定在不会被拉扯的位置；文章中一次录制中断就是由腕部相机连接处受力导致的。

### 7.2 当前版本的安装环境

当前仓库 `pyproject.toml` 要求 Python **3.12 或更高版本**。剪藏文章使用 Python 3.10 的命令只适用于当时版本，不能直接套用。

推荐使用 uv：

```bash
uv sync --locked --extra core_scripts --extra feetech
```

需要训练 ACT 再加入训练依赖：

```bash
uv sync --locked --extra core_scripts --extra feetech --extra training
```

或者使用 Conda 环境，但要保证 `python --version` 满足当前项目要求，并安装系统或 Conda 的 `ffmpeg`。安装后从仓库根目录运行 `uv run ...` 或已激活环境中的同名 CLI，避免调用到另一个环境里的旧版 `lerobot`。

检查实际命令来源：

```bash
which lerobot-calibrate
which lerobot-record
python --version
git rev-parse --short HEAD
```

升级仓库前先保存本地改动：

```bash
git status
git stash push -m "before-lerobot-update"
git pull --ff-only
git stash pop
```

如果 `stash pop` 产生冲突，先解决冲突并运行必要的检查，再继续操作机械臂。

### 7.3 查找端口与固定设备名称

拔掉一块控制板，运行 `lerobot-find-port`，按提示重新插入；分别记录主臂和从臂的串口。macOS 常见路径是 `/dev/cu.*` 或 `/dev/tty.*`，Linux 常见路径是 `/dev/ttyACM*`。一次只连接要识别的控制板，避免把两条串口弄混。

Linux 如果遇到权限错误，临时处理方式是：

```bash
sudo chmod 666 /dev/ttyACM0
```

长期使用应把用户加入设备所属组（常见为 `dialout` 或 `uucp`），再重新登录。macOS 不需要 `chmod 666`；如果应用无法访问 USB 或相机，应在系统隐私设置中授权终端、Python 或 IDE。

Linux 可以按 USB 序列号创建稳定的 udev 别名，例如 `/dev/leader_arm` 和 `/dev/follower_arm`。规则中的序列号必须从本机 `udevadm info` 查询，不能照抄文章示例。macOS 不使用 udev，应使用当前系统生成的 `/dev/cu.*` 路径或自行建立稳定的设备管理方案。

### 7.4 先做无相机遥操作

完成主臂和从臂校准后，先不接相机验证动作方向：

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/follower_arm \
  --robot.id=my_follower_arm \
  --teleop.type=so101_leader \
  --teleop.port=/dev/leader_arm \
  --teleop.id=my_leader_arm \
  --display_data=false
```

把 `/dev/follower_arm`、`/dev/leader_arm` 换成实际串口。用手缓慢移动主臂，确认从臂每个关节方向、夹爪方向和运动范围都正确。按 `Ctrl+C` 停止。若动作方向异常，先停机处理校准和机械连接，不要进入数据录制。

需要查看相机时，在 `--robot.cameras` 中加入相机配置并开启 `--display_data=true`。当前仓库支持 Rerun；也可以使用 `--display_mode=foxglove` 并连接 Foxglove 的 WebSocket。

### 7.5 录制前的相机验证

先列出并保存预览图：

```bash
lerobot-find-cameras opencv \
  --output-dir ./outputs/captured_images \
  --record-time-s 2
```

预览图比只看索引更可靠：确认画面确实覆盖操作区域，物体在整个动作中不会离开画面，腕部相机不会被夹具或线缆遮挡。文章中的 Linux 示例使用 `/dev/video0`、`/dev/video2` 等路径；macOS 通常使用整数索引，不能直接照抄。

当前探测到本机索引 1 可以读帧，报告 1920×1080、约 15 FPS。若使用它，可先从下面的配置开始，再按实际稳定帧率调整：

```bash
--robot.cameras="{front: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}}"
```

录制时降低到 640×480 可以减少编码和存储压力，但必须重新用 `lerobot-find-cameras` 或实际打开测试确认该分辨率与帧率被相机接受。相机 FPS、数据集 FPS 和控制循环 FPS 不一致时，优先保证相机能稳定持续读帧。

### 7.6 用 `lerobot-record` 录制数据集

当前正式 CLI 是 `lerobot-record`。下面是一个 5 回合本地测试模板；将两条串口、相机索引、任务描述和本地目录换成实际值：

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/follower_arm \
  --robot.id=my_follower_arm \
  --robot.cameras="{front: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}}" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/leader_arm \
  --teleop.id=my_leader_arm \
  --dataset.repo_id=my-so101-test \
  --dataset.root=./data/datasets/my-so101-test \
  --dataset.no_stamp=true \
  --dataset.num_episodes=5 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=10 \
  --dataset.single_task="把红色玩偶放进纸箱" \
  --dataset.push_to_hub=false \
  --display_data=true
```

如果准备上传 Hugging Face Hub，先 `hf auth login`，再去掉 `--dataset.push_to_hub=false`，并把 `repo_id` 改成 `用户名/数据集名`。`--dataset.no_stamp=true` 用于让本地目录和 repo ID 保持固定；默认配置可能给 repo ID 添加时间戳，适合避免覆盖但不便于手动续录。

每个回合的实际操作是：等待录制提示 → 用主臂完成任务 → 将环境恢复到下一回合的初始状态。键盘控制为：

| 按键 | 作用 |
| --- | --- |
| 右箭头 | 当前回合提前结束并保存 |
| 左箭头 | 丢弃当前回合并重新录制 |
| `Esc` | 停止整个录制会话，保留已完成回合 |

先录制 5 回合并检查质量，再扩大到 50～100 回合。每个回合的起始物体位置、抓取路径和完成速度应保持基本一致；随后逐步增加物体位置、光照和摆放变化。文章建议至少 50 组数据、多个物体位置，这适合作为起始经验，不是所有任务的硬性门槛。

### 7.7 录制中断与续录

当前 `lerobot-record` 支持 `--resume=true`。相机超时通常先检查 USB 线是否被腕部运动拉扯、相机是否仍被系统识别、供电和编码线程是否稳定。修好硬件后，使用相同的数据集 ID、根目录、机械臂/相机配置续录：

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/follower_arm \
  --robot.id=my_follower_arm \
  --robot.cameras="{front: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}}" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/leader_arm \
  --teleop.id=my_leader_arm \
  --dataset.repo_id=my-so101-test \
  --dataset.root=./data/datasets/my-so101-test \
  --dataset.no_stamp=true \
  --dataset.num_episodes=5 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=10 \
  --dataset.single_task="把红色玩偶放进纸箱" \
  --dataset.push_to_hub=false \
  --resume=true
```

续录时 `--dataset.num_episodes` 表示**本次还要追加的回合数**，不是数据集最终总回合数。不要把修复相机前的坏回合当作高质量示范；如果坏帧已写入数据集，先用数据集工具检查并排除或重新录制。

### 7.8 查看和回放数据集

当前仓库内置 Rerun 数据集查看器。查看第 0 回合：

```bash
lerobot-dataset-viz \
  --repo-id my-so101-test \
  --root ./data/datasets/my-so101-test \
  --episode-index 0
```

重点检查：相机是否持续有画面、动作是否从完整起始状态开始、夹爪是否看得清、示范中是否有犹豫和无效回合。训练前先删掉或重录明显错误的回合。

确认数据集动作可回放后，再谨慎尝试：

```bash
lerobot-replay \
  --robot.type=so101_follower \
  --robot.port=/dev/follower_arm \
  --robot.id=my_follower_arm \
  --dataset.repo_id=my-so101-test \
  --dataset.root=./data/datasets/my-so101-test \
  --dataset.episode=0
```

回放会驱动机械臂，先清空工作区、降低风险，并随时准备 `Ctrl+C`。回放使用的机械臂校准和数据集动作空间必须匹配。

### 7.9 ACT 训练建议

当前官方训练入口是 `lerobot-train`，无需复制剪藏文章中的 `extra/lerobot_train_swanlab.py`。ACT 是 SO-101 入门的合适基线：对单任务、固定相机和相对一致的示范通常容易先得到结果。

```bash
lerobot-train \
  --dataset.repo_id=my-so101-test \
  --dataset.root=./data/datasets/my-so101-test \
  --policy.type=act \
  --policy.device=cuda \
  --output_dir=./outputs/train/act_my_so101_test \
  --job_name=act_my_so101_test \
  --batch_size=8 \
  --steps=100000 \
  --wandb.enable=false \
  --policy.push_to_hub=false
```

没有 CUDA 时，将设备改为 `mps`（Apple Silicon）或 `cpu`，并适当减小 `--batch_size`。训练步数、批大小和显存占用需要根据数据集和硬件调整；`100000` 是一个可观察趋势的起点，不是保证收敛的固定值。每次训练都保留输出目录中的配置和 checkpoint，便于比较数据质量与超参数。

如果中断训练，可从最后 checkpoint 的配置恢复：

```bash
lerobot-train \
  --config_path=./outputs/train/act_my_so101_test/checkpoints/last/pretrained_model/train_config.json \
  --resume=true
```

当前项目原生支持 Weights & Biases（`--wandb.enable=true`）。SwanLab 需要额外的自定义封装；剪藏文章中的 SwanLab 文件是文章作者的扩展，不属于当前仓库内置 CLI，不能直接假定安装本仓库后就存在。

### 7.10 后续可选：获得模型后使用 `lerobot-rollout` 做策略推理

`lerobot-rollout` 是当前仓库提供的模型推理入口：加载已经训练好的策略，根据相机画面和关节状态预测动作，再发送给真实机械臂。“推理入口改用此命令”说的是软件接口与旧文章的区别，不表示本机已经部署或运行了模型。

执行前必须已有可用的模型权重及配套配置、处理器文件，并完成机械臂校准和相机配置。当前已完成机械臂校准和相机配置确认，但本次尚未训练模型，也未执行下面的命令；其中 checkpoint 路径是预期训练产物的示例，不代表该目录已存在。

完成训练后，最小的无数据保存推理模板为：

```bash
lerobot-rollout \
  --strategy.type=base \
  --policy.path=./outputs/train/act_my_so101_test/checkpoints/last/pretrained_model \
  --robot.type=so101_follower \
  --robot.port=/dev/follower_arm \
  --robot.id=my_follower_arm \
  --robot.cameras="{front: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}}" \
  --task="把红色玩偶放进纸箱" \
  --duration=30
```

如果模型保存在 Hub，将 `--policy.path` 换成对应模型仓库 ID。策略训练时使用的相机名称、分辨率、预处理和任务描述应与推理配置保持一致。第一次推理时保持机械臂周围无障碍物，使用较短的 `--duration`，确认策略输出方向和安全限位后再延长运行时间。

不要把剪藏文章中的 `python -m lerobot.extra.lerobot_record_web` 当作当前官方入口：那些 Web 录制和推理脚本是文章中自行添加的扩展文件，本仓库当前对应功能由 `lerobot-record` 和 `lerobot-rollout` 提供。需要浏览器可视化时，优先使用现有的 Rerun/Foxglove 配置。

### 7.11 本地模型、VLA、RT 与 `task` 参数

“本地模型”只表示模型权重和配置保存在本机目录，例如：

```text
outputs/train/act_my_task/checkpoints/last/pretrained_model/
```

它不等于 VLA。模型类型由训练时的 `--policy.type` 决定：

| 模型或名称 | 是否通常使用自然语言 | 典型输入 | 说明 |
| --- | --- | --- | --- |
| ACT | 否 | 相机图像、关节状态 | 常见的单任务模仿学习策略；行为由训练数据隐式决定 |
| Diffusion | 通常否 | 相机图像、关节状态 | 是否使用语言取决于具体实现和训练配置 |
| SmolVLA、PI0、PI05 | 是 | 相机图像、关节状态、语言任务 | 属于视觉-语言-动作（VLA）策略 |
| RT-1、RT-2 | 是 | 图像、语言任务，可能还有状态 | VLA 架构；是否能直接加载取决于当前仓库是否有对应实现和格式适配 |

另外，命令中的 `--inference.type=rtc` 指的是 **Real-Time Chunking** 推理后端，不是 RT-1/RT-2 模型，也不会把一个普通 ACT 自动变成 VLA。RTC 负责异步生成、合并和消费动作块；只有支持 RTC 的策略和匹配的 checkpoint 才能使用它。

#### `--task` 的实际流程

`lerobot-rollout --task="抓取红色方块"` 的处理过程是：

1. rollout 创建推理引擎，并保存这段字符串作为当前任务。
2. 每次采集相机和关节状态时，LeRobot 将 `task` 与观测一起放入模型输入字典。
3. VLA 策略的预处理器把任务文本分词或编码，模型用它和图像、状态共同预测动作。
4. ACT 等不需要语言的策略通常不会读取这个字段，动作主要由图像、状态和 checkpoint 决定；此时 `task` 仍可能作为录制数据的任务标签使用。

因此，`task` 不是给操作系统执行的命令，也不是自动规划器。对语言条件模型，它是当前行为的语言条件；对单任务 ACT，它不能临时把模型改造成另一个任务。任务描述应与训练数据使用的描述保持一致，例如训练时是 `pick up the red cube`，推理时不要随意改成含义或语言结构差异很大的句子。

如果使用 `--interactive=true`，还可以通过 `/subtask <文本>` 在运行中更新任务。同步或 RTC 推理引擎会丢弃或替换尚未执行的旧动作块，使新的语言条件从后续推理开始生效；这仍要求 checkpoint 本身支持语言条件。

## 8. 经验性排错清单

| 现象 | 优先检查 |
| --- | --- |
| `Permission denied` 打不开串口 | Linux 设备组/权限；macOS 应用授权；是否被另一个进程占用 |
| 找不到 `gripper` | 是否误在整臂上运行单电机初始化；供电、三芯线、控制板跳帽和波特率 |
| 校准表的 `MIN` 和 `MAX` 不变 | 表格出现后是否真的手动移动关节；是否移动了正确的机械臂；是否提前按 Enter |
| 运动方向相反 | 立即停止，检查 leader/follower 类型、校准文件、ID 对应和 drive mode |
| `Incorrect status packet` 或超时 | 电源电压、串口线、总线连接、多个电机广播冲突、USB 集线器和重试次数 |
| 相机读取超时 | 相机线缆是否被拉扯、相机索引是否变化、分辨率/FPS 是否被设备接受、编码线程是否过载 |
| 训练显存不足 | 降低 `--batch_size`、使用更小图像、选择合适设备或云端 GPU |

遇到硬件运动异常时，优先断开扭矩或切断电源，再查看日志。任何“看起来只是软件参数”的问题，都应先排除电源、线缆和机械限位。

## 9. 文章内容与当前仓库的差异

剪藏文章的实践价值主要在于：成品臂可以跳过电机初始化、先做动作方向检查、相机线缆要留余量、先录 5 回合验证再扩展数据集，以及用多个物体位置增加示范多样性。以下内容需要按当前仓库调整：

- Python 版本：文章中的 3.10 → 当前项目要求 3.12+。
- 入口命令：文章中的自定义 `extra` Web 脚本 → 当前官方 `lerobot-record` / `lerobot-rollout`。
- 训练：文章的 SwanLab 封装 → 当前 `lerobot-train` 原生支持 W&B；SwanLab 需自行维护扩展。
- 校准参数：文章的 `--robot.calibration_dir` 示例仍可用于当前配置，但应使用真实存在的目录；默认目录由 `HF_LEROBOT_CALIBRATION` 和设备类型决定。
- 推理评估：文章的自定义录制脚本 → 当前 `lerobot-rollout --strategy.type=base` 运行策略，若要保存评估轨迹再选择带 dataset 的 rollout strategy。

## 10. 相关文件

- [夹爪手动测试脚本](../tests/motors/manual_gripper.py)
- [SO-101 官方仓库指南](source/so101.mdx)
- [项目用户操作指南](../AGENT_GUIDE.md)
- [从臂校准实现](../src/lerobot/robots/so_follower/so_follower.py)
- [电机运动范围记录实现](../src/lerobot/motors/motors_bus.py)
