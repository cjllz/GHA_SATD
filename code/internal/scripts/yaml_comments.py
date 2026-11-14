"""YAML/source-location adapter; this component is new, not upstream SATD logic."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
from bisect import bisect_right

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.deps'))
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.tokens import CommentToken


@dataclass
class CommentBlock:
    comment_text: str
    body: str
    line_start: int
    line_end: int
    column: int
    kind: str = 'yaml'
    owner: str | None = None
    inline: bool = False


@dataclass
class NodeInfo:
    path: str
    parent: str
    line: int
    column: int
    end_line: int
    kind: str
    value: object
    style: str | None = None
    scalar_line: int = 0
    reliable: bool = True


@dataclass
class ParsedYaml:
    source: str
    nodes: list[NodeInfo] = field(default_factory=list)
    comments: list[CommentBlock] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def issue(reason, line=0, detail=''):
    return {'reason': reason, 'line': line, 'detail': str(detail)[:800]}


def _path(parent, key):
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', key):
        return (parent + '.' if parent else '') + key
    return parent + '[' + json.dumps(key, ensure_ascii=False) + ']'


def _comment_tokens(value):
    if isinstance(value, CommentToken):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _comment_tokens(item)


def _merge(comments, source):
    lines = source.splitlines(keepends=True)
    result = []
    seen = set()
    for c in sorted(comments, key=lambda c: (c.line_start, c.column)):
        key = (c.line_start, c.column, c.line_end, c.comment_text)
        if key in seen:
            continue
        seen.add(key)
        if (result and not c.inline and not result[-1].inline
                and result[-1].line_end + 1 == c.line_start
                and result[-1].column == c.column
                and result[-1].kind == c.kind and result[-1].owner == c.owner):
            prev = result[-1]
            prev.line_end = c.line_end
            raw = ''.join(lines[prev.line_start-1:prev.line_end])
            prev.comment_text = raw[prev.column:].rstrip('\r\n\x85\u2028\u2029')
            prev.body += '\n' + c.body
        else:
            result.append(c)
    return result


def comments_from_tokens(source, tokens, complete=True):
    """Read # only outside lexical tokens, plus block-scalar header comments."""
    breaks=list(re.finditer(r'\r\n|[\r\n\x85\u2028\u2029]',source))
    starts=[0]+[m.end() for m in breaks]
    ends=[m.start() for m in breaks]+[len(source)]
    comments=[]
    previous=0
    def gap(start,end):
        while (index:=source.find('#',start,end))!=-1:
            row=bisect_right(starts,index)-1
            stop=min(ends[row],end)
            raw=source[index:stop]
            col=index-starts[row]
            comments.append(CommentBlock(raw,raw[1:],row+1,row+1,col,
                                         inline=bool(source[starts[row]:index].strip())))
            start=stop+1
    for token in tokens:
        gap(previous,token.start_mark.index)
        if getattr(token,'style',None) in ('|','>'):
            end=ends[bisect_right(starts,token.start_mark.index)-1]
            gap(token.start_mark.index,min(end,token.end_mark.index))
        previous=max(previous,token.end_mark.index)
    if complete:gap(previous,len(source))
    return comments


