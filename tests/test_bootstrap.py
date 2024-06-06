import textwrap

from fromager.commands import bootstrap


def test_get_requirements_single_arg():
    requirements = bootstrap._get_requirements_from_args(['a'], [])
    assert ['a'] == requirements


def test_get_requirements_multiple_args():
    requirements = bootstrap._get_requirements_from_args(['a', 'b'], [])
    assert ['a', 'b'] == requirements


def test_get_requirements_requirements_file(tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('c\n')
    requirements = bootstrap._get_requirements_from_args([], [requirements_file])
    assert ['c'] == requirements


def test_get_requirements_requirements_file_comments(tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text(
        textwrap.dedent('''
        c
        d # with comment
        # ignore comment

        '''),
    )
    requirements = bootstrap._get_requirements_from_args([], [requirements_file])
    assert ['c', 'd'] == requirements


def test_get_requirements_requirements_file_multiple(tmp_path):
    requirements1_file = tmp_path / 'requirements1.txt'
    requirements1_file.write_text('a\n')
    requirements2_file = tmp_path / 'requirements2.txt'
    requirements2_file.write_text('b\n')
    requirements = bootstrap._get_requirements_from_args([], [requirements1_file, requirements2_file])
    assert ['a', 'b'] == requirements


def test_get_requirements_file_with_comments_and_blanks(tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('a\n\n# ignore\nb\nc\n')
    requirements = bootstrap._get_requirements_from_args([], [requirements_file])
    assert ['a', 'b', 'c'] == requirements


def test_get_requirements_args_and_file(tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('c\n')
    requirements = bootstrap._get_requirements_from_args(['a', 'b'], [requirements_file])
    assert ['a', 'b', 'c'] == requirements
