#!/usr/bin/env python

from distutils.core import setup
from catkin_pkg.python_setup import generate_distutils_setup


d = generate_distutils_setup(
    packages=[
        "ros_llm_voice_agent",
        "ros_llm_voice_agent.core",
        "ros_llm_voice_agent.llm",
        "ros_llm_voice_agent.memory",
        "ros_llm_voice_agent.ros",
        "ros_llm_voice_agent.tools",
        "ros_llm_voice_agent.voice",
    ],
    package_dir={"": "src"},
)

setup(**d)
