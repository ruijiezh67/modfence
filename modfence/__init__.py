"""modfence: see a project as modules, and prompt Claude Code about one module at a time."""
__version__ = "0.3.0"


def fence_for(task, root=None, fence=True):
    """The fence for a task and the text to give the model, for an agent you run yourself (API, Agent SDK)."""
    from .jit import fence_for as f
    return f(task, root, fence)


def check_edit(path, root=None):
    """None if the fence lets this file be written, else the reason to send the model instead."""
    from .jit import check_edit as f
    return f(path, root)