def parse_yaml(source: str) -> ParsedYaml:
    result = ParsedYaml(source)
    lines = source.splitlines(keepends=True)
    tokens = []
    parser = YAML(typ='rt', pure=True)
    parser.version = (1, 2)
    try:
        for token in parser.scan(source):
            tokens.append(token)
    except (YAMLError, RecursionError, ValueError, NotImplementedError, AssertionError) as exc:
        result.issues.append(issue('yaml_scan_error', detail=exc))
    comments = []
    for token in tokens:
        for ct in _comment_tokens(getattr(token, 'comment', None)):
            start = ct.start_mark.line
            for offset, _ in enumerate(ct.value.splitlines()):
                row = start + offset
                if row >= len(lines):
                    continue
                text = lines[row].rstrip('\r\n\x85\u2028\u2029')
                col = ct.start_mark.column if offset == 0 else len(text)-len(text.lstrip())
                if not text[col:].startswith('#') and text.lstrip().startswith('#'):
                    col = len(text)-len(text.lstrip())
                if text[col:col+1] != '#':
                    continue
                raw = text[col:]
                comments.append(CommentBlock(raw, raw[1:], row+1, row+1, col,
                                             inline=bool(text[:col].strip())))
    # Source gaps avoid ruamel's normalized/moved comment metadata dropping
    # blank-line-prefixed or scalar-header comments. Metadata still recovers
    # reliable comments attached to the last token of an interrupted scan.
    if not result.issues:
        comments = comments_from_tokens(source,tokens)
    else:
        comments += comments_from_tokens(source,tokens,complete=False)
    result.comments = _merge(comments, source)
    parser = YAML(typ='rt', pure=True)
    parser.version = (1, 2)
    try:
        root = parser.compose(source)
    except (YAMLError, RecursionError, ValueError, NotImplementedError, AssertionError) as exc:
        result.issues.append(issue('yaml_tree_error', detail=exc))
        return result
    return populate_nodes(result, root)


def populate_nodes(result, root):
    if root is None:
        return result
    seen = set()

    def walk(node, path='', parent='', keymark=None, reliable=True):
        if id(node) in seen:
            return  # aliases do not create new physical source comments
        seen.add(id(node))
        mark = keymark or node.start_mark
        if path:
            result.nodes.append(NodeInfo(path, parent, mark.line+1, mark.column,
                                         node.end_mark.line+1, node.id, node.value,
                                         getattr(node, 'style', None) or None, node.start_mark.line+1, reliable))
        if node.id == 'mapping':
            keys = [k.value for k, v in node.value if k.id == 'scalar']
            duplicates = {k for k in keys if keys.count(k) > 1}
            for key, value in node.value:
                if key.id != 'scalar':
                    result.issues.append(issue('complex_key', key.start_mark.line+1))
                    continue
                child = _path(path, key.value)
                if key.value in duplicates:
                    result.issues.append(issue('duplicate_key', key.start_mark.line+1, child))
                walk(value, child, path, key.start_mark, reliable and key.value not in duplicates)
        elif node.id == 'sequence':
            for i, child in enumerate(node.value):
                walk(child, f'{path}[{i}]', path, reliable=reliable)
    try:
        walk(root)
    except RecursionError as exc:
        result.nodes.clear()
        result.issues.append(issue('yaml_tree_error', detail=exc))
    return result


_bash_parser = None
_powershell = None


def _shell(parsed, run):
    nodes = {n.path: n for n in parsed.nodes if n.reliable}
    job = run.path.split('.steps', 1)[0]
    for path in (run.parent+'.shell', job+'.defaults.run.shell', 'defaults.run.shell'):
        n = nodes.get(path)
        if n and n.kind == 'scalar':
            word = n.value.split()[0].lower() if n.value.strip() else ''
            return {'bash':'bash', 'sh':'bash', 'python':'python', 'pwsh':'pwsh', 'powershell':'pwsh'}.get(word)
    runner = nodes.get(job+'.runs-on')
    values = []
    if runner:
        values = [str(runner.value)] if runner.kind == 'scalar' else [str(n.value) for n in parsed.nodes if n.parent == runner.path and n.kind == 'scalar']
    if any(re.fullmatch(r'windows-[\w.-]+', v) for v in values):
        return 'pwsh'
    if any(re.fullmatch(r'(ubuntu|macos)-[\w.-]+', v) for v in values):
        return 'bash'
    # A container job defaults to sh. Unknown/matrix/self-hosted OS is not guessed.
    if job+'.container' in nodes:
        return 'bash'
    return None


