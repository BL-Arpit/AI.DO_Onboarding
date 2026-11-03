import json
import os
from pathlib import Path
import httpx

def verification_agent(employee, documents):
    prompt = (Path(__file__).parent.parent/'prompts/verification.txt').read_text()
    issues = []
    types = {d['kind'] for d in documents}
    for kind in ('AADHAAR_CARD','PAN_CARD'):
        if kind not in types:
            issues.append('Missing ' + kind)
    if not types.intersection({'BANK_PASSBOOK','CHEQUE'}):
        issues.append('Missing bank document')
    for doc in documents:
        c, e = doc['classification'], doc['extraction']
        if e.get('is_mock') or e.get('extraction_source')=='mock':
            issues.append(doc['kind']+': MOCK data, not OCR or verified identity')
        if c.get('needs_review') or c.get('type_disagreement') or e.get('status') != 'success':
            issues.append(doc['kind'] + ': document needs review')
        extracted = e.get('extracted_data') or {}
        name = extracted.get('name') or extracted.get('account_holder_name')
        if name and ' '.join(name.casefold().split()) != ' '.join(employee['name'].casefold().split()):
            issues.append(doc['kind'] + ': name differs from employee')
    result = {'status':'needs_review','issues':issues,
              'summary':'Document consistency audit only; background and DL checks are pending.',
              'agent':'local_checks','authoritative_checks':'not_configured'}
    url = os.getenv('AGENT_URL')
    if url:
        try:
            response = httpx.post(url, headers={'Authorization':'Bearer '+os.getenv('AGENT_API_KEY','')},
                json={'model':os.getenv('AGENT_MODEL'), 'temperature':0,
                      'messages':[{'role':'system','content':prompt},
                                  {'role':'user','content':json.dumps({'employee':employee,'documents':documents})}]}, timeout=60)
            response.raise_for_status()
            proposal = json.loads(response.json()['choices'][0]['message']['content'])
            if proposal['status'] != 'needs_review' or not isinstance(proposal['issues'], list) or not all(isinstance(x,str) for x in proposal['issues']):
                raise ValueError('Invalid agent output')
            result['issues'] += proposal['issues'][:30]
            result['summary'] = str(proposal.get('summary',''))[:2000]
            result['agent'] = 'prompt_agent'
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            result['issues'].append('Prompt agent unavailable; human review required')
    return result
