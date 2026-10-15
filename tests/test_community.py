"""Public result validation uses offline fixtures, never a live model score."""
import copy
import json
from pathlib import Path

import pytest

from sixcat import community as c
from sixcat import community_export as e
from sixcat.manifest import fingerprint
from tests.test_reliability_v06 import endpoint, run_fixture

@pytest.fixture(scope='session')
def reference_result(tmp_path_factory):
    path = tmp_path_factory.mktemp('community-reference')/'run.jsonl'
    with endpoint(delay=.001) as (url, state):
        result = run_fixture(path, url, seconds=45)
    assert result['complete']
    return result

@pytest.fixture
def raw_result(reference_result):
    return copy.deepcopy(reference_result)

@pytest.fixture
def public_doc(raw_result):
    return e.make_public(raw_result, contributor='fixture-user', metadata=e.default_metadata(raw_result),
                         run_at='2026-10-15T12:00:00Z', original_sha256='e'*64)


def resign(doc):
    doc['run_id'] = e.run_identity(doc['result'])
    doc['content_sha256'] = fingerprint({k:v for k,v in doc.items() if k != 'content_sha256'})
    return doc


def test_export_preserves_scores_and_strips_private_metadata(raw_result, public_doc):
    assert public_doc['result']['categories'] == raw_result['categories']
    assert public_doc['result']['items']['code'][0]['raw_text'] == raw_result['items']['code'][0]['raw_text']
    assert sum(public_doc['result']['n'].values()) == 120
    for key in ('base_url','server_props','log','diagnostics'):
        assert key not in public_doc['result']
    assert all('wire_request' not in r and 'reasoning_content' not in r for rows in public_doc['result']['items'].values() for r in rows)
    c.validate_result(public_doc['result'])
    e.validate_public(public_doc)


def test_low_scores_and_completed_truncations_are_eligible(raw_result):
    # Wrong answers are not infrastructure errors; the fixture naturally has low categories.
    assert min(raw_result['categories'].values()) < 100
    c.validate_result(raw_result)
    raw_result['items']['code'][0]['finish'] = 'length'
    c.validate_result(raw_result)


@pytest.mark.parametrize('field,value', [('complete',False),('timed_out',True),('limit',10),
    ('limit_scope','per_dataset'),('code_execution','disabled'),('policy_probe','failed'),
    ('transport','stdio'),('errors',[{'status':'error'}]),('attempt_policy','latest'),('parser','v4'),
    ('concurrency',0),('concurrency',True),('execution_segments',[])])
def test_ineligible_results_cannot_publish(raw_result, field, value):
    raw_result[field]=value
    with pytest.raises(c.SubmissionError): c.validate_result(raw_result)


def test_unknown_benchmark_and_forged_policy_rejected(raw_result):
    raw_result['benchmark_manifest']['tools_sha256']='a'*64
    manifest=raw_result['benchmark_manifest']
    manifest['fingerprint']=fingerprint({k:v for k,v in manifest.items() if k!='fingerprint'})
    raw_result['benchmark_fingerprint']=manifest['fingerprint']
    with pytest.raises(c.SubmissionError,match='approved'): c.validate_result(raw_result)


@pytest.mark.parametrize('change', ['score','count','duplicate','policy','budget','raw_missing','nested'])
def test_public_tampering_even_with_recomputed_checksum(public_doc,change):
    r=public_doc['result']
    if change=='score': r['categories']['code']=1.0
    if change=='count': r['n']['code']=19
    if change=='duplicate': r['items']['code'][1]['key']=r['items']['code'][0]['key']
    if change=='policy': r['policy']['temperature']=0.9
    if change=='budget': r['budgets']['code']+=1
    if change=='raw_missing': r['items']['code'][0].pop('raw_text')
    if change=='nested': r['items']['code'][0]['request_params']['private-note']='bad'
    resign(public_doc)
    with pytest.raises(c.SubmissionError): e.validate_public(public_doc)


@pytest.mark.parametrize('bad', ['{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}','[', '"'+('x'*(1024*1024+1))+'"'])
def test_strict_json_rejects_invalid_data(bad):
    with pytest.raises(c.SubmissionError): c.strict_json(bad)


def test_nested_and_oversize_limits():
    with pytest.raises(c.SubmissionError): c.strict_json('['*35+'0'+']'*35)
    with pytest.raises(c.SubmissionError): c.strict_json(' '* (c.MAX_BYTES+1))
    with pytest.raises(c.SubmissionError): c.check_tree(float('inf'))
    with pytest.raises(c.SubmissionError): c.check_tree(object())


