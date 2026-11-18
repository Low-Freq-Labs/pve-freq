"""Portable stdlib checks for private authoring journal DATA only.

Case bodies preserve the first reviewed fourteen groups. Import/discovery only
registers tests; it executes no group and acquires no database/provider owner.
"""
import copy
from dataclasses import FrozenInstanceError
import pickle
import unittest

from freq.services import snippet_authoring_journal_data as model

CASES = []


def check(name, function):
    CASES.append((name, function))


def expect_refusal(function):
    try:
        function()
    except model.InvalidSnippetJournalData as error:
        assert str(error) == 'Invalid private authoring journal data'
        return
    raise AssertionError('Expected fixed refusal')


def event(name, persistence='confirmed', **extra):
    return dict(event=name, persistence=persistence, **extra)


# Explicit oracle from accepted contract, not the implementation's _NEXT map.
PATH = ('registered', 'write-intent', 'write-observed', 'readback-intent',
        'readback-verified', 'publication-intent', 'published', 'reply-intent')


def record(names=('registered',)):
    return dict(kind='new-content-authoring', installation_id='fictional-install',
        operation_id='fictional-op', snapshot_id='fictional-snapshot',
        bindings={name: 'fictional-' + name for name in
            ('installation', 'actor', 'storage', 'target', 'writer', 'source', 'lifetime', 'recipient')},
        version=dict(estate_id='fictional-estate', storage_id='fictional-storage',
            storage_incarnation='fictional-storage-epoch', volume_id='fictional-volume',
            content_kind='user', revision='fictional-version', sha256='0' * 64,
            size=0, node_coverage=[]), events=[event(name) for name in names])


def parse(value):
    return model.normalize_authoring_journal_record_data(value)


def append(previous, fact):
    proposed = copy.deepcopy(previous)
    proposed['events'].append(fact)
    return proposed, model.validate_authoring_journal_append_data(previous, proposed)


def normal_graph():
    previous = record()
    for name in PATH[1:]:
        proposed, result = append(previous, event(name))
        assert result.phase == name and not result.uncertain and not result.retired
        assert previous['events'] == proposed['events'][:-1]
        previous = proposed
    for outcome in ('reply-observed', 'reply-unknown'):
        proposed, result = append(previous, event(outcome))
        assert result.phase == outcome
        assert result.uncertain is (outcome == 'reply-unknown')
        for repeated in ('reply-intent', 'reply-observed', 'reply-unknown'):
            changed = copy.deepcopy(proposed)
            changed['events'].append(event(repeated))
            expect_refusal(lambda: parse(changed))


check('authoring graph and alternative reply outcomes without another release', normal_graph)


def phase_skips():
    for index, name in enumerate(PATH):
        value = record(PATH[:index + 1])
        duplicate = copy.deepcopy(value)
        duplicate['events'].append(event(name))
        expect_refusal(lambda: parse(duplicate))
        if index + 2 < len(PATH):
            value['events'].append(event(PATH[index + 2]))
            expect_refusal(lambda: parse(value))


check('skip or repeat required phase refuses', phase_skips)


def no_reply_without_intent():
    for outcome in ('reply-observed', 'reply-unknown'):
        value = record(PATH[:-1])
        value['events'].append(event(outcome))
        expect_refusal(lambda: parse(value))


check('published alone cannot claim a reply outcome', no_reply_without_intent)


def unknown_commits():
    for index, name in enumerate(PATH):
        value = record(PATH[:index])
        value['events'].append(event(name, 'unknown'))
        result = parse(value)
        assert result.uncertain and result.phase == (PATH[index - 1] if index else None)
        for successor in (name, PATH[index + 1] if index + 1 < len(PATH) else 'reply-observed'):
            proposed = copy.deepcopy(value)
            proposed['events'].append(event(successor))
            expect_refusal(lambda: parse(proposed))
        for terminal in ('retire', 'restart'):
            proposed, result = append(value, event(terminal))
            assert result.uncertain
            assert (result.retired if terminal == 'retire' else result.recovery_only)


check('unknown phase commit never advances or retries; pure retirement remains possible', unknown_commits)


def quarantine_boundaries():
    for suffix, attribute in (('retire', 'retired'), ('restart', 'recovery_only')):
        for index in range(len(PATH)):
            value = record(PATH[:index + 1])
            value['events'].append(event(suffix))
            assert getattr(parse(value), attribute)
            for next_name in (suffix, 'write-intent', 'reply-intent', 'reply-observed'):
                proposed = copy.deepcopy(value)
                proposed['events'].append(event(next_name))
                expect_refusal(lambda: parse(proposed))


check('retirement or restart at every prefix bars arming and release', quarantine_boundaries)


def late_evidence():
    value = record(PATH + ('reply-unknown',))
    value, _ = append(value, event('retire'))
    for outcome in ('unknown', 'observed', 'ordinary-failure'):
        value, result = append(value, event('late-outcome', boundary='reply', outcome=outcome))
        assert result.phase == 'reply-unknown' and result.retired and result.uncertain
    duplicate = copy.deepcopy(value)
    duplicate['events'].append(event('late-outcome', boundary='reply', outcome='observed'))
    expect_refusal(lambda: parse(duplicate))
    value['events'].append(event('reply-intent'))
    expect_refusal(lambda: parse(value))
    unsupported = record()
    unsupported['events'] += [event('retire'), event('late-outcome', boundary='reply', outcome='observed')]
    expect_refusal(lambda: parse(unsupported))


check('late classifications retain unknown and retirement without renewed transport', late_evidence)


