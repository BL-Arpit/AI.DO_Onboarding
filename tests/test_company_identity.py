"""Single-company super admin and confirmed in-place company identity changes."""
import pytest
from fastapi import HTTPException
from tests.test_company_roleplays import world, isolate_external_services
from app.repositories.database import connection
from app.chat import planner_context, smollm_agent as smol
from app.chat.onboarding_agent import Turn


def test_company_rename_and_owner_correction_keep_all_ids(world, monkeypatch):
    w = world
    sa, owner, tid = w.company('odessi')
    hr = w.hr(owner, 'odessi')
    eid = w.employee(hr, 'karthik@example.org')
    user = sa.get('/api/auth/session').json()['user']
    with connection() as db:
        before = dict(db.execute("SELECT * FROM users WHERE tenant_id=? AND role='owner'", (tid,)).fetchone())
    # Seed an obsolete unfinished owner draft; the rename supersedes it.
    draft = w.chat(sa, 'Invite owner')
    assert 'already has' in draft['messages'][-1]['text']
    monkeypatch.setenv('CHAT_PROVIDER', 'groq')
    monkeypatch.setattr(smol, 'choose', lambda *a: smol.Decision(tool='rename_company', arguments={'organization_name':'BridgeLabz','name':'Arpit Sahu'}))
    proposal = w.chat(sa, 'change company name to BridgeLabz and owner name to Arpit Sahu')
    assert proposal['active_confirmation']
    assert sa.get('/api/organizations/current').json()['name'] == 'odessi'
    done = w.confirm(sa, proposal)
    assert 'Company renamed to BridgeLabz' in done['messages'][-1]['text']
    assert done['active_confirmation'] is None
    with connection() as db:
        after = dict(db.execute("SELECT * FROM users WHERE id=?", (before['id'],)).fetchone())
        assert after['tenant_id'] == tid and after['name'] == 'Arpit Sahu'
        assert after['email'] == before['email']
        assert db.execute('SELECT tenant_id FROM employees WHERE id=?', (eid,)).fetchone()['tenant_id'] == tid
        assert db.execute("SELECT COUNT(*) AS n FROM users WHERE tenant_id=? AND role='owner'", (tid,)).fetchone()['n'] == 1
    ctx = planner_context.build({}, {}, user)
    assert ctx['business']['company'] == 'BridgeLabz'
    assert next(a for a in ctx['business']['company_accounts'] if a['role']=='owner')['name'] == 'Arpit Sahu'
    monkeypatch.setattr(smol, 'choose', lambda *a: smol.Decision(tool='invite_owner', arguments={}))
    monkeypatch.setattr(smol, 'grounded_reply', lambda thread, text, result: result)
    assert 'already has' in w.chat(sa, 'Invite owner')['messages'][-1]['text']


def test_api_blocks_second_company_cross_company_rename_and_non_admin(world):
    w = world
    sa, owner, tid = w.company('first')
    other_sa, _, other_tid = w.company('other')
    body={'name':'Another', 'owner':{'name':'Other Owner','email':'second-owner@example.org'}}
    assert sa.post('/api/organizations', json=body).status_code == 409
    assert owner.put('/api/organizations/current/name', json={'name':'Blocked','expected_version':1}).status_code == 403
    # Client cannot choose an arbitrary company in a rename payload.
    assert sa.put('/api/organizations/current/name', json={'name':'Blocked','expected_version':1,'tenant_id':other_tid}).status_code == 422
    assert other_sa.get('/api/organizations/current').json()['name'] == 'other'
    assert sa.get('/api/organizations/current').json()['name'] == 'first'


def test_rename_conflict_and_cancellation_are_safe(world, monkeypatch):
    w = world
    sa, _, tid = w.company('original')
    monkeypatch.setenv('CHAT_PROVIDER','groq')
    monkeypatch.setattr(smol,'choose',lambda *a:smol.Decision(tool='rename_company',arguments={'organization_name':'New Name'}))
    proposal=w.chat(sa,'Rename to New Name')
    cancelled=w.chat(sa,'Cancel')
    assert cancelled['active_confirmation'] is None
    assert sa.get('/api/organizations/current').json()['name']=='original'
    proposal=w.chat(sa,'Rename to New Name')
    assert sa.put('/api/organizations/current/name',json={'name':'Concurrent','expected_version':1}).status_code==200
    result=w.confirm(sa,proposal)
    assert 'changed' in result['messages'][-1]['text']
    assert sa.get('/api/organizations/current').json()['name']=='Concurrent'


def test_assigned_superadmin_does_not_offer_owner_tool(world, monkeypatch):
    w=world
    sa,_,_=w.company('assigned')
    user=sa.get('/api/auth/session').json()['user']
    context=planner_context.build({}, {}, user)
    monkeypatch.setenv('CHAT_PROVIDER','groq')
    from app.chat import groq_provider
    def decide(thread,state,text,role,context,catalog,schema):
        assert 'invite_owner' not in catalog
        assert 'invite_hr' not in catalog
        assert 'rename_company' in catalog
        return ('chat', {}, False, 'Your owner appoints HR.', None)
    monkeypatch.setattr(groq_provider,'decide',decide)
    decision=smol.choose({'planner_context':context},{},'Add Aishwarya as HR','super_admin')
    assert decision.tool=='chat'


def test_owner_guard_rejects_internal_second_owner(world):
    from app.api.onboarding import create_account
    w=world
    _,_,tid=w.company('guard')
    with connection() as db:
        with pytest.raises(HTTPException) as exc:
            create_account(db,'Another','another@example.org','owner','unused-password',tid)
        assert exc.value.status_code==409


def test_old_owner_draft_is_discarded_and_hr_action_is_not_owner_setup(world):
    w = world
    sa, _, _ = w.company('stale')
    user = sa.get('/api/auth/session').json()['user']
    state = {'task_draft': {'tool':'invite_owner','values':{'name':'Aishwarya'}},
             'setup': {'id':'old','organization':None},
             'pending': {'id':'old','operation':'provision','values':{}}}
    context = planner_context.build({},state,user)
    assert 'task_draft' not in state and 'pending' not in state and 'setup' not in state
    assert context['business']['owner_limit'] == 1
    thread = sa.post('/api/conversations').json()
    result = sa.post('/api/conversations/'+thread['id']+'/turn',json={'text':'Add Aishwarya as HR','action':'appoint'})
    assert result.status_code == 403
