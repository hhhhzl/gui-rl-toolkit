import os
import gym
import numpy as np
from gym import spaces, utils


class GUIEnv(gym.ObservationWrapper):
    def __init__(self, env):
        super().__init__(env)

    def step(self, a):
        pass

    def _get_obs(self):
        pass

    def relabel_ob(self):
        pass

    def is_reached(self):
        pass

    def reset_model(self):
        return self._get_obs()

    def propose_original(self):
        pass

    def viewer_setup(self):
        pass

    def touching(self):
        pass

    def seed(self):
        pass
