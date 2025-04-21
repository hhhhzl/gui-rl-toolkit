from rlf.args import str2bool
from rlf.envs.env_interface import EnvInterface, register_env_interface
from rlf.envs.utils import SepGoal


class GoalAntInterface(EnvInterface):
    def env_trans_fn(self, env, set_eval):
        env.env.spawn_noise = self.args.ant_noise
        env.env.is_expert = self.args.ant_is_expert
        env.env.coverage = self.args.ant_cover

        return env

    def get_add_args(self, parser):
        super().get_add_args(parser)


register_env_interface("GUI-v0", GoalAntInterface)