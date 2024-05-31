import textwrap

import pytest

from fromager import __main__ as main


@pytest.fixture
def parser():
    return main._get_argument_parser()


def test_get_requirements_single_arg(parser):
    args = parser.parse_args(['bootstrap', 'a'])
    requirements = main._get_requirements_from_args(args)
    assert ['a'] == requirements


def test_get_requirements_multiple_args(parser):
    args = parser.parse_args(['bootstrap', 'a', 'b'])
    requirements = main._get_requirements_from_args(args)
    assert ['a', 'b'] == requirements


def test_get_requirements_requirements_file(parser, tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('c\n')
    args = parser.parse_args(['bootstrap', '-r', str(requirements_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['c'] == requirements


def test_get_requirements_requirements_file_comments(parser, tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text(
        textwrap.dedent('''
        c
        d # with comment
        # ignore comment

        '''),
    )
    args = parser.parse_args(['bootstrap', '-r', str(requirements_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['c', 'd'] == requirements


def test_get_requirements_requirements_file_multiple(parser, tmp_path):
    requirements1_file = tmp_path / 'requirements1.txt'
    requirements1_file.write_text('a\n')
    requirements2_file = tmp_path / 'requirements2.txt'
    requirements2_file.write_text('b\n')
    args = parser.parse_args(['bootstrap', '-r', str(requirements1_file), '-r', str(requirements2_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['a', 'b'] == requirements


def test_get_requirements_file_with_comments_and_blanks(parser, tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('a\n\n# ignore\nb\nc\n')
    args = parser.parse_args(['bootstrap', '-r', str(requirements_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['a', 'b', 'c'] == requirements


def test_get_requirements_args_and_file(parser, tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('c\n')
    args = parser.parse_args(['bootstrap', 'a', 'b', '-r', str(requirements_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['a', 'b', 'c'] == requirements
