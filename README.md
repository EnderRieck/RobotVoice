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

`env.sh` 示例：

```bash
export LLM_BASE_URL="https://api.stepfun.ai/v1/chat/completions"
export LLM_MODEL="step-3.7-flash"
export LLM_API_KEY="your-stepfun-api-key"

export STEPFUN_TTS_URL="https://api.stepfun.ai/v1/audio/speech"
export STEPFUN_TTS_API_KEY="your-stepfun-api-key"
export STEPFUN_TTS_MODEL="step-tts-2"
export STEPFUN_TTS_VOICE="wenrounansheng"
```

如果没有单独设置 `STEPFUN_TTS_API_KEY`，程序会回退使用 `LLM_API_KEY`。

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

实时模式还带有 listen watchdog：如果布防后长时间没有收到 `/aiui/nlp`，例如 AIUI 出现 VAD 前端点/后端点但没有 NLP 文本，Agent 会自动再次调用 `/aiui/wakeup_mute` 重新进入监听。

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

当前 `config/tools.yaml` 已经放了三个安全示例：

```text
dynamic_get_bodyhub_status   调用 /MediumSize/BodyHub/GetStatus
dynamic_get_battery_state    监听 /MediumSize/SensorHub/BatteryState
dynamic_stop_aiui_playback   发布 /aiui/stop_play
detect_face                  调用 /ros_face_node/face_detect
```

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
