from yaml_comments import parse_yaml, extract_comments


def blocks(source):
    return extract_comments(parse_yaml(source))[0]


def test_comment_tokens_and_source_lines():
    source = '# TODO 顶层\r\n# workaround\r\non: push # FIXME trigger\r\nname: "# TODO not a comment"\r\n\r\n# TODO tail\r\n'
    cs = blocks(source)
    assert [(c.line_start,c.line_end) for c in cs] == [(1,2),(3,3),(6,6)]
    assert cs[0].comment_text == '# TODO 顶层\r\n# workaround'
    assert cs[1].comment_text == '# FIXME trigger'
    assert 'on' in [n.path for n in parse_yaml(source).nodes]


def test_literal_script_comments_not_strings_or_heredoc():
    source = '''jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: |
          # TODO actual
          echo "# TODO string"
          cat <<'EOF'
          # TODO document
          EOF
          echo ok # FIXME inline
'''
    cs = blocks(source)
    assert [c.comment_text for c in cs] == ['# TODO actual','# FIXME inline']
    assert [c.line_start for c in cs] == [6,11]
    assert all(c.owner == 'jobs.test.steps[0].run' for c in cs)


def test_duplicate_keys_and_broken_tree_preserve_reliable_comments():
    p = parse_yaml('jobs:\n  test:\n    runs-on: ubuntu # TODO keep\n    runs-on: windows\n')
    cs, issues = extract_comments(p)
    assert len(cs) == 1 and cs[0].line_start == 3
    assert any(i['reason']=='duplicate_key' for i in p.issues)
    p = parse_yaml('# TODO keep even if tree fails\njobs: [}\n')
    assert blocks(p.source)[0].comment_text == '# TODO keep even if tree fails'
    assert p.issues


def test_python_and_powershell_comments():
    for shell, body in [('python', '# TODO real\nprint("# TODO string")'), ('pwsh', '# TODO real\nWrite-Output "# TODO string"')]:
        s = 'jobs:\n  t:\n    steps:\n      - shell: '+shell+'\n        run: |\n'+''.join('          '+x+'\n' for x in body.splitlines())
        assert [c.comment_text for c in blocks(s)] == ['# TODO real']


def test_unknown_shell_is_reported_not_misclassified():
    p = parse_yaml('jobs:\n  t:\n    steps:\n      - shell: custom {0}\n        run: |\n          # TODO maybe\n')
    cs,issues=extract_comments(p)
    assert cs == []
    assert any(i['reason']=='unsupported_shell' for i in issues)


def test_github_expressions_do_not_break_script_comment_extraction():
    s='''jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: |
          tool --value ${{ secrets.VALUE }}
          # TODO remove workaround
          echo "${{ format('}} {0}', github.ref) }}" # FIXME actual
'''
    cs=blocks(s)
    assert [c.comment_text for c in cs]==['# TODO remove workaround','# FIXME actual']
    assert [c.line_start for c in cs]==[7,8]


def test_comment_before_indentless_sequence_is_preserved():
    s='jobs:\n  test:\n    steps:\n    # python2-pip is broken\n    - name: Install\n      run: echo ok\n'
    assert [c.comment_text for c in blocks(s)]==['# python2-pip is broken']


def test_comment_after_block_scalar_and_blank_line_is_preserved():
    s='text: |\n  value\n\n# TODO first\n# second\nnext: value\n'
    assert [c.comment_text for c in blocks(s)]==['# TODO first\n# second']


def test_literal_header_comment_is_a_yaml_comment():
    s='text: | # TODO header\n  value\n'
    assert [c.comment_text for c in blocks(s)]==['# TODO header']
