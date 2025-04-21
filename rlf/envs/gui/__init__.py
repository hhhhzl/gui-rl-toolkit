import rlf.envs.ant.ant_interface
from gym.envs.registration import register

register(
    id="GUI-v0",
    entry_point="rlf.envs.gui.gui:GUIEnv",
    max_episode_steps=50,
)