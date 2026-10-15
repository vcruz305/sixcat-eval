import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sixcat import community as c, community_export as e, submit
from sixcat import community_github as g
from tests.test_community import reference_result, raw_result, public_doc


def save(path, doc):
    path.write_text(json.dumps(doc),encoding='utf-8')
    return path


def test_preview_is_offline_and_original_unchanged(raw_result,tmp_path,monkeypatch,capsys):
    source=save(tmp_path/'result.json',raw_result); before=source.read_bytes()
    monkeypatch.setattr(g,'GitHubCLI',lambda: pytest.fail('preview must not use GitHub'))
    assert submit.main([str(source),'--preview','--github-user','fixture-user'])==0
    doc=json.loads(capsys.readouterr().out)
    assert doc['schema']==c.SCHEMA and source.read_bytes()==before
    assert list(tmp_path.iterdir())==[source]


def test_missing_metadata_exports_draft_without_auth(raw_result,tmp_path,monkeypatch,capsys):
    source=save(tmp_path/'result.json',raw_result)
    monkeypatch.setattr(g,'GitHubCLI',lambda: pytest.fail('draft must not use GitHub'))
    assert submit.main([str(source),'--export-dir',str(tmp_path/'draft')])==2
    report=json.loads(capsys.readouterr().out)
    assert 'github_user' in report['missing']
    draft=c.read_json(Path(report['draft']))
    assert draft['schema']=='sixcat-submission-draft-v1'


def test_export_is_idempotent_and_contains_only_public_copy(raw_result,tmp_path,capsys):
    source=save(tmp_path/'result.json',raw_result)
    directory=tmp_path/'export'
    argv=[str(source),'--export-dir',str(directory),'--github-user','fixture-user','--source-kind','cloud',
          '--source','nous','--api-wrapper','Hermes','--quant-format','Undisclosed']
    assert submit.main(argv)==0
    exported=Path(json.loads(capsys.readouterr().out)['local_export'])
    doc=c.read_json(exported)
    assert doc['metadata']['source']=='nous'
    assert doc['metadata']['inference_engine']=='Undisclosed'
    assert (directory/'README-row.md').is_file()
    assert submit.main(argv)==0
    capsys.readouterr()
    changed=copy.deepcopy(doc); changed['contributor']='someone-else'
    with pytest.raises(c.SubmissionError): submit.write_package(changed,directory)


def test_noninteractive_default_never_uploads(raw_result,tmp_path,monkeypatch,capsys):
    source=save(tmp_path/'result.json',raw_result)
    monkeypatch.setattr(submit.sys,'stdin',SimpleNamespace(isatty=lambda:False))
    monkeypatch.setattr(g,'GitHubCLI',lambda: pytest.fail('No consent'))
    assert submit.main([str(source),'--github-user','fixture-user'])==0
    assert json.loads(capsys.readouterr().out)['status']=='exported_only'


def test_explicit_yes_publishes_exact_prepared_export(public_doc,tmp_path,monkeypatch,capsys):
    source=save(tmp_path/'public.json',public_doc)
    client=SimpleNamespace(username=lambda:'fixture-user')
    monkeypatch.setattr(g,'GitHubCLI',lambda:client)
    called=[]
    def publish(doc,**kwargs):
        called.append((doc,kwargs)); return {'status':'submitted','url':'https://github.com/example/pr/1'}
    monkeypatch.setattr(g,'publish',publish)
    assert submit.main([str(source),'--yes'])==0
    assert called[0][0]==public_doc and called[0][1]['consent'] is True
    assert json.loads(capsys.readouterr().out)['status']=='submitted'


def test_contributor_mismatch_stops_before_publish(public_doc,tmp_path,monkeypatch,capsys):
    source=save(tmp_path/'public.json',public_doc)
    monkeypatch.setattr(g,'GitHubCLI',lambda:SimpleNamespace(username=lambda:'someone-else'))
    monkeypatch.setattr(g,'publish',lambda *a,**k:pytest.fail('identity mismatch'))
    assert submit.main([str(source),'--yes'])==2
    assert 'match' in capsys.readouterr().err


def test_metadata_file_and_reasoning_are_explicit(raw_result,tmp_path,capsys):
    source=save(tmp_path/'result.json',raw_result)
    metadata=save(tmp_path/'meta.json',{'source_kind':'cloud','source':'nous','inference_engine':'Undisclosed'})
    assert submit.main([str(source),'--preview','--metadata',str(metadata),'--github-user','fixture-user','--include-reasoning'])==0
    assert json.loads(capsys.readouterr().out)['export']['reasoning_included'] is True
    save(metadata,{'api_key':'do not upload'})
    assert submit.main([str(source),'--preview','--metadata',str(metadata)])==2


def test_no_execution_of_answer_on_submission(public_doc,tmp_path,monkeypatch):
    from sixcat import code
    monkeypatch.setattr(code,'_run_humaneval',lambda *a,**k:pytest.fail('Do not execute public answers'))
    path=save(tmp_path/'result.json',public_doc)
    assert submit.main([str(path),'--preview'])==0


def test_after_run_skips_incomplete_and_prepares_complete(raw_result,tmp_path,monkeypatch):
    path=save(tmp_path/'result.json',raw_result)
    main=Mock(return_value=0);monkeypatch.setattr(submit,'main',main)
    submit.after_run(raw_result,path)
    assert '--export-dir' in main.call_args.args[0]
    main.reset_mock();raw_result['complete']=False
    submit.after_run(raw_result,path)
    main.assert_not_called()


def test_runtime_hints_are_scoped(raw_result):
    from sixcat.community_runtime import runtime_metadata,current
    from sixcat.__main__ import _slim_result
    target=SimpleNamespace(provider='nous')
    with runtime_metadata(target):
        saved=_slim_result(raw_result,Path('private/profile.jsonl'))
        assert saved['community_metadata']['source']=='nous'
    assert current.get() is None
    meta=e.default_metadata(saved)
    assert meta['source_kind']=='cloud' and meta['api_wrapper']=='Hermes raw-model bridge'


def test_package_registry_schema_and_version_unchanged():
    root=Path(__file__).resolve().parents[1]
    assert c.load_registry()['benchmarks']
    assert json.loads((root/'sixcat/community.schema.json').read_text())['properties']['schema']['const']==c.SCHEMA
    assert 'Unreleased on `main`' in (root/'README.md').read_text()
