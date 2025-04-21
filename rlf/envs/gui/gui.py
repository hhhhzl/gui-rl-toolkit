import os
import gym
import numpy as np
from gym import spaces, utils


class GUIEnv(gym.Env):
    def __init__(self):
        pass

    def step(self, a):
        pass

    def _get_obs(self):
        pass

    def relabel_ob(self, ob_current, ob_future):
        pass

    def is_reached(self, ob):
        pass

    def reset_model(self):
        return self._get_obs()

    def propose_original(self):
        pass

    def viewer_setup(self):
        pass

    def touching(self, geom1_name, geom2_name):
        pass

    def seed(self):
        pass
