import subprocess

from mirror_builder import external_commands

def test_external_commands_environ():
    env = { "BLAH": "test" }
    try:
        external_commands.run([ "sh", "-c", "set; exit 1" ], extra_environ=env)
    except subprocess.CalledProcessError as ex:
        assert "BLAH=test" in ex.output
    else:
        assert False and "should not be reached"
