import pytest
from yaml_comments import parse_yaml, extract_comments
from fast_yaml import parse_yaml_fast


@pytest.mark.parametrize('s',[
    '# TODO top\non: push # fix inline\n',
    'name: "中文 # TODO string" # FIXME real\n',
    "name: 'can''t # TODO string' # TODO real\n",
    '# TODO first\r\n# second\r\n\non: push\r\n',
    'jobs:\n  test:\n    steps:\n    # TODO step\n    - run: |\n        # TODO shell\n        echo ok\n',
    'env: {A: "# TODO string", B: value} # workaround\n',
    'name: plain#not-comment\n# TODO real\n',
    'env: &vars\n  A: one # TODO anchor\njobs:\n  test:\n    env: *vars\n',
    'jobs:\n  test:\n    runs-on: linux # TODO duplicate\n    runs-on: windows\n',
    '# TODO keep\njobs: [}\n',
    '# TODO comment-only\n',
    'text: | # TODO header\n  value\n\n# TODO first\n# second\nnext: value\n',
])
def test_fast_and_reference_extract_identical_comments_and_nodes(s):
    a=parse_yaml(s);b=parse_yaml_fast(s)
    assert extract_comments(a)==extract_comments(b)
    def shape(p):
        return [(n.path,n.parent,n.line,n.column,n.end_line,n.kind,n.style,n.scalar_line,n.reliable)
                for n in p.nodes]
    assert shape(a)==shape(b)


@pytest.mark.parametrize('newline',['\r','\r\n','\x85','\u2028','\u2029'])
def test_yaml_line_breaks_preserve_source_line_numbers(newline):
    s=newline.join(['# TODO first','name: example','# FIXME second','on: push',''])
    for parser in (parse_yaml,parse_yaml_fast):
        cs,_=extract_comments(parser(s))
        assert [(c.comment_text,c.line_start) for c in cs]==[('# TODO first',1),('# FIXME second',3)]
