import ast
from pathlib import Path
import re
from build_satd_comments import match_keywords, normalize_text, make_comment_id, load_keywords
from yaml_comments import CommentBlock

ROOT=Path(__file__).resolve().parents[1]


def test_matching_is_identical_to_upstream_expression():
    source=(ROOT/'reference/SATDinBuildSystems/Scripts/identify_SATD_comments.py').read_text()
    tree=ast.parse(source)
    original=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='keywords' for t in n.targets))
    expression=compile(ast.Expression(original),'upstream-expression','eval')
    words=load_keywords()
    assert len(words)==len(set(words))==73
    texts=[w.upper() for w in words]+['prefix suffix','TODO workaround FIXME', 'temporary\nsolution', "don’t use this", "don't use this", 'todo_item','TODO: 中文']
    for text in texts:
        expected=eval(expression,{'re':re,'keywords_debt':words,'comment':text})
        assert match_keywords(text,words)==expected
    assert match_keywords('prefix',words)==[]
    assert match_keywords('temporary\nsolution',words)==[]


def test_normalization_does_not_affect_matches_or_id():
    words=load_keywords()
    assert normalize_text('  Temporary\n solution  ')=='temporary solution'
    assert match_keywords('  Temporary\n solution  ',words)==[]
    block=CommentBlock('# TODO',' TODO',1,1,0)
    assert make_comment_id('a'*64,block)==make_comment_id('a'*64,block)
    assert make_comment_id('a'*64,block)!=make_comment_id('b'*64,block)
