import pytest
from yaml_comments import parse_yaml, extract_comments
from satd_location import locate_comment


def locations(source):
    p=parse_yaml(source)
    cs,_=extract_comments(p)
    return [locate_comment(c,p)[0] for c in cs]


@pytest.mark.parametrize('key',['on','env','jobs'])
def test_top_level_attaches_to_adjacent_field(key):
    assert locations(f'# TODO: 修改触发条件\n{key}: {{}}\n')==[key]


def test_inline_preceding_script_and_whole_job():
    s='''jobs:
  test:
    # TODO: rewrite this job
    runs-on: ubuntu-latest # TODO support Windows
    steps:
      - name: test
        # TODO pin commit
        uses: actions/checkout@main
      - run: |
          # TODO remove workaround
          npm test
'''
    assert locations(s)==['jobs.test','jobs.test.runs-on','jobs.test.steps[0].uses','jobs.test.steps[1].run']


def test_coarse_and_unknown_locations():
    assert locations('# TODO detached\n\non: push\n')==['unknown']
    assert locations('jobs:\n  test:\n    # TODO unclear\n\n    runs-on: ubuntu-latest\n')==['jobs.test']
    assert locations('jobs:\n  test:\n    # TODO: rewrite this job\n')==['jobs.test']
    assert locations('# TODO keep\njobs: [}\n')==['unknown']


def test_list_item_boundary_and_escaped_keys():
    s='''jobs:
  test.unit:
    steps:
      # TODO step
      - uses: a/b@main
      # TODO next step
      - uses: c/d@main
'''
    assert locations(s)==['jobs["test.unit"].steps[0]','jobs["test.unit"].steps[1]']


def test_duplicate_target_falls_back_to_job():
    s='jobs:\n  test:\n    runs-on: ubuntu # TODO keep\n    runs-on: windows\n'
    assert locations(s)==['jobs.test']
