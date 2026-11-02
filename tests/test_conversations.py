def test_conversation_drafts_are_separate(client,monkeypatch):
    from app.agents import router
    monkeypatch.setattr(router,'chat_agent',lambda text:{'intent':'cancel' if text=='cancel' else 'add_person'})
    first=client.post('/api/chat',json={'message':'add name: Ravi Kumar','conversation_id':'one'})
    assert first.status_code==200
    second=client.post('/api/chat',json={'message':'add name: Neha Sharma','conversation_id':'two'})
    assert second.status_code==200
    from app.database import connection
    import json
    with connection() as db:
        states=[json.loads(r['state']) for r in db.execute('SELECT state FROM conversations')]
    assert {s['person']['name'] for s in states}=={'Ravi Kumar','Neha Sharma'}
    client.post('/api/chat',json={'message':'cancel','conversation_id':'one'})
    with connection() as db:
        states=[json.loads(r['state']) for r in db.execute('SELECT state FROM conversations')]
    assert len(states)==1 and states[0]['person']['name']=='Neha Sharma'
