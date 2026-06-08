# ros_llm_voice_agent

这是一个面向机器人 ROS 系统的独立大模型语音 Agent 包。

本包不依赖 `ywy` 业务代码，而是通过 ROS topic、service、BodyHub、AIUI、视觉和动作脚本等已有接口连接机器人能力。核心思路是把机器人的基础能力封装成工具，由 Agent Harness 统一调度，从而支持后续扩展更多语音控制和机器人任务。

当前代码保持 ROS Kinetic / Python 2.7 运行环境兼容，脚本入口使用：

```python
#!/usr/bin/env python
```

## 功能概览

- 非实时语音对话：AIUI 识别文本 -> 大模型 -> 可选工具调用 -> TTS 生成音频 -> 本地播放。
- 实时聊天模式：唤醒后说触发词进入连续对话，播放结束后自动调用 `/aiui/wakeup_mute` 继续监听。
- Agent Harness：统一管理对话、工具调用、安全检查、记忆和 ROS 适配。
- StepFun 大模型：支持 OpenAI-compatible chat completions 和原生工具调用。
- StepFun TTS：文本输入直接生成音频文件，再由机器人播放。
- 文本清洗：播放前会去掉 Markdown、符号和不适合 TTS 的格式，减少“某某”式错误播报。

## 运行配置

API key 和本地运行参数不要提交到 Git。推荐在机器人上创建：

```bash
mkdir -p ~/.config/ros_llm_voice_agent
nano ~/.config/ros_llm_voice_agent/env.sh
chmod 600 ~/.config/ros_llm_voice_agent/env.sh
```

`env.sh` 只放 **API key 和 URL**；模型、音色等其余配置都在 yaml 里（见下面「配置职责划分」）。示例：

```bash
# 大模型 chat completions
export LLM_BASE_URL="https://api.stepfun.com/v1/chat/completions"
export LLM_API_KEY="your-stepfun-api-key"

# 非实时 TTS
export STEPFUN_TTS_URL="https://api.stepfun.com/v1/audio/speech"
export STEPFUN_TTS_API_KEY="your-stepfun-api-key"

# 阶跃实时语音 WebSocket 后端
export STEPFUN_REALTIME_API_KEY="$LLM_API_KEY"
export STEPFUN_REALTIME_URL="wss://api.stepfun.com/v1/realtime"
```

如果没有单独设置 `STEPFUN_TTS_API_KEY` / `STEPFUN_REALTIME_API_KEY`，会回退使用 `LLM_API_KEY`。

> `*_MODEL`、`*_VOICE` 这类环境变量仍然**优先生效**（env 覆盖 yaml），但默认不再写在 `env.sh` 里，改到 yaml 配置；只在需要临时覆盖时才在 env 设置。

## 配置职责划分

配置分两层：`env.sh` 只管「密钥和端点」，yaml 管「行为和参数」。解析顺序是 **环境变量 → yaml → 代码默认**，即 env 可临时覆盖 yaml。

| 文件 | 负责 |
|---|---|
| `~/.config/ros_llm_voice_agent/env.sh` | **仅** API key（`*_API_KEY`）和 URL（`LLM_BASE_URL`、`STEPFUN_TTS_URL`、`STEPFUN_REALTIME_URL`）。不提交 Git。 |
| `config/agent.yaml` | 非实时主链路：LLM（`llm.model`）、TTS（`tts.model`、`tts.voice`）、会话触发词、topic/service 名等。 |
| `config/stepfun_realtime.yaml` | 阶跃实时语音后端：`model`、`voice`、`modalities`、`turn_detection`(VAD)、`audio`(采样率/设备/增益)、工具开关等。 |
| `config/tools.yaml` | 工具白名单：`actions`(play_action 子动作) 和 `dynamic_ros_tools`(声明式 service/topic/listener 工具)。 |
| `config/prompts.yaml` | 系统提示词。 |
| `config/safety.yaml` | 运动安全限制(前进/后退/转向上限)。 |

当前默认：LLM `step-3.7-flash`；非实时 TTS `step-tts-2` + `qingchunshaonv`(女声)；实时 `step-1o-audio` + `linjiajiejie`(女声)。