def _script_ranges(script, shell):
    """Return (0-based row, codepoint column, end row, end column) ranges."""
    global _bash_parser, _powershell
    # GitHub expands these before invoking the shell. Mask only for syntax
    # recognition, preserving every character position and newline. Match SATD
    # against the untouched source after projecting comment spans back to YAML.
    chars = list(script)
    start = 0
    while (start := script.find('${{', start)) != -1:
        pos = start+3
        quoted = False
        while pos < len(script):
            if script[pos] == "'":
                if quoted and script[pos:pos+2] == "''":
                    pos += 2
                    continue
                quoted = not quoted
            if not quoted and script[pos:pos+2] == '}}':
                end = pos+2
                for index in range(start,end):
                    if chars[index] not in '\r\n':
                        chars[index] = 'x'
                start = end
                break
            pos += 1
        else:
            raise ValueError('Unterminated GitHub expression')
    script = ''.join(chars)
    if shell == 'bash':
        from tree_sitter import Language, Parser
        import tree_sitter_bash
        if _bash_parser is None:
            _bash_parser = Parser(Language(tree_sitter_bash.language()))
        data = script.encode('utf-8')
        tree = _bash_parser.parse(data)
        if tree.root_node.has_error:
            raise ValueError('Bash parse error; script comments not inferred')
        found = []
        stack = [tree.root_node]
        rows = script.splitlines()
        while stack:
            node = stack.pop()
            if node.type == 'heredoc_body':
                continue
            if node.type == 'comment':
                sr, sc = node.start_point; er, ec = node.end_point
                found.append((sr, len(rows[sr].encode()[:sc].decode()), er, len(rows[er].encode()[:ec].decode())))
            else:
                stack.extend(reversed(node.children))
        return found
    if shell == 'python':
        return [(t.start[0]-1,t.start[1],t.end[0]-1,t.end[1])
                for t in tokenize.generate_tokens(io.StringIO(script).readline) if t.type == tokenize.COMMENT]
    if shell == 'pwsh':
        if _powershell is None or _powershell.poll() is not None:
            exe = shutil.which('pwsh') or shutil.which('powershell')
            if not exe:
                raise ValueError('PowerShell parser unavailable')
            _powershell = subprocess.Popen([exe,'-NoLogo','-NoProfile','-NonInteractive','-File',str(Path(__file__).with_name('pwsh_comments.ps1'))],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        _powershell.stdin.write(json.dumps(script,ensure_ascii=True)+'\n'); _powershell.stdin.flush()
        response = json.loads(_powershell.stdout.readline())
        if response.get('error'):
            raise ValueError(response['error'])
        rows = script.splitlines()
        def col(row, n):
            return len(rows[row].encode('utf-16-le')[:n*2].decode('utf-16-le'))
        return [(a-1,col(a-1,b-1),c-1,col(c-1,d-1)) for a,b,c,d in response['ranges']]
    raise ValueError('unsupported shell')


def extract_comments(parsed: ParsedYaml):
    comments = list(parsed.comments)
    issues = []
    lines = parsed.source.splitlines(keepends=True)
    for n in parsed.nodes:
        if not n.path.endswith('.run') or '.steps[' not in n.path or n.kind != 'scalar' or '#' not in str(n.value):
            continue
        if n.style != '|':
            issues.append(issue('unsupported_run_scalar_style', n.line, n.path))
            continue
        shell = _shell(parsed, n)
        if not shell:
            issues.append(issue('unsupported_shell', n.line, n.path))
            continue
        try:
            ranges = _script_ranges(n.value, shell)
            raw_rows = lines[n.scalar_line:n.end_line-1]
            nonempty = [len(s)-len(s.lstrip(' ')) for s in raw_rows if s.strip()]
            indent = min(nonempty) if nonempty else 0
            for sr, sc, er, ec in ranges:
                first, last = n.scalar_line+sr, n.scalar_line+er
                if first == last:
                    raw = lines[first][indent+sc:indent+ec]
                else:
                    raw = lines[first][indent+sc:] + ''.join(lines[first+1:last]) + lines[last][:indent+ec]
                body = raw[2:-2] if raw.startswith('<#') and raw.endswith('#>') else raw[1:]
                comments.append(CommentBlock(raw,body,first+1,last+1,indent+sc,'script',n.path if n.reliable else None,
                                             bool(lines[first][indent:indent+sc].strip())))
        except (ValueError, tokenize.TokenError, IndentationError, OSError, EOFError) as exc:
            issues.append(issue('script_parse_error', n.line, f'{n.path}: {exc}'))
    return _merge(comments, parsed.source), issues
