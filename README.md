# ros_llm_voice_agent

Independent LLM voice agent package for the robot ROS application.

This package does not depend on `ywy` business code. It uses existing ROS audio,
AIUI, BodyHub, vision, and action scripts through a constrained Agent Harness.
The node uses `#!/usr/bin/env python` and keeps the code Python 2/3 compatible
for the existing ROS Kinetic-style runtime.

Main environment variables:

- `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` for the OpenAI-compatible chat API.
- `STEPFUN_TTS_URL`, `STEPFUN_TTS_API_KEY`, `STEPFUN_TTS_MODEL`,
  `STEPFUN_TTS_VOICE` for file-style TTS. If `STEPFUN_TTS_API_KEY` is not set,
  the node falls back to `LLM_API_KEY`.

For StepFun native tool calling:

```bash
export LLM_BASE_URL="https://api.stepfun.ai/v1/chat/completions"
export LLM_MODEL="step-3.7-flash"
export LLM_API_KEY="your-stepfun-api-key"
export STEPFUN_TTS_URL="https://api.stepfun.ai/v1/audio/speech"
export STEPFUN_TTS_MODEL="step-tts-2"
export STEPFUN_TTS_VOICE="lively-girl"
```

`config/agent.yaml` enables native OpenAI-compatible `tools` by default through
`send_tools_native: true`.

Initial launch:

```bash
source ~/robot_ros_application/catkin_ws/devel/setup.bash
roslaunch ros_llm_voice_agent agent_non_realtime.launch
```

Realtime AIUI voice launch:

```bash
source ~/robot_ros_application/catkin_ws/devel/setup.bash
source ~/.config/ros_llm_voice_agent/env.sh
roslaunch ros_llm_voice_agent agent_realtime.launch
```

Say `和我聊聊天`, `陪我聊聊天`, `开始聊天`, `聊天模式`, `实时语音`,
or `进入实时语音` after wakeup to enter realtime mode.
After every reply, the node calls `/aiui/wakeup_mute` so AIUI keeps listening
without playing another wakeup reply. Say `退出聊天`, `不聊了`, or `停止聊天`
to return to idle mode.

Service-based realtime test:

```bash
rosservice call /llm_voice_agent/start_realtime "{}"
rosservice call /llm_voice_agent/stop_realtime "{}"
```

Realtime text stub launch:

```bash
roslaunch ros_llm_voice_agent agent_with_realtime_stub.launch
```

Publish a simulated realtime final transcript:

```bash
rostopic pub /llm_voice_agent/realtime/final_text std_msgs/String "data: '往前走一点'"
```

## Calling this module from teammate code

Treat this package as a ROS-facing voice Agent. Teammate code should usually call
it through ROS topics and services instead of importing Python modules directly.

Common input methods:

```bash
# Send one recognized sentence into the normal AIUI text path.
rostopic pub -1 /aiui/nlp std_msgs/String "data: '介绍一下你自己'"

# Enter or exit realtime voice mode without speaking.
rosservice call /llm_voice_agent/start_realtime "{}"
rosservice call /llm_voice_agent/stop_realtime "{}"

# Emergency stop for speech/actions/tools managed by this Agent.
rosservice call /llm_voice_agent/stop_all "{}"
```

Common output/monitor topics:

```text
/llm_voice_agent/state       std_msgs/String, JSON state such as idle/realtime
/llm_voice_agent/transcript  std_msgs/String, text received by the Agent
/llm_voice_agent/reply_text  std_msgs/String, raw LLM reply text
/llm_voice_agent/tool_events std_msgs/String, JSON tool-call/TTS/playback events
/llm_voice_agent/play_end    std_msgs/Empty, emitted after local audio playback
```

For an external realtime ASR backend, launch with realtime text input enabled
and publish final transcripts to `/llm_voice_agent/realtime/final_text`:

```bash
roslaunch ros_llm_voice_agent agent_realtime.launch enable_realtime_text_topic:=true
rostopic pub -1 /llm_voice_agent/realtime/final_text std_msgs/String "data: '往前走一点'"
```

To add new robot capabilities, keep ROS-specific code behind `RosAdapter`, define
a tool schema, and register the tool through `tools/factory.py`. The LLM should
only see the tool name, description, and JSON parameters; direct ROS topic/service
details should stay inside the tool or adapter layer.

## Migrating to another robot

Copy only this package into the target robot workspace:

```bash
cp -r ros_llm_voice_agent ~/robot_ros_application/catkin_ws/src/
cd ~/robot_ros_application/catkin_ws
catkin_make --pkg ros_llm_voice_agent
source devel/setup.bash
```

Create runtime environment variables on the new robot. Do not commit this file:

```bash
mkdir -p ~/.config/ros_llm_voice_agent
nano ~/.config/ros_llm_voice_agent/env.sh
chmod 600 ~/.config/ros_llm_voice_agent/env.sh
```

Expected `env.sh` entries:

```bash
export LLM_BASE_URL="https://api.stepfun.ai/v1/chat/completions"
export LLM_MODEL="step-3.7-flash"
export LLM_API_KEY="your-stepfun-api-key"
export STEPFUN_TTS_URL="https://api.stepfun.ai/v1/audio/speech"
export STEPFUN_TTS_MODEL="step-tts-2"
export STEPFUN_TTS_VOICE="wenrounansheng"
```

Check the target robot has the expected voice and control interfaces:

```bash
rostopic list | grep -E '/aiui/nlp|/micarrays/wakeup|/aiui/stop_play'
rosservice list | grep /aiui/wakeup_mute
rostopic list | grep -E '/gaitCommand|/MediumSize/BodyHub|/MediumSize/SensorHub/BatteryState'
```

If topic or service names differ, update `config/agent.yaml` for AIUI topics and
update `ros/ros_adapter.py` for robot-specific control APIs such as BodyHub,
walking, battery, actions, or vision services.

Runtime dependencies to verify on the target robot:

```text
ROS workspace with ros_AIUI_node, ros_mic_arrays, BodyHub/control packages
Python packages: requests, yaml
Audio playback command: play from sox, or ffplay as fallback
Network access to the configured LLM/TTS API endpoint
```

Basic migration test:

```bash
source /opt/ros/kinetic/setup.bash
source ~/robot_ros_application/catkin_ws/devel/setup.bash
source ~/.config/ros_llm_voice_agent/env.sh
roslaunch ros_llm_voice_agent agent_non_realtime.launch
rostopic pub -1 /aiui/nlp std_msgs/String "data: '你好，介绍一下你自己'"
```

## Saving this package

This package should be versioned as an independent ROS package, not by committing
the whole robot ROS workspace.

Recommended local save flow:

```bash
cd ~/robot_ros_application
git switch -c feature/llm-voice-agent
git add catkin_ws/src/ros_llm_voice_agent
git status --short catkin_ws/src/ros_llm_voice_agent
git commit -m "Add ROS LLM voice agent"
```

Do not use `git add .` in the robot workspace unless you have reviewed all
unrelated robot, map, binary, and generated-file changes.

Keep runtime secrets out of Git. API keys and local provider settings should stay
in:

```bash
~/.config/ros_llm_voice_agent/env.sh
```

If the package is edited directly on the robot, copy the changed package or YAML
files back to the local checkout before committing. Before committing from the
robot, remove generated Python cache files:

```bash
find catkin_ws/src/ros_llm_voice_agent -name '*.pyc' -delete
find catkin_ws/src/ros_llm_voice_agent -name '__pycache__' -type d -prune -exec rm -rf {} +
```

The existing upstream remote belongs to the robot system repository. Keep commits
local or push to a personal/course repository unless you are sure the upstream
remote is the intended target.