`config/agent.yaml` 默认开启 OpenAI-compatible 原生工具调用：

```yaml
send_tools_native: true
```

## 启动方式

先加载 ROS 环境和本包环境变量：

```bash
source /opt/ros/kinetic/setup.bash
source ~/robot_ros_application/catkin_ws/devel/setup.bash
source ~/.config/ros_llm_voice_agent/env.sh
```

启动非实时语音 Agent：

```bash
roslaunch ros_llm_voice_agent agent_non_realtime.launch
```

启动带实时聊天触发的 Agent：

```bash
roslaunch ros_llm_voice_agent agent_realtime.launch
```

启动阶跃实时语音后端：

```bash
roslaunch ros_llm_voice_agent agent_stepfun_realtime.launch
```

## 测试方式

文本模拟一次 AIUI 识别结果：

```bash
rostopic pub -1 /aiui/nlp std_msgs/String "data: '你好，介绍一下你自己'"
```

手动进入或退出实时聊天模式：

```bash
rosservice call /llm_voice_agent/start_realtime "{}"
rosservice call /llm_voice_agent/stop_realtime "{}"
```

紧急停止当前语音、动作或工具流程：

```bash
rosservice call /llm_voice_agent/stop_all "{}"
```

常用监控 topic：

```text
/llm_voice_agent/state       当前状态，例如 idle/realtime
/llm_voice_agent/transcript  Agent 收到的识别文本
/llm_voice_agent/reply_text  大模型原始回复文本
/llm_voice_agent/tool_events 工具调用、TTS、播放事件
/llm_voice_agent/play_end    本地音频播放结束事件
```

## 实时聊天

当前有两种实时模式：

- `agent_realtime.launch`：旧的 AIUI 连续监听模式，AIUI 负责唤醒、VAD 和 ASR，Agent 负责大模型和 TTS。
- `agent_stepfun_realtime.launch`：新的阶跃实时语音后端，AIUI 只负责触发入口，进入后由 `stepfun_realtime_voice_node.py` 直接采集麦克风 PCM 音频并通过 WebSocket 发给阶跃。

唤醒机器人后，说下面任意触发词可进入实时聊天模式：

```text
和我聊聊天
陪我聊聊天
开始聊天
聊天模式
实时语音
进入实时语音
```

进入实时聊天后，每次回复播放结束，节点会调用 `/aiui/wakeup_mute`，让 AIUI 继续监听而不额外播放唤醒反馈。

实时模式还带有 listen watchdog：如果布防后长时间没有收到 `/aiui/nlp`，例如 AIUI 出现 VAD 前端点/后端点但没有 NLP 文本，Agent 会自动再次调用 `/aiui/wakeup_mute` 重新进入监听。Agent 也会监听 `/aiui/iat`，一旦有中间识别文本就认为用户正在说话，避免 watchdog 在用户说话过程中重置 AIUI。

进入实时语音也暴露为工具：`start_realtime_voice`。默认配置下，`和我聊聊天`、`陪我聊聊天`、`进入实时语音` 这类表达会先交给 LLM 判断，由 LLM 调用该工具进入连续对话模式。需要恢复旧的硬触发方式时，把 `config/agent.yaml` 里的 `chat_triggers_use_llm_tool` 改为 `false`。

说下面任意退出词可回到普通待机模式：

```text
退出聊天
不聊了
停止聊天
```

如果要接入外部实时 ASR，只需要发布最终识别文本到：

```text
/llm_voice_agent/realtime/final_text
```

启动方式：

```bash
roslaunch ros_llm_voice_agent agent_realtime.launch enable_realtime_text_topic:=true
rostopic pub -1 /llm_voice_agent/realtime/final_text std_msgs/String "data: '往前走一点'"
```

### 阶跃实时语音后端

新的实时节点提供：

```text
/llm_voice_agent/stepfun_realtime/start
/llm_voice_agent/stepfun_realtime/stop
/llm_voice_agent/stepfun_realtime/state
```

主 Agent 会额外提供给实时节点使用的工具服务：

