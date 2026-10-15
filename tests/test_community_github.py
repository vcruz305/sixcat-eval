import base64
import json
import subprocess
from types import SimpleNamespace

import pytest
from sixcat import community as c, community_export as e, community_github as g
from tests.test_community import reference_result, raw_result, public_doc


class FakeGitHub:
    def __init__(self, *, push=True, existing=None, branch=False, wrong_fork=False, race=False):
        self.calls=[];self.push=push;self.existing=existing or [];self.branch=branch
        self.fork=False;self.wrong_fork=wrong_fork;self.race=race
    def username(self):return 'fixture-user'
    def api(self,method,path,data=None):
        self.calls.append((method,path,data))
        if method=='GET':
            if path==g.ROOT:return {'permissions':{'push':self.push}}
            if '/pulls?' in path:return self.existing
            if path.endswith('/git/ref/heads/main'):return {'object':{'sha':('c' if self.race else 'a')*40}}
        if method=='POST':
            if path.endswith('/forks'):self.fork=True;return {}
            if path.endswith('/git/trees'):
                assert {t['path'] for t in data['tree']} == {'README.md', e.result_path(self.doc)}
                return {'sha':'b'*40}
            if path.endswith('/git/commits'):return {'sha':'d'*40}
            if path.endswith('/git/refs'):
                assert data['ref'].startswith('refs/heads/sixcat-results/')
                return {}
            if path.endswith('/pulls'):return {'html_url':'https://github.com/vcruz305/sixcat-eval/pull/999'}
        raise AssertionError((method,path))
    def optional(self,path):
        if '/git/ref/' in path:return {} if self.branch else None
        if self.fork or self.wrong_fork:
            return {'fork':True,'parent':{'full_name':'other/repo' if self.wrong_fork else g.REPOSITORY}}
        return None


def setup_snapshot(monkeypatch,public_doc,docs=None):
    monkeypatch.setattr(g,'snapshot',lambda client:('a'*40,'b'*40,c.START+'\n\n'+e.render_table(docs or [])+'\n'+c.END,docs or [],c.load_registry()))
    monkeypatch.setattr(g.time,'sleep',lambda _:None)


@pytest.mark.parametrize('push',[True,False])
def test_publish_two_files_without_touching_main_or_releases(public_doc,monkeypatch,push):
    setup_snapshot(monkeypatch,public_doc)
    client=FakeGitHub(push=push);client.doc=public_doc
    result=g.publish(public_doc,consent=True,client=client)
    assert result['status']=='submitted'
    assert len(result['files'])==2
    if not push: assert client.fork
    assert not any('/releases' in path or method in {'PATCH','PUT','DELETE'} for method,path,_ in client.calls)
    assert all(data['ref']!='refs/heads/main' for _,path,data in client.calls if path.endswith('/git/refs'))


def test_no_consent_does_not_even_read_auth(public_doc):
    with pytest.raises(c.SubmissionError,match='confirmation'):g.publish(public_doc,client=object())


def test_duplicate_returns_existing_result_without_writes(public_doc,monkeypatch):
    setup_snapshot(monkeypatch,public_doc,[public_doc]);client=FakeGitHub()
    assert g.publish(public_doc,consent=True,client=client)['status']=='already_submitted'
    assert not client.calls


@pytest.mark.parametrize('state',['open','closed'])
def test_existing_pr_is_not_duplicated(public_doc,monkeypatch,state):
    setup_snapshot(monkeypatch,public_doc)
    client=FakeGitHub(existing=[{'state':state,'html_url':'existing-pr'}])
    result=g.publish(public_doc,consent=True,client=client)
    assert result['status']=='already_'+state
    assert not any(m=='POST' for m,_,_ in client.calls)


@pytest.mark.parametrize('kwargs,match',[({'branch':True},'branch'),({'push':False,'wrong_fork':True},'fork'),({'race':True},'main changed')])
def test_publish_refuses_overwrites_wrong_forks_and_stale_base(public_doc,monkeypatch,kwargs,match):
    setup_snapshot(monkeypatch,public_doc);client=FakeGitHub(**kwargs);client.doc=public_doc
    with pytest.raises(c.SubmissionError,match=match):g.publish(public_doc,consent=True,client=client)
    assert not any(p.endswith('/git/refs') or (m=='POST' and p.endswith('/pulls')) for m,p,_ in client.calls)


