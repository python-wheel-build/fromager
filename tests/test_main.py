import argparse

import pytest

from mirror_builder import __main__ as main


@pytest.fixture
def parser():
    p = argparse.ArgumentParser()
    p.add_argument('--requirements', '-r')
    p.add_argument('toplevel', nargs='*')
    return p


def test_single_arg(parser):
    args = parser.parse_args(['a'])
    requirements = main._get_requirements_from_args(args)
    assert ['a'] == requirements


def test_multiple_args(parser):
    args = parser.parse_args(['a', 'b'])
    requirements = main._get_requirements_from_args(args)
    assert ['a', 'b'] == requirements


def test_requirements_file(parser, tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('c\n')
    args = parser.parse_args(['-r', str(requirements_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['c'] == requirements


def test_file_with_comments_and_blanks(parser, tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('a\n\n# ignore\nb\nc\n')
    args = parser.parse_args(['-r', str(requirements_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['a', 'b', 'c'] == requirements


def test_args_and_file(parser, tmp_path):
    requirements_file = tmp_path / 'requirements.txt'
    requirements_file.write_text('c\n')
    args = parser.parse_args(['a', 'b', '-r', str(requirements_file)])
    requirements = main._get_requirements_from_args(args)
    assert ['a', 'b', 'c'] == requirements