```text
/llm_voice_agent/tool_specs
/llm_voice_agent/execute_tool
```

实时节点启动后会从 `/llm_voice_agent/tool_specs` 拉取当前工具 schema，传给阶跃实时模型。阶跃返回 function call 时，节点会调用 `/llm_voice_agent/execute_tool`，由现有 Agent Harness 执行工具并把结果回传给实时模型。

机器人上如果缺少 WebSocket 依赖，先安装：

```bash
python -m pip install --user "websocket-client==0.59.0"
```

本地 PC 可以先脱离 ROS 测试阶跃实时语音链路：

```powershell
pixi install
$env:STEPFUN_REALTIME_API_KEY="your-stepfun-api-key"
pixi run realtime-text
pixi run realtime-mic
pixi run realtime-mic-commit
```

`realtime-mic` 使用服务端 VAD 自动判断说话结束；`realtime-mic-commit` 会录音 5 秒后手动提交音频，适合排查“持续输入但不输出”的问题。

实时语音默认直接订阅机器人已有的麦克风阵列音频流：

```text
/audio/stream
```

这个 topic 是 `std_msgs/UInt8MultiArray`，当前机器人上约为 16 kHz、16-bit、mono PCM。实时节点会重采样到 24 kHz 后发给阶跃实时语音接口。

如果要改回 ALSA 直接采集，修改 `config/stepfun_realtime.yaml`：

```yaml
audio:
  input_source: alsa
```

ALSA 采集和播放使用系统命令：

```text
arecord
aplay
```

实时语音播放设备和音量在 `config/stepfun_realtime.yaml`：

```yaml
audio:
  output_device: plughw:0,0   # 机器人模拟扬声器(card0)，plughw 自动重采样
  output_gain: 3.0            # 阶跃返回 PCM 振幅偏低，软件增益放大；破音就调小
```

> 用 `aplay -l` 确认声卡编号。当前机器人只有 card0，**不要写不存在的 `hw:2,0`**（会导致 aplay broken pipe：有 speaking 状态却没声音）。

手动测试：

```bash
rostopic echo /llm_voice_agent/stepfun_realtime/state
rosservice call /llm_voice_agent/stepfun_realtime/start "{}"
rosservice call /llm_voice_agent/stepfun_realtime/stop "{}"
```

### 实时语音排错（踩过的坑）

接通阶跃实时语音时踩过的坑，按现象排查：

- **连得上但完全没声音 / `response.done status=incomplete`**：先查工具 schema 格式。阶跃实时要 **chat-completions 嵌套格式** `{type: function, function: {name, ...}}`，平铺写法 `{type: function, name: ...}` 会回 `400 input_invalid`。
- **麦克风模式一直发数据但没回复**：
  - `turn_detection` 必须带 `create_response: true`，否则服务端 VAD 检测到说话也不自动生成回复。
  - `energy_awakeness_threshold` 默认 **2500 偏高**，机器人麦克风经 16k→24k 重采样后能量偏低常常过不了线。节点已上报 `rms`（`/llm_voice_agent/tool_events` 的 `stepfun_realtime_audio_stream` 事件里）；说话时 `rms` 要明显大于阈值，否则调低（机器人上用 1200）。
  - 本机 PC 测试时默认输入设备可能是 VoiceMeeter 等虚拟声卡（静音，`rms=0`），要用 `--input-device` 指定真实麦克风。
- **state 走到 speaking 却没声音 / `play_error: Broken pipe`**：播放设备不存在或打不开。`aplay -l` 查声卡，用 `plughw:0,0`，别用不存在的 `hw:2,0`。
- **有声音但比非实时小很多**：阶跃返回 PCM 振幅偏低，调大 `audio.output_gain`。
- **模型只复述用户的话、不回答**：`step-audio-2-mini` 对音频输入复述倾向很强，需很强系统提示才压得住；换旗舰 `step-1o-audio` 即正常对话。另外 `step-audio-2-mini` 还要求 instructions 末尾追加「请使用默认男声/女声与用户交流」，旗舰模型不需要。
- **改了节点/yaml 不生效**：节点在进程启动时读一次 yaml，改完要**重启节点进程**（不是 stop/start 服务）。
- **本机脱离 ROS 排查**：`pixi run realtime-mic-commit --raw --input-device <N>` 录 5 秒手动提交，`--raw` 打印服务端原始事件，最适合定位「持续输入不输出」。`pixi run audio-devices` 列设备号。

