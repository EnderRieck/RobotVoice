#!/usr/bin/env bash
# Deploy the realtime-voice fixes onto the robot.
# Run ON the robot after the two updated files have been uploaded to /tmp/deploy/.
#   scp scripts/stepfun_realtime_voice_node.py config/stepfun_realtime.yaml lemon@<robot>:/tmp/deploy/
#   ssh lemon@<robot> bash /tmp/deploy/deploy_realtime_to_robot.sh
set -e

PKG="$HOME/robot_ros_application/catkin_ws/src/ros_llm_voice_agent"
ENV="$HOME/.config/ros_llm_voice_agent/env.sh"
SRC="/tmp/deploy"
TS="$(date +%Y%m%d_%H%M%S)"

echo "=== 1. syntax-check the new node ==="
python3 -m py_compile "$SRC/stepfun_realtime_voice_node.py"
echo "COMPILE_OK"

echo "=== 2. backup current files (suffix .bak_$TS) ==="
cp -p "$PKG/scripts/stepfun_realtime_voice_node.py" "$PKG/scripts/stepfun_realtime_voice_node.py.bak_$TS"
cp -p "$PKG/config/stepfun_realtime.yaml"          "$PKG/config/stepfun_realtime.yaml.bak_$TS"
cp -p "$ENV"                                        "${ENV}.bak_$TS"

echo "=== 3. install updated package files ==="
cp "$SRC/stepfun_realtime_voice_node.py" "$PKG/scripts/stepfun_realtime_voice_node.py"
cp "$SRC/stepfun_realtime.yaml"          "$PKG/config/stepfun_realtime.yaml"

echo "=== 4. update env.sh voices/model (idempotent) ==="
sed -i -E 's/^(export[[:space:]]+STEPFUN_TTS_VOICE=).*/\1"qingchunshaonv"/'       "$ENV"
sed -i -E 's/^(export[[:space:]]+STEPFUN_REALTIME_MODEL=).*/\1"step-1o-audio"/'   "$ENV"
sed -i -E 's/^(export[[:space:]]+STEPFUN_REALTIME_VOICE=).*/\1"linjiajiejie"/'    "$ENV"

echo "=== 5. verify ==="
echo "-- node tool shape --"
grep -n '"function": {' "$PKG/scripts/stepfun_realtime_voice_node.py" | head -1
echo "-- realtime yaml model/voice --"
grep -nE '^\s+(model|voice):' "$PKG/config/stepfun_realtime.yaml"
echo "-- env.sh voices/model --"
grep -nE 'STEPFUN_(TTS|REALTIME)_(VOICE|MODEL)' "$ENV"
echo "=== DONE (backups: *.bak_$TS) ==="
