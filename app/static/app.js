'use strict';
const $=id=>document.getElementById(id);
let csrf='',conv='',busy=false,activeTask=null,selected=null;
function node(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.append(e);return e;}
function notice(text){$('notice').textContent=text;$('notice').hidden=false;}
function loginView(){csrf='';conv='';selected=null;activeTask=null;$('chatlog').replaceChildren();$('workspace').hidden=true;$('loginView').hidden=false;}
async function api(path,options={}){
 const headers={...(options.headers||{})};
 if(options.body&&!(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
 if(options.method&&!['GET','HEAD'].includes(options.method))headers['X-CSRF-Token']=csrf;
 const response=await fetch('/api'+path,{...options,headers,credentials:'same-origin'});
 const raw=await response.text();let data;try{data=raw?JSON.parse(raw):{};}catch{throw Error('Unexpected server response ('+response.status+').');}
 if(!response.ok){if(response.status===401)loginView();const message=typeof data.detail==='string'?data.detail:'Request failed ('+response.status+').';throw Error(message+(data.request_id?' Request: '+data.request_id:''));}return data;
}
async function guard(action,label='Working…'){
 if(busy)return;busy=true;$('progress').textContent=label;for(const id of ['attach','send','newChat'])$(id).disabled=true;
 try{await action();$('notice').hidden=true;}catch(e){notice(e.message);}finally{busy=false;$('progress').textContent='';for(const id of ['attach','send','newChat'])$(id).disabled=false;$('composer').elements.message.focus();}
}
function button(text,action,parent,primary=false){const b=node('button',text,parent);b.type='button';if(primary)b.className='primary';b.onclick=()=>guard(action);return b;}
function bubble(text,role='assistant'){if($('welcome'))$('welcome').remove();const e=node('div',text,$('chatlog'));e.className='bubble '+role;scroll();return e;}
function scroll(){$('chatlog').scrollTop=$('chatlog').scrollHeight;}
function task(title){if(activeTask)activeTask.remove();activeTask=node('section',undefined,$('chatlog'));activeTask.className='task';if(title)node('h2',title,activeTask);return activeTask;}
function table(rows,columns,parent,master=false){const wrap=node('div',undefined,parent);wrap.className='scroll'+(master?' master':'');const t=node('table',undefined,wrap);const h=node('tr',undefined,node('thead',undefined,t));columns.forEach(x=>node('th',x,h));const body=node('tbody',undefined,t);rows.forEach(values=>{const row=node('tr',undefined,body);values.forEach(value=>node('td',value??'',row));});return t;}
async function refreshConversations(){const rows=await api('/conversations');$('conversations').replaceChildren();for(const row of rows){const b=button('Chat '+row.id.slice(0,6),()=>openConversation(row.id),$('conversations'));if(row.id===conv)b.className='active';}}
async function newChat(){conv=Array.from(crypto.getRandomValues(new Uint32Array(4)),n=>n.toString(16)).join('');selected=null;activeTask=null;$('chatlog').replaceChildren();$('chatTitle').textContent='New conversation';bubble('Hi, welcome.');document.body.classList.remove('sidebar-open');await refreshConversations();}
async function openConversation(id){conv=id;selected=null;activeTask=null;$('chatlog').replaceChildren();const data=await api('/conversations/'+id);data.messages.forEach(m=>bubble(m.content,m.role));$('chatTitle').textContent='Chat '+id.slice(0,6);document.body.classList.remove('sidebar-open');if(data.pending)renderConfirmation(data.pending);else if(data.selected_id){selected=await api('/employees/'+data.selected_id);renderEmployee(selected);}await refreshConversations();}
async function send(text){if(!conv)await newChat();bubble(text,'user');const result=await api('/chat',{method:'POST',body:{message:text,conversation_id:conv}});await handle(result);await refreshConversations();}
async function handle(result){
 if(result.reply)bubble(result.reply);
 if(activeTask){activeTask.remove();activeTask=null;}
 if(result.action==='confirm')renderConfirmation(result);
 if(result.employee){selected=result.employee;renderEmployee(selected);}
 else if(result.document)renderDocument(result.document);
 if(result.action==='list'){selected=null;await showMaster();}
 if(result.action==='export')await downloadMaster();
 if(result.action==='deleted')selected=null;
 if(result.action==='import')renderImport(result);
 if(result.choices){const box=task('Choose an employee');for(const person of result.choices)button(person.name+' · '+person.email,()=>send('select '+person.id),box);}
 if(result.report){const box=task('Audit');node('p',result.report.summary,box);for(const issue of result.report.issues||[])node('p',issue,box);}
 scroll();
}
function renderConfirmation(result){const box=task('Review change');node('pre',JSON.stringify(result.proposal,null,2),box);const actions=node('div',undefined,box);actions.className='buttons';button('Confirm',async()=>handle(await api('/actions/'+result.pending_id+'/confirm',{method:'POST',body:{conversation_id:conv}})),actions,true);button('Cancel',()=>send('cancel'),actions);}
function renderDocument(result){const box=task(result.classification.document_type.replaceAll('_',' '));if(result.extraction.is_mock)node('div','MOCK · manually annotated sample, not OCR or verified identity',box).className='tag';table(Object.entries(result.prefill).filter(([k])=>k!=='additional_fields'),['Field','Prefilled value'],box);}
function renderEmployee(person){
 const box=task(person.name);node('p',person.email+' · '+person.phone,box).className='dim';
 const mocked=(person.documents||[]).some(d=>d.extraction?.is_mock);if(mocked)node('div','MOCK data · not verified identity',box).className='tag';
 const kinds=Object.keys(person.fields||{});if(!kinds.length){node('p','Attach a document using +. I will classify it and fill the fields.',box);return;}
 const events=person.audit||[];const last=action=>Math.max(-1,...events.map((e,i)=>e.action===action?i:-1));
 const confirmed=last('fields_confirmed')>last('document_extracted');
 if(!confirmed){
  node('p','Review the prefilled fields.',box);const form=node('form',undefined,box);const edited=structuredClone(person.fields);
  for(const kind of kinds){node('h3',kind.replaceAll('_',' '),form);for(const [key,value] of Object.entries(edited[kind])){if(key==='additional_fields')continue;const label=node('label',key.replaceAll('_',' '),form);const input=node('input',undefined,label);input.value=value??'';input.oninput=()=>edited[kind][key]=input.value;}}
  const confirm=node('button','Confirm fields',form);confirm.className='primary';form.onsubmit=e=>{e.preventDefault();guard(async()=>{selected=await api('/employees/'+person.id+'/fields',{method:'PUT',body:{version:person.version,fields:edited}});renderEmployee(selected);});};
 }else if(!Object.keys(person.verification||{}).length){node('p','Fields confirmed. Run the consistency audit when ready.',box);button('Run audit',async()=>{const report=await api('/employees/'+person.id+'/audit',{method:'POST',body:{version:person.version}});bubble(report.summary);selected=await api('/employees/'+person.id);renderEmployee(selected);},box,true);}
 else{node('p',person.verification.summary,box);for(const issue of person.verification.issues||[])node('p',issue,box);node('p','Use + to add the next document, or type a change.',box).className='dim';}
 scroll();
}
function renderImport(result){const box=task('Review import');node('p',result.preview.accepted.length+' valid · '+result.preview.rejected.length+' skipped',box);table(result.preview.accepted.map(r=>[r.person.name,r.person.email,r.person.phone]),['Name','Email','Phone'],box);for(const row of result.preview.rejected)node('p','Row '+row.row+': '+row.issues.join(' '),box);if(result.preview.accepted.length)button('Confirm import',async()=>handle(await api('/imports/'+result.import_id+'/confirm',{method:'POST'})),box,true);}
async function showMaster(){const data=await api('/employees/master');const box=task('Master employee sheet');button('Download Excel',downloadMaster,box);if(!data.rows.length){node('p','No employees yet.',box);return;}const t=table(data.rows,data.columns.map(x=>x.replaceAll('_',' ')),box,true);Array.from(t.tBodies[0].rows).forEach((row,i)=>{row.cells[0].replaceChildren();button('Open',()=>send('select '+data.rows[i][0]),row.cells[0]);});}
async function downloadMaster(){const response=await fetch('/api/employees/export',{credentials:'same-origin'});if(!response.ok){if(response.status===401)loginView();let data={};try{data=await response.json();}catch{}throw Error(data.detail||'Download failed. Sign in and retry.');}const blob=await response.blob();const url=URL.createObjectURL(blob);const a=node('a',undefined,document.body);a.href=url;a.download='master_employees.xlsx';a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
async function upload(files){if(!conv)await newChat();for(const file of files){bubble(file.name,'user');const form=new FormData();form.append('file',file);const result=await api('/chat/'+conv+'/attachments',{method:'POST',body:form});await handle(result);if(files.length>1)break;}if(files.length>1)bubble('Finish this document or import task, then attach the next file.');await refreshConversations();}
async function signedIn(){const data=await api('/auth/session');csrf=data.csrf_token;$('loginView').hidden=true;$('workspace').hidden=false;await refreshConversations();if(!conv)await newChat();}
$('loginForm').onsubmit=e=>{e.preventDefault();guard(async()=>{const data=await api('/auth/login',{method:'POST',body:Object.fromEntries(new FormData(e.target))});csrf=data.csrf_token;e.target.elements.password.value='';await signedIn();});};
$('composer').onsubmit=e=>{e.preventDefault();const input=e.target.elements.message;const text=input.value.trim();if(!text)return;input.value='';input.style.height='auto';guard(()=>send(text));};
const input=$('composer').elements.message;input.oninput=()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,180)+'px';};input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!busy)$('composer').requestSubmit();}};
$('attach').onclick=()=>{if(!busy)$('files').click();};$('files').onchange=e=>{const files=Array.from(e.target.files);e.target.value='';guard(()=>upload(files),'Reading document…');};
$('newChat').onclick=()=>guard(newChat);$('master').onclick=()=>guard(()=>send('list'));$('showMaster').onclick=()=>guard(()=>send('list'));$('add').onclick=()=>guard(()=>send('add'));
$('logout').onclick=()=>guard(async()=>{await api('/auth/logout',{method:'POST'});conv='';selected=null;activeTask=null;$('chatlog').replaceChildren();loginView();});
$('account').onclick=()=>guard(async()=>{const box=task('Change password');const form=node('form',undefined,box);for(const [name,title] of [['old_password','Current password'],['new_password','New password (16+ characters)']]){const label=node('label',title,form);const field=node('input',undefined,label);field.type='password';field.name=name;field.required=true;field.autocomplete=name==='old_password'?'current-password':'new-password';if(name==='new_password')field.minLength=16;}const submit=node('button','Change password',form);submit.className='primary';form.onsubmit=e=>{e.preventDefault();guard(async()=>{await api('/auth/password',{method:'POST',body:Object.fromEntries(new FormData(form))});conv='';loginView();});};scroll();});
$('menu').onclick=()=>document.body.classList.add('sidebar-open');$('closeSidebar').onclick=()=>document.body.classList.remove('sidebar-open');
let drag=0;document.addEventListener('dragenter',e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files')){e.preventDefault();drag++;if(!$('workspace').hidden)$('dropHint').hidden=false;}});document.addEventListener('dragover',e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files'))e.preventDefault();});document.addEventListener('dragleave',()=>{if(--drag<=0){drag=0;$('dropHint').hidden=true;}});document.addEventListener('drop',e=>{e.preventDefault();drag=0;$('dropHint').hidden=true;if(!$('workspace').hidden)guard(()=>upload(Array.from(e.dataTransfer?.files||[])),'Reading document…');});
(async()=>{try{await signedIn();}catch(e){if(!/sign in/i.test(e.message))notice(e.message);}})();
