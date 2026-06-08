cmake_minimum_required(VERSION 2.8.3)
project(ros_llm_voice_agent)

find_package(catkin REQUIRED COMPONENTS
  message_generation
  rospy
  std_msgs
  std_srvs
)

catkin_python_setup()

add_service_files(
  FILES
  ExecuteTool.srv
  GetToolSpecs.srv
)

generate_messages(
  DEPENDENCIES
  std_msgs
)

catkin_package(
  CATKIN_DEPENDS message_runtime rospy std_msgs std_srvs
)

catkin_install_python(PROGRAMS
  scripts/llm_voice_agent_node.py
  scripts/stepfun_realtime_voice_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch config
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)