## 给队友调用

队友代码建议通过 ROS topic 和 service 调用本模块，不建议直接 import Python 内部类。

常用输入方式：

```bash
# 发送一句普通语音识别后的文本
rostopic pub -1 /aiui/nlp std_msgs/String "data: '介绍一下你自己'"

# 进入或退出实时聊天
rosservice call /llm_voice_agent/start_realtime "{}"
rosservice call /llm_voice_agent/stop_realtime "{}"

# 停止当前 Agent 管理的语音、动作或工具流程
rosservice call /llm_voice_agent/stop_all "{}"
```

队友如果只想观察 Agent 输出，可以订阅：

```text
/llm_voice_agent/state
/llm_voice_agent/transcript
/llm_voice_agent/reply_text
/llm_voice_agent/tool_events
/llm_voice_agent/play_end
```

## 添加新工具

新增机器人能力时，推荐保持这个分层：

1. 在 `ros/ros_adapter.py` 中封装具体 ROS topic、service 或动作调用。
2. 在 `tools/` 目录中定义工具逻辑。
3. 在 `tools/factory.py` 中注册工具。
4. 在 `config/tools.yaml` 中配置工具开关和描述。
5. 必要时在 `config/safety.yaml` 中加入安全限制。

大模型只应该看到工具名、描述和 JSON 参数。具体 ROS 细节应留在 Tool 或 `RosAdapter` 内部。

## YAML 动态工具

如果别人已经写好了 ROS 包，并且它暴露了 service、topic 或可订阅的状态 topic，可以直接在 `config/tools.yaml` 的 `dynamic_ros_tools` 里注册成工具，不一定要再写 Python Tool 类。

支持三种类型：

```text
service   调用 ROS service
topic     发布一条 ROS message
listener  订阅 ROS topic，并在工具调用时返回最近一次消息
```

当前 `config/tools.yaml` 的 `dynamic_ros_tools` 只保留一个示例：

```text
dynamic_stop_aiui_playback   发布 /aiui/stop_play（topic 类型）
```

> 机器人状态、电池、人脸检测已由内置工具（`get_bodyhub_status` / `get_battery_state` / `detect_face`）提供，不再用动态工具重复注册。下面的 service / topic / listener 写法仍可作为接入队友 ROS 包的模板。

### 注册 Service

示例：把别人的 `/demo/set_light` service 注册成 `set_light` 工具。

```yaml
dynamic_ros_tools:
  set_light:
    type: service
    description: 设置机器人灯光颜色。
    risk: low
    service: /demo/set_light
    service_type: teammate_pkg/SetLight
    timeout_seconds: 2.0
    parameters:
      type: object
      properties:
        color:
          type: string
          description: 灯光颜色
          enum: [red, green, blue]
      required: [color]
    request:
      fields:
        color: color
      constants:
        enable: true
    response:
      fields:
        success: success
        detail: message
```

含义：

- `parameters` 是给大模型看的 JSON schema。
- `request.fields` 表示把工具参数映射到 service request 字段。
- `request.constants` 表示固定写入 request 的常量字段。
- `response.fields` 表示从 service response 中抽取哪些字段返回给 Agent。

### 注册 Topic 发布

示例：把 `/demo/expression` 注册成一个发布表情的工具。

```yaml
dynamic_ros_tools:
  set_expression:
    type: topic
    description: 设置机器人脸部表情。
    risk: low
    topic: /demo/expression
    message_type: std_msgs/String
    queue_size: 2
    parameters:
      type: object
      properties:
        expression:
          type: string
          description: 表情名称
          enum: [happy, sad, neutral]
      required: [expression]
    message:
      fields:
        data: expression
```

