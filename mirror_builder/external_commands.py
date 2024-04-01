import logging
import os
import shlex
import subprocess

logger = logging.getLogger(__name__)


# based on pyproject_hooks/_impl.py: quiet_subprocess_runner
def run(cmd, cwd=None, extra_environ=None):
    """Call the subprocess while logging output
    """
    env = os.environ.copy()
    if extra_environ:
        env.update(extra_environ)

    logger.debug('running: %s', ' '.join(shlex.quote(str(s)) for s in cmd))
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout.decode('utf-8') if completed.stdout else ''
    logger.debug('output: %s', output)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, cmd, output)
