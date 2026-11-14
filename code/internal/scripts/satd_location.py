"""User-defined YAML location rules. Never filters a SATD candidate."""
import re


def locate_comment(block, parsed) -> tuple[str, str]:
    nodes = parsed.nodes
    by_path = {n.path: n for n in nodes if n.reliable}
    if block.kind == 'script':
        return (block.owner, 'script_run') if block.owner else ('unknown', 'ambiguous_script_owner')
    reliable = [n for n in nodes if n.reliable]

    def parent_path(path):
        n = by_path.get(path)
        return n.parent if n else ''

    def chain(path):
        out = []
        while path:
            out.append(path)
            path = parent_path(path)
        return out

    def boundary(node):
        siblings = [n.line for n in nodes if n.parent == node.parent and n.line > node.line]
        if siblings:
            return min(siblings)
        parent = by_path.get(node.parent)
        return boundary(parent) if parent else len(parsed.source.splitlines())+1

    # A containing scope must precede the comment and have matching indentation.
    scopes = []
    for n in reliable:
        is_job = n.parent == 'jobs'
        is_item = bool(re.search(r'\[\d+\]$', n.path))
        if (n.kind in ('mapping','sequence') or is_job):
            indent_ok = block.column >= n.column if is_item else block.column > n.column
            if n.line < block.line_start < boundary(n) and indent_ok:
                scopes.append(n)
    scopes.sort(key=lambda n: (len(chain(n.path)),n.column,n.line), reverse=True)
    fallback = (scopes[0].path, 'containing_scope') if scopes else ('unknown', 'no_reliable_target')

    if block.inline:
        current = [n for n in nodes if n.line == block.line_start and n.column < block.column]
        if any(not n.reliable for n in current):
            return fallback
        if current:
            paths = [chain(n.path) for n in current]
            # Select the deepest field if all other same-line nodes are ancestors.
            deepest = max(paths, key=len)
            leaves = [n for n in current if not any(n.path in chain(m.path)[1:] for m in current)]
            if len(leaves) == 1:
                return leaves[0].path, 'inline_field'
            common = set.intersection(*(set(p) for p in paths))
            if common:
                return next(p for p in deepest if p in common), 'inline_container'
        return fallback

    following = [n for n in nodes if n.line == block.line_end+1]
    if block.column == 0:
        targets = [n for n in following if n.parent == '' and n.column == 0 and n.reliable]
        return (targets[0].path, 'adjacent_top_level') if len(targets)==1 else ('unknown', 'unattached_top_level')

    job = next((n for n in scopes if n.parent == 'jobs'), None)
    if job and re.search(r'\b(?:rewrite|refactor|rework|redesign)\s+(?:this|the|whole|entire)\s+job\b', block.body.lower()):
        return job.path, 'explicit_whole_job'
    # A comment before a dash refers to the list item, not its first field.
    items = [n for n in following if n.reliable and re.search(r'\[\d+\]$',n.path) and n.column == block.column+2]
    if len(items) == 1:
        return items[0].path, 'adjacent_sequence_item'
    targets = [n for n in following if n.reliable and n.column == block.column]
    if len(targets) == 1:
        return targets[0].path, 'adjacent_field'
    return fallback
