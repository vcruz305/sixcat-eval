import copy
import json
from pathlib import Path
import subprocess

import pytest
from sixcat import community as c, community_export as e, community_check as ck
from tests.test_community import reference_result, raw_result, public_doc, resign


def init(root):
    root.mkdir()
    subprocess.run(['git','init','-q',str(root)],check=True)
    (root/'community/results').mkdir(parents=True)
    (root/'sixcat').mkdir()
    (root/'README.md').write_text('Before\n'+c.START+'\n\n'+e.render_table([])+'\n'+c.END+'\nAfter',encoding='utf-8')
    (root/'sixcat/community-compatibility.json').write_text(json.dumps(c.load_registry()))
    return root


def stage(root):
    subprocess.run(['git','-C',str(root),'add','.'],check=True)


def add(root,doc):
    path=root/e.result_path(doc);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc))
    ck.check(root,render=True)


def test_empty_and_rendered_table_are_valid(tmp_path,public_doc):
    root=init(tmp_path/'repo')
    assert ck.check(root)['submissions']==0
    add(root,public_doc)
    assert ck.check(root)['submissions']==1
    assert ck.main(['validate','--root',str(root)])==0
    (root/'README.md').write_text((root/'README.md').read_text().replace('Before','Different'))
    # A software-only edit outside the table is fine without a result PR scope.
    assert ck.check(root)['status']=='valid'


def test_result_pr_adds_only_json_and_generated_readme(tmp_path,public_doc):
    base=init(tmp_path/'base');head=init(tmp_path/'head');stage(base)
    add(head,public_doc);stage(head)
    result=ck.check(head,base=base,author='fixture-user')
    assert result['executed_submitted_code'] is False
    with pytest.raises(c.SubmissionError,match='author'):ck.check(head,base=base,author='other-person')
    (head/'extra.py').write_text('raise RuntimeError("never execute me")');stage(head)
    with pytest.raises(c.SubmissionError,match='only add one JSON'):ck.check(head,base=base)


def test_public_pr_cannot_approve_its_own_registry(tmp_path,public_doc):
    base=init(tmp_path/'base');head=init(tmp_path/'head');stage(base)
    altered=copy.deepcopy(public_doc);r=altered['result'];r['benchmark_manifest']['tools_sha256']='f'*64
    m=r['benchmark_manifest'];m['fingerprint']=c.fingerprint({k:v for k,v in m.items() if k!='fingerprint'})
    r['benchmark_fingerprint']=m['fingerprint'];resign(altered)
    fake={'schema':'sixcat-community-compatibility-v1','benchmarks':{m['fingerprint']:{'manifest':m}}}
    (head/'sixcat/community-compatibility.json').write_text(json.dumps(fake))
    path=head/e.result_path(altered);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(altered));stage(head)
    with pytest.raises(c.SubmissionError,match='approved'):ck.check(head,base=base)


def test_existing_results_cannot_be_deleted_in_submission(tmp_path,public_doc):
    base=init(tmp_path/'base');head=init(tmp_path/'head');add(base,public_doc);stage(base);stage(head)
    with pytest.raises(c.SubmissionError,match='append-only'):ck.check(head,base=base)


def test_table_and_outside_text_must_match(tmp_path,public_doc):
    base=init(tmp_path/'base');head=init(tmp_path/'head');stage(base);add(head,public_doc)
    p=head/'README.md';p.write_text(p.read_text().replace('Before','Edited'));stage(head)
    with pytest.raises(c.SubmissionError,match='outside'):ck.check(head,base=base)
    p.write_text(p.read_text().replace('Edited','Before').replace('100.0','99.9'))
    with pytest.raises(c.SubmissionError,match='README table'):ck.check(head)


def test_symlinks_and_non_json_files_rejected(tmp_path):
    root=init(tmp_path/'repo')
    (root/'community/results/not-a-result.py').write_text('print("bad")')
    with pytest.raises(c.SubmissionError,match='Only JSON'):ck.check(root)
    (root/'community/results/not-a-result.py').unlink()
    target=tmp_path/'secret';target.write_text('not public')
    try:(root/'community/results/link.json').symlink_to(target)
    except OSError:pytest.skip('symlink privilege unavailable on this host')
    with pytest.raises(c.SubmissionError,match='Symlinks'):ck.check(root)


def test_validator_failure_exit_and_does_not_import_candidate(tmp_path,public_doc):
    root=init(tmp_path/'repo');add(root,public_doc)
    marker=tmp_path/'executed'
    (root/'sixcat/__init__.py').write_text(f'open({str(marker)!r},"w").write("executed")')
    assert ck.check(root)['status']=='valid' and not marker.exists()
    (root/'README.md').write_text('bad')
    assert ck.main(['validate','--root',str(root)])==2


def test_trusted_workflow_never_uses_candidate_code():
    root=Path(__file__).resolve().parents[1]
    text=(root/'.github/workflows/community-results.yml').read_text()
    assert 'pull_request_target' not in text
    assert 'working-directory: trusted' in text
    assert 'pull_request.base.sha' in text and 'persist-credentials: false' in text
    assert 'contents: read' in text
    assert 'pip install' not in text
    assert '--base "$GITHUB_WORKSPACE/trusted"' in text
