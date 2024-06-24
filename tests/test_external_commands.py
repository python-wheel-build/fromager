import pathlib

from fromager import external_commands


def test_external_commands_environ():
    env = {"BLAH": "test"}
    output = external_commands.run(["sh", "-c", "echo $BLAH"], extra_environ=env)
    assert "test\n" == output


def test_external_commands_log_file(tmp_path):
    log_filename = pathlib.Path(tmp_path) / "test.log"
    env = {"BLAH": "test"}
    output = external_commands.run(
        ["sh", "-c", "echo $BLAH"],
        extra_environ=env,
        log_filename=log_filename,
    )
    assert "test\n" == output
    assert log_filename.exists()
    file_contents = log_filename.read_text()
    assert "test\n" == file_contents