def ordinary_failure_distinct():
    for prefix, failed in ((PATH[:2], 'write-failed'), (PATH[:4], 'readback-failed'),
                            (PATH[:6], 'publication-failed')):
        value = record(prefix + (failed,))
        result = parse(value)
        assert result.phase == failed and result.uncertain is False
        value['events'].append(event('reply-intent'))
        expect_refusal(lambda: parse(value))


check('observed ordinary failure remains distinct from unknown commit or outcome', ordinary_failure_distinct)


def immutable_metadata():
    previous = record()
    for name in ('installation_id', 'operation_id', 'snapshot_id'):
        proposed = copy.deepcopy(previous)
        proposed[name] = 'different-fictional-token'
        proposed['events'].append(event('write-intent'))
        expect_refusal(lambda: model.validate_authoring_journal_append_data(previous, proposed))
    for name in previous['bindings']:
        proposed = copy.deepcopy(previous)
        proposed['bindings'][name] = 'different-fictional-token'
        proposed['events'].append(event('write-intent'))
        expect_refusal(lambda: model.validate_authoring_journal_append_data(previous, proposed))
    for name, new in (('storage_incarnation', 'different-incarnation'),
                      ('volume_id', 'different-volume'), ('revision', 'different-revision'),
                      ('sha256', '1' * 64), ('size', 1), ('content_kind', 'vendor')):
        proposed = copy.deepcopy(previous)
        proposed['version'][name] = new
        proposed['events'].append(event('write-intent'))
        expect_refusal(lambda: model.validate_authoring_journal_append_data(previous, proposed))


check('all identity bindings and immutable version fields survive append', immutable_metadata)


def predecessor_exact():
    previous = record(PATH[:3])
    for replacement in ([], [event('registered')], previous['events'],
                        previous['events'] + [event('readback-intent'), event('readback-verified')]):
        proposed = copy.deepcopy(previous)
        proposed['events'] = replacement
        expect_refusal(lambda: model.validate_authoring_journal_append_data(previous, proposed))
    previous = record(('registered',))
    previous['events'][0]['persistence'] = 'unknown'
    proposed = record(('registered', 'write-intent'))
    expect_refusal(lambda: model.validate_authoring_journal_append_data(previous, proposed))


check('full predecessor and exactly one append required even when proposed graph itself is valid', predecessor_exact)


class Hostile:
    def __repr__(self):
        raise AssertionError('Opaque repr called')
    __str__ = __repr__
    def __eq__(self, other):
        raise AssertionError('Opaque equality called')
    def __bool__(self):
        raise AssertionError('Opaque truth called')


def kinds_first():
    for kind in ('select-existing', 'recovery', Hostile(), True):
        value = record()
        value['kind'] = kind
        value['events'] = Hostile()
        value['version'] = Hostile()
        expect_refusal(lambda: parse(value))


check('unsupported kind refuses before phase or restricted values', kinds_first)


def names_before_values():
    for name in ('content', 'password', 'path', 'permission', 'success', 'currentness', 'connection'):
        value = record()
        value[name] = Hostile()
        expect_refusal(lambda: parse(value))
        value = record()
        value['events'][0][name] = Hostile()
        expect_refusal(lambda: parse(value))


check('extra secret or authority fields rejected without inspecting values', names_before_values)


def exact_types_and_bounds():
    class Mapping(dict):
        pass
    class Text(str):
        pass
    class Rows(list):
        pass
    expect_refusal(lambda: parse(Mapping(record())))
    for name, value in (('kind', Text('new-content-authoring')), ('installation_id', Hostile()),
                        ('operation_id', 'x' * 129), ('events', Rows([event('registered')])),
                        ('events', []), ('events', [event('registered')] * 33)):
        row = record()
        row[name] = value
        expect_refusal(lambda: parse(row))
    for field in ('event', 'persistence'):
        row = record()
        row['events'][0][field] = Hostile()
        expect_refusal(lambda: parse(row))


check('exact types and finite token/event bounds', exact_types_and_bounds)


def detached_and_hidden():
    original = record()
    result = parse(original)
    original['bindings']['actor'] = 'different'
    original['version']['revision'] = 'different'
    original['events'][0]['event'] = 'different'
    assert result.bindings != tuple(original['bindings'].items())
    assert result.version.revision == 'fictional-version'
    assert result.events[0].event == 'registered'
    for item in (result, result.events[0]):
        assert 'fictional' not in repr(item) and 'registered' not in repr(item)
        try:
            hash(item)
        except TypeError:
            pass
        else:
            raise AssertionError('Unexpected public hash')
        try:
            pickle.dumps(item)
        except TypeError:
            pass
        else:
            raise AssertionError('Unexpected serialization')
    try:
        result.phase = 'published'
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError('Mutable record')
    expect_refusal(lambda: parse(result))


check('detached immutable hidden metadata cannot bypass normalization', detached_and_hidden)


def original_failures():
    class Control(BaseException):
        pass
    original = model.normalize_snippet_reference_data
    for failure in (MemoryError(), Control()):
        def fail(value):
            raise failure
        model.normalize_snippet_reference_data = fail
        try:
            try:
                parse(record())
            except BaseException as caught:
                assert caught is failure
            else:
                raise AssertionError('Original failure disappeared')
        finally:
            model.normalize_snippet_reference_data = original


check('original fixed-normalizer allocation and control failures retain identity', original_failures)


class TestAuthoringJournalData(unittest.TestCase):
    pass


def _as_unittest(function):
    def invoke(self):
        function()
    return invoke


for _index, (_name, _function) in enumerate(CASES, 1):
    _method = _as_unittest(_function)
    _method.__doc__ = _name
    setattr(TestAuthoringJournalData, 'test_%02d' % _index, _method)


if __name__ == '__main__':
    unittest.main()