@pytest.mark.parametrize('field', ['base_url','headers','api_key','profile','log'])
def test_unexpected_public_private_fields_are_rejected(public_doc,field):
    public_doc['result'][field]='private-value'
    resign(public_doc)
    with pytest.raises(c.SubmissionError): e.validate_public(public_doc)


def test_recognizable_credentials_in_answers_require_review(public_doc):
    public_doc['result']['items']['code'][0]['raw_text']='Bearer ' + 'x'*30
    resign(public_doc)
    with pytest.raises(c.SubmissionError,match='credential'): e.validate_public(public_doc)


def test_reasoning_opt_in_and_run_identity(raw_result,public_doc):
    with_reasoning=e.make_public(raw_result,contributor='fixture-user',metadata=e.default_metadata(raw_result),
        run_at=public_doc['run_at'],original_sha256='e'*64,include_reasoning=True)
    assert with_reasoning['run_id']==public_doc['run_id']
    assert 'reasoning_content' in with_reasoning['result']['items']['code'][0]
    assert with_reasoning['export']['reasoning_included']
    with_reasoning['export']['reasoning_included']=False; resign(with_reasoning)
    with pytest.raises(c.SubmissionError,match='Undisclosed'): e.validate_public(with_reasoning)


def test_paths_hashes_and_duplicates(public_doc):
    path=e.result_path(public_doc)
    assert path.startswith('community/results/2026/10/') and 'fixture-user__20261015T120000Z__' in path
    assert '/' not in Path(path).name
    assert e.validate_collection([(path,public_doc)])==[public_doc]
    with pytest.raises(c.SubmissionError,match='Duplicate'): e.validate_collection([(path,public_doc)]*2)
    with pytest.raises(c.SubmissionError,match='filename'): e.validate_collection([('other.json',public_doc)])
    public_doc['content_sha256']='0'*64
    with pytest.raises(c.SubmissionError,match='checksum'): e.validate_public(public_doc)


@pytest.mark.parametrize('field,value', [('model_url','http://example.com'),('model_url','https://127.0.0.1/a'),
    ('model_url','https://example.com/?key=x'),('model_url','https://x.internal/a'),
    ('model_name','/home/person/private-model'),('source_kind','unknown'),('average_bpw',0),('context_tokens',1.5)])
def test_bad_metadata(public_doc,field,value):
    public_doc['metadata'][field]=value; resign(public_doc)
    with pytest.raises(c.SubmissionError): e.validate_public(public_doc)


def test_readme_generation_and_escaping(public_doc):
    public_doc['metadata']['model_name']='[model](https://example.com) | <script>'
    resign(public_doc)
    readme='Before\n'+c.START+'\nold\n'+c.END+'\nAfter'
    rendered=e.replace_table(readme,[public_doc])
    assert rendered.startswith('Before') and rendered.endswith('After')
    assert '&lt;script&gt;' in rendered and '&#124;' in rendered
    assert rendered==e.replace_table(rendered,[public_doc])
    assert 'Code' not in e.render_table([])
    with pytest.raises(c.SubmissionError): e.replace_table('no markers',[])


@pytest.mark.parametrize('date',['bad','2026-10-15','1990-01-01T00:00:00Z'])
def test_invalid_date(date):
    with pytest.raises(c.SubmissionError): e.parse_time(date)


def test_diagnostic_retry_segments_do_not_duplicate_first_response_run(public_doc):
    changed = copy.deepcopy(public_doc['result'])
    changed['execution_segments'].append({'id':'diagnostic-only', 'elapsed_s':12})
    changed['concurrency'] = 8
    assert e.run_identity(changed) == public_doc['run_id']
    changed['items']['code'][0]['segment_id'] = 'new-genuine-run'
    assert e.run_identity(changed) != public_doc['run_id']


def test_legacy_hermes_loopback_is_not_misclassified_as_local(raw_result):
    raw_result['server_props']={'openai_models':{'data':[{'id':raw_result['model'],
        'target_kind':'hermes_runtime_model','hermes_provider':'nous','hermes_profile':'private-profile'}]}}
    meta=e.default_metadata(raw_result)
    assert meta['source_kind']=='cloud' and meta['source']=='nous'
    assert 'private-profile' not in json.dumps(meta)


def test_private_provider_model_path_is_omitted_without_editing_answers(raw_result):
    raw_result['items']['code'][0]['provider_model']='/home/private/model'
    projected=e.project_result(raw_result)
    assert 'provider_model' not in projected['items']['code'][0]
    assert projected['items']['code'][0]['raw_text']==raw_result['items']['code'][0]['raw_text']
