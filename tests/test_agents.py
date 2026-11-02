import json
from pathlib import Path
from app.agents.chat import chat_agent,MODEL_DIR


def test_local_ann_routes_paraphrase_to_onboarding(client):
    response=client.post('/api/chat',json={'message':'please onboard a person'}).json()
    assert response['chat_model']['model']=='local_ann_v1'
    assert response['chat_model']['intent']=='add_person'
    assert response['agent_trace']==['chat_agent','onboarding_agent']
    assert response['action']=='collect'
    assert client.get('/api/employees').json()==[]
    for text in ('Neha Rao','neha@example.com','9876543210'):
        result=client.post('/api/chat',json={'message':text}).json()
        assert result['agent_trace'][-1]=='onboarding_agent'
    assert result['action']=='confirm_person'
    assert client.post('/api/chat',json={'message':'confirm'}).json()['action']=='added'


def test_unknown_intent_does_not_start_or_save(client):
    response=client.post('/api/chat',json={'message':'write me a poem'}).json()
    assert response['chat_model']['intent']=='unknown'
    assert client.get('/api/employees').json()==[]
    assert response['agent_trace'][-1]=='help'
    assert client.post('/api/chat',json={'message':'confirm'}).json()['reply'].startswith('There is no pending')


def test_ann_predictions_and_negative_commands():
    for text,intent in [('add','add_person'),('hello','greeting'),('import','import_excel'),
                        ('list','list_people'),('audit','audit'),('upload document','upload_document'),('export','export_excel')]:
        assert chat_agent(text)['intent']==intent
    assert chat_agent('do not approve')['intent']=='unknown'
    assert chat_agent('zzzzzzzzzzzzzzzzzz')['intent']=='unknown'


def test_training_and_heldout_examples_are_separate():
    root=Path(__file__).resolve().parents[1]
    train=json.loads((root/'training/intents.json').read_text())
    heldout=json.loads((root/'training/evaluation.json').read_text())
    assert not {s for rows in train.values() for s in rows}&{s for rows in heldout.values() for s in rows}
    report=json.loads((MODEL_DIR/'evaluation.json').read_text())
    assert report['held_out_examples']==sum(map(len,heldout.values()))
    # No claim of perfect accuracy: preserve the actually observed prototype metrics.
    assert report['top1_accuracy']>.8
