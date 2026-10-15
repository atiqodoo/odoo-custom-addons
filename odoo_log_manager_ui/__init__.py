from . import models


def post_init_hook(env):
    env["log.manager.source"].sudo().action_discover_sources()