def test_contributor_identity_checked(public_doc,monkeypatch):
    public_doc['contributor']='someone-else'
    with pytest.raises(c.SubmissionError,match='Contributor'):g.publish(public_doc,consent=True,client=FakeGitHub())


def test_cli_reuses_gh_without_token_arguments(monkeypatch):
    calls=[]
    def run(args,**kw):
        calls.append((args,kw));return SimpleNamespace(returncode=0,stdout='{"login":"fixture-user"}',stderr='')
    monkeypatch.setattr(g.subprocess,'run',run)
    assert g.GitHubCLI().username()=='fixture-user'
    g.GitHubCLI().api('POST',g.ROOT+'/pulls',{'title':'A title'})
    assert calls[0][0][:3]==['gh','api','--hostname']
    assert '--input' in calls[1][0] and calls[1][1]['input']=='{"title": "A title"}'


@pytest.mark.parametrize('response',[
    SimpleNamespace(returncode=1,stdout='',stderr='SECRET HTTP 403'),
    SimpleNamespace(returncode=0,stdout='not json',stderr=''),
])
def test_cli_errors_do_not_echo_credentials(monkeypatch,response):
    monkeypatch.setattr(g.subprocess,'run',lambda *a,**k:response)
    with pytest.raises(c.SubmissionError) as exc:g.GitHubCLI().api('GET','user')
    assert 'SECRET' not in str(exc.value)


def test_gh_missing_timeout_and_optional_404(monkeypatch):
    monkeypatch.setattr(g.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(c.SubmissionError,match='unavailable'):g.GitHubCLI().api('GET','user')
    cli=g.GitHubCLI()
    monkeypatch.setattr(cli,'api',lambda *a:(_ for _ in ()).throw(g.GitHubError(404)))
    assert cli.optional('missing') is None
    monkeypatch.setattr(cli,'api',lambda *a:(_ for _ in ()).throw(g.GitHubError(403)))
    with pytest.raises(g.GitHubError):cli.optional('denied')


def test_snapshot_uses_live_main_and_approved_registry(public_doc):
    values={'README.md':c.START+'\n\n'+e.render_table([public_doc])+'\n'+c.END,
        'sixcat/community-compatibility.json':json.dumps(c.load_registry()),e.result_path(public_doc):json.dumps(public_doc)}
    shas={name:format(i+1,'040x') for i,name in enumerate(values)}
    def api(method,path,data=None):
        assert method=='GET'
        if path.endswith('/git/ref/heads/main'):return {'object':{'sha':'a'*40}}
        if '/git/commits/' in path:return {'tree':{'sha':'b'*40}}
        if '/git/trees/' in path:return {'truncated':False,'tree':[{'path':p,'mode':'100644','type':'blob','sha':s,'size':len(values[p])} for p,s in shas.items()]}
        name=next(n for n,s in shas.items() if path.endswith(s)); text=values[name].encode()
        return {'encoding':'base64','size':len(text),'content':base64.b64encode(text).decode()}
    base,tree,readme,docs,registry=g.snapshot(SimpleNamespace(api=api))
    assert base=='a'*40 and docs==[public_doc] and registry['benchmarks']


def test_invalid_blob_and_truncated_tree():
    with pytest.raises(c.SubmissionError):g.blob_text(object(),'not-a-sha')
    client=SimpleNamespace(api=lambda *a:{'encoding':'base64','size':1,'content':'!!!'})
    with pytest.raises(c.SubmissionError):g.blob_text(client,'a'*40)
    def api(method,path):
        if '/git/ref/' in path:return {'object':{'sha':'a'*40}}
        if '/git/commits/' in path:return {'tree':{'sha':'b'*40}}
        return {'truncated':True}
    with pytest.raises(c.SubmissionError,match='Truncated'):g.snapshot(SimpleNamespace(api=api))
