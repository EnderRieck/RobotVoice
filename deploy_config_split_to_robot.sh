#!/usr/bin/env bash
# Round 2: move model/voice out of env.sh into yaml.
# env.sh keeps only API keys + URLs; model/voice now live in the yaml configs.
# Upload first:
#   scp src/.../generic_chat_client.py src/.../stepfun_tts.py config/agent.yaml lemon@<robot>:/tmp/deploy2/
#   ssh lemon@<robot> bash /tmp/deploy2/deploy_config_split_to_robot.sh
set -e

PKG="$HOME/robot_ros_application/catkin_ws/src/ros_llm_voice_agent"
ENV="$HOME/.config/ros_llm_voice_agent/env.sh"
SRC="/tmp/deploy2"
TS="$(date +%Y%m%d_%H%M%S)"

echo "=== 1. syntax-check new python ==="
python3 -m py_compile "$SRC/generic_chat_client.py" "$SRC/stepfun_tts.py"
echo "COMPILE_OK"

echo "=== 2. backup (.bak_$TS) ==="
cp -p "$PKG/src/ros_llm_voice_agent/llm/generic_chat_client.py" "$PKG/src/ros_llm_voice_agent/llm/generic_chat_client.py.bak_$TS"
cp -p "$PKG/src/ros_llm_voice_agent/voice/stepfun_tts.py"       "$PKG/src/ros_llm_voice_agent/voice/stepfun_tts.py.bak_$TS"
cp -p "$PKG/config/agent.yaml"                                  "$PKG/config/agent.yaml.bak_$TS"
cp -p "$ENV"                                                    "${ENV}.bak_$TS"

echo "=== 3. install ==="
cp "$SRC/generic_chat_client.py" "$PKG/src/ros_llm_voice_agent/llm/generic_chat_client.py"
cp "$SRC/stepfun_tts.py"         "$PKG/src/ros_llm_voice_agent/voice/stepfun_tts.py"
cp "$SRC/agent.yaml"             "$PKG/config/agent.yaml"

echo "=== 4. strip model/voice from env.sh (keep only API keys + URLs) ==="
sed -i '/^export LLM_MODEL=/d'              "$ENV"
sed -i '/^export STEPFUN_TTS_MODEL=/d'      "$ENV"
sed -i '/^export STEPFUN_TTS_VOICE=/d'      "$ENV"
sed -i '/^export STEPFUN_REALTIME_MODEL=/d' "$ENV"
sed -i '/^export STEPFUN_REALTIME_VOICE=/d' "$ENV"

echo "=== 5. verify ==="
echo "-- env.sh remaining non-secret lines --"
grep -nvE 'KEY|TOKEN|SECRET|PASSWORD' "$ENV" | grep -E 'export|#' | head -30
echo "-- llm/tts yaml --"
grep -nE '^\s+(model|voice):' "$PKG/config/agent.yaml"
echo "-- realtime yaml --"
grep -nE '^\s+(model|voice):' "$PKG/config/stepfun_realtime.yaml"
echo "=== DONE (backups: *.bak_$TS) ==="
