"""Validate declared machine-checkable goal requirements without inventing them."""
OPERATORS = {'equals', 'not_equals', 'exists', 'contains', 'changed'}
RULE_FIELDS = OPERATORS | {'section', 'probe', 'step_id', 'before_section', 'requirement_id'}


def validate_rule(rule):
    if (not isinstance(rule, dict) or not isinstance(rule.get('section'), str)
            or not rule['section'].strip() or set(rule)-RULE_FIELDS):
        raise ValueError('invalid_verification_rule')
    if any(name in rule and (not isinstance(rule[name], str) or not rule[name].strip())
           for name in ('step_id', 'before_section', 'requirement_id')):
        raise ValueError('invalid_verification_rule')
    operators = OPERATORS & rule.keys()
    if len(operators) != 1:
        raise ValueError('exactly_one_verification_operator_required')
    if any(name in rule and rule[name] is not True for name in ('exists', 'changed')):
        raise ValueError('invalid_verification_operator_value')
    if 'probe' in rule and (not isinstance(rule['probe'], dict) or
            rule['probe'].get('type') not in {'server_file', 'document_content', 'companion'}):
        raise ValueError('unsupported_observation_probe')


def requirement_coverage(requirements, checks):
    if not isinstance(checks, list):raise ValueError('invalid_completion_checks')
    for check in checks:validate_rule(check)
    if not isinstance(requirements, list) or any(not isinstance(r, dict) or
            not isinstance(r.get('id'), str) or not r['id'].strip() or
            not isinstance(r.get('description'), str) or not r['description'].strip() for r in requirements):
        raise ValueError('invalid_goal_requirements')
    ids = [r['id'] for r in requirements]
    if len(set(ids)) != len(ids):raise ValueError('duplicate_goal_requirement')
    linked = {c['requirement_id'] for c in checks if c.get('requirement_id') is not None}
    if linked-set(ids):raise ValueError('unknown_goal_requirement')
    if set(ids)-linked:raise ValueError('goal_requirement_without_final_check')
    return {'declared': len(ids), 'covered': len(linked), 'semantic_completeness_verified': False}