如果 message 只有一个字段，例如 `std_msgs/String.data`，也可以省略 `message`，工具调用只有一个参数时会自动写入这个字段。

### 注册 Listener

示例：把别人视觉包发布的 `/demo/object_name` 注册成一个查询工具。

```yaml
dynamic_ros_tools:
  get_seen_object:
    type: listener
    description: 获取视觉模块最近识别到的物体名称。
    risk: low
    topic: /demo/object_name
    message_type: std_msgs/String
    timeout_seconds: 2.0
    wait_for_message: true
    max_age_seconds: 5.0
    parameters:
      type: object
      properties: {}
    result:
      fields:
        object_name: data
```

`listener` 会在 Agent 启动时订阅 topic。工具被调用时会返回最近一次消息；如果还没收到消息，并且 `wait_for_message: true`，会等待最多 `timeout_seconds`。

### 字段路径

字段映射支持点号路径，例如：

```yaml
request:
  fields:
    target.pose.position.x: x
    target.pose.position.y: y
```

这适合封装嵌套 ROS message。前提是目标 message/request 本身已经有对应字段。

## 迁移到新机器人

把本包放入目标机器人 catkin workspace：

```bash
cd ~/robot_ros_application/catkin_ws/src
git clone https://github.com/EnderRieck/RobotVoice.git ros_llm_voice_agent
cd ~/robot_ros_application/catkin_ws
catkin_make --pkg ros_llm_voice_agent
source devel/setup.bash
```

然后在新机器人上单独配置 `env.sh`，不要把 API key 写进仓库：

```bash
mkdir -p ~/.config/ros_llm_voice_agent
nano ~/.config/ros_llm_voice_agent/env.sh
chmod 600 ~/.config/ros_llm_voice_agent/env.sh
source ~/.config/ros_llm_voice_agent/env.sh
```

检查目标机器人是否有这些接口：

```bash
rostopic list | grep -E '/aiui/nlp|/micarrays/wakeup|/aiui/stop_play'
rosservice list | grep /aiui/wakeup_mute
rostopic list | grep -E '/gaitCommand|/MediumSize/BodyHub|/MediumSize/SensorHub/BatteryState'
```

如果 topic 或 service 名字不一致，修改：

```text
config/agent.yaml
src/ros_llm_voice_agent/ros/ros_adapter.py
```

基础迁移测试：

```bash
source /opt/ros/kinetic/setup.bash
source ~/robot_ros_application/catkin_ws/devel/setup.bash
source ~/.config/ros_llm_voice_agent/env.sh
roslaunch ros_llm_voice_agent agent_non_realtime.launch
rostopic pub -1 /aiui/nlp std_msgs/String "data: '你好，介绍一下你自己'"
```

## 本地保存和提交

这个包应该作为独立 ROS 包维护，不建议把整个机器人 ROS 框架提交到个人仓库。

如果是在机器人总仓库中开发，提交时只添加本包路径：

```bash
cd ~/robot_ros_application
git add catkin_ws/src/ros_llm_voice_agent
git status --short catkin_ws/src/ros_llm_voice_agent
git commit -m "Update ROS LLM voice agent"
```

不要在机器人总仓库里直接使用：

```bash
git add .
```

因为共享机器人里可能有地图、二进制文件、缓存文件和其他同学的改动。

提交前清理 Python 缓存：

```bash
find catkin_ws/src/ros_llm_voice_agent -name '*.pyc' -delete
find catkin_ws/src/ros_llm_voice_agent -name '__pycache__' -type d -prune -exec rm -rf {} +
```

## 推送到 GitHub

当前推荐维护方式是：GitHub 仓库只保存这个包本身，不保存整个 `robot_ros_application`。

本地初始化后，绑定远端并推送：

```bash
git remote add origin https://github.com/EnderRieck/RobotVoice.git
git push -u origin main
```

后续更新流程：

```bash
git status
git add README.md config src scripts launch package.xml CMakeLists.txt setup.py
git commit -m "Update voice agent"
git push
```

再次强调：API key、`env.sh`、运行日志、生成音频和 catkin 构建目录不应提交到 Git。
