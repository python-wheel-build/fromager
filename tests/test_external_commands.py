import subprocess

from mirror_builder import external_commands


def test_external_commands_environ():
    env = { "BLAH": "test" }
    output = external_commands.run([ "sh", "-c", "echo $BLAH" ], extra_environ=env)
    assert "test\n" == output
