"""LibYAML source-span adapter, checked against the ruamel reference backend.

Comment characters are recognized only in gaps outside ALL scanner tokens;
quoted/plain/block scalars and tags therefore cannot produce false comments.
Node scalar values are kept as raw strings, never constructed/resolved to bool.
Any scan/compose failure falls back to the reference parser for partial recovery.
"""
import yaml
from yaml_comments import ParsedYaml, _merge, populate_nodes, parse_yaml, comments_from_tokens


def parse_yaml_fast(source):
    if '\t' in source:
        return parse_yaml(source)
    try:
        tokens=list(yaml.scan(source,Loader=yaml.CSafeLoader))
        root=yaml.compose(source,Loader=yaml.CSafeLoader)
    except (yaml.YAMLError,RecursionError,ValueError):
        return parse_yaml(source)
    result=ParsedYaml(source)
    comments=comments_from_tokens(source,tokens)
    result.comments=_merge(comments,source)
    return populate_nodes(result,root)
