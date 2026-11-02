let me, selected, importId;
const $=id=>document.getElementById(id);
function notice(text){if($('workspace').style.display==='block')bubble(text);else{$('notice').textContent=text;$('notice').style.display='block';}}
async function api(path,options={}){
 if(options.body && !(options.body instanceof FormData)){options.body=JSON.stringify(options.body);options.headers={'Content-Type':'application/json'};}
 const response=await fetch('/api'+path,options);
 const raw=await response.text();let data;
 try{data=raw?JSON.parse(raw):{};}catch{
  if(!response.ok)throw Error(raw.trim().startsWith('<')?'Server error ('+response.status+'). Check the application server.':raw.slice(0,300)||'Request failed ('+response.status+').');
  throw Error('Server returned an unexpected response. Check the application server.');
 }
 if(!response.ok)throw Error(typeof data?.detail==='string'?data.detail:'Request failed ('+response.status+'). Please check your entries.');return data;
}
async function guard(action,button){if(button)button.disabled=true;try{await action();}catch(e){notice(e.message);}finally{if(button)button.disabled=false;}}
function element(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.append(e);return e;}
function button(label,action,parent){const b=element('button',label,parent);b.type='button';b.onclick=()=>guard(action,b);return b;}
function bubble(text,who='assistant'){const b=element('div',text,$('chatlog'));b.className='bubble '+who;$('greeting').hidden=true;$('chatlog').scrollTop=$('chatlog').scrollHeight;return b;}
function table(rows,headers,parent){const wrap=element('div',undefined,parent);wrap.className='scroll';const t=element('table',undefined,wrap);const h=element('tr',undefined,element('thead',undefined,t));headers.forEach(x=>element('th',x,h));const body=element('tbody',undefined,t);for(const row of rows){const tr=element('tr',undefined,body);row.forEach(x=>element('td',x??'',tr));}return t;}
function invitation(url,parent){if(!url)return;const p=element('p','Activation link: ',parent);const link=element('a',url,p);link.href=url;}
async function refresh(){
 me=await api('/me');$('notice').style.display='none';$('login').hidden=true;$('workspace').style.display='block';$('account').textContent=me.name+' · '+me.role.replaceAll('_',' ');
 const canAdd=['operator','owner','hr_admin','recruiter'].includes(me.role);$('add').hidden=!canAdd;$('uploadExcel').hidden=!canAdd;$('manage').hidden=me.role!=='owner';$('passwordButton').hidden=me.stage<2;
 const rows=await api('/employees');$('employees').replaceChildren();if(!rows.length)element('p','No people yet.',$('employees'));
 for(const row of rows)button(row.name+' · '+row.status,()=>openEmployee(row.id),$('employees')).className='row';
 if(me.stage>=3){const status=await api('/status');$('emailStatus').hidden=false;$('emailStatus').textContent='Email: '+(status.email_configured?'configured':'setup needed')+' · Pending: '+status.pending_emails;$('retryEmail').hidden=me.role!=='owner';}
}
async function send(text){
 bubble(text,'user');const result=await api('/chat',{method:'POST',body:{message:text,conversation_id:currentChat.id,employee_id:selected?.id,version:selected?.version,note:$('taskNote')?.value??''}});
 const b=bubble(result.reply);
 if(result.person)table([['Name',result.person.name],['Email',result.person.email],['Phone',result.person.phone],['Client',result.person.client],['Track',result.person.track]],['Field','Value'],b);
 if(result.action==='confirm_person'||result.action==='confirm_user'||result.action==='confirm_role')button('Confirm',()=>send('confirm'),b);
 invitation(result.invitation_url,b);
 if(result.report)element('pre',JSON.stringify(result.report,null,2),b);
 if(result.action==='import')showExcel();
 if(result.action==='list'){const list=bubble('People');for(const row of await api('/employees'))button(row.name,()=>openEmployee(row.id),list);}
 if(result.action==='upload_document')$('attachments').click();
 if(result.action==='export')location.assign('/api/employees/export');
 await refresh();if(result.employee_id)await openEmployee(result.employee_id);else if(selected)await openEmployee(selected.id);
}
async function openEmployee(id){
 selected=await api('/employees/'+id);const d=$('detail');$('chatlog').append(d);d.hidden=false;d.replaceChildren();element('h2',selected.name,d);element('span',selected.status,d).className='tag';element('p',selected.email+' · '+selected.phone,d);element('p',selected.track+(selected.client?' · '+selected.client:''),d).className='muted';
 const editable=selected.status==='draft'&&['operator','owner','hr_admin','employee'].includes(me.role);
 if(editable){const form=element('form',undefined,d);const label=element('label','Government or bank document',form);const file=element('input',undefined,label);file.type='file';file.accept='image/*,.pdf';file.required=true;const submit=element('button','Upload document',form);form.onsubmit=e=>{e.preventDefault();guard(async()=>{const body=new FormData();body.append('file',file.files[0]);const r=await api('/employees/'+id+'/documents',{method:'POST',body});bubble('Document read: '+r.extraction.document_type+(r.classification.needs_review?' · Check classification':''));await openEmployee(id);},submit);};}
 for(const [kind,fields] of Object.entries(selected.fields)){
 const box=element('fieldset',undefined,d);element('legend',kind,box);
 for(const [key,value] of Object.entries(fields)){if(key==='additional_fields')continue;const label=element('label',key.replaceAll('_',' '),box);const input=element('input',undefined,label);input.value=value??'';input.disabled=!editable;input.oninput=()=>{selected.fields[kind][key]=input.value;};}}
 const actions=element('div',undefined,d);actions.className='tools';
 if(editable)button('Confirm fields',async()=>{await api('/employees/'+id+'/fields',{method:'PUT',body:{fields:selected.fields,version:selected.version}});await openEmployee(id);bubble('Fields confirmed.');},actions);
 if(selected.status!=='approved'&&['operator','owner','hr_admin','employee'].includes(me.role))button('Audit',async()=>{const report=await api('/employees/'+id+'/verify',{method:'POST'});const b=bubble(report.summary);element('pre',JSON.stringify(report.issues,null,2),b);await openEmployee(id);},actions);
 if(me.stage>=3){let available=[];
 if(selected.status==='draft'&&['employee','owner','hr_admin'].includes(me.role))available=['submit'];
 if(selected.status==='employee_submitted'&&['owner','hr_admin'].includes(me.role))available=['review','request_changes'];
 if(selected.status==='hr_reviewed'&&['owner','operations'].includes(me.role))available=['approve','request_changes'];
 if(available.length){const label=element('label','Task note',d);const note=element('input',undefined,label);note.id='taskNote';note.placeholder='Review decision or correction required';for(const action of available)button(action.replaceAll('_',' '),async()=>{const result=await api('/chat',{method:'POST',body:{message:action,conversation_id:currentChat.id,employee_id:id,version:selected.version,note:note.value}});bubble(result.reply);await refresh();await openEmployee(id);},actions);}}
 if(Object.keys(selected.verification).length){const details=element('details',undefined,d);element('summary','Audit result',details);element('pre',JSON.stringify(selected.verification,null,2),details);}
 const activity=element('details',undefined,d);element('summary','Activity',activity);for(const item of selected.audit)element('p',item.created+' · '+item.action+(item.details?' · '+item.details:''),activity);
}
$('loginForm').onsubmit=e=>{e.preventDefault();guard(async()=>{await api('/login',{method:'POST',body:Object.fromEntries(new FormData(e.target))});await refresh();bubble('Hi. Type add to add a person.');},e.submitter);};
$('chatForm').onsubmit=e=>{e.preventDefault();const text=e.target.elements.message.value;e.target.reset();guard(()=>send(text),e.submitter);};
$('add').onclick=()=>guard(()=>send('add'));
$('uploadExcel').onclick=()=>{$('attachments').accept='.xls,.xlsx';$('attachments').click();};
$('excelForm').onsubmit=e=>{e.preventDefault();guard(async()=>{
 await previewExcel(new FormData(e.target));},e.submitter);};
async function previewExcel(formData){
 const result=await api('/imports/preview',{method:'POST',body:formData});importId=result.import_id;const p=$('preview');p.replaceChildren();element('h3','Preview · '+result.sheet,p);element('p',result.accepted.length+' valid · '+result.rejected.length+' skipped',p);
 if(result.sheets.length>1)element('p','Worksheets: '+result.sheets.join(', ')+'. Enter a worksheet name above to preview another.',p).className='muted';
 table(result.accepted.map(r=>[r.row,r.person.name,r.person.email,r.person.phone,r.person.client,r.person.track]),['Row','Name','Email','Phone','Client','Track'],p);
 if(result.rejected.length){const details=element('details',undefined,p);details.open=true;element('summary','Skipped rows',details);table(result.rejected.map(r=>[r.row,r.name,r.issues.join(' ')]),['Row','Name','Reason'],details);}
 if(result.accepted.length)button('Import '+result.accepted.length+' people',async()=>{const confirmation=await api('/imports/'+importId+'/confirm',{method:'POST'});const b=bubble('Imported '+confirmation.count+' people.');for(const person of confirmation.added){if(person.invitation_url){element('strong',person.name,b);invitation(person.invitation_url,b);}}p.replaceChildren();$('excelPanel').hidden=true;await refresh();},p);
 }
$('logout').onclick=()=>guard(async()=>{await api('/logout',{method:'POST'});location.reload();});
$('manage').onclick=()=>guard(async()=>{$('chatlog').append($('usersPanel'));$('usersPanel').hidden=!$('usersPanel').hidden;const users=await api('/users');$('users').replaceChildren();for(const user of users){const p=element('p',user.name+' · '+user.email+' ',$('users'));const select=element('select',undefined,p);select.setAttribute('aria-label','Role for '+user.email);for(const role of ['owner','hr_admin','operations','employee','recruiter']){const option=element('option',role,select);option.value=role;option.selected=user.role===role;}button('Save role',async()=>{await api('/users/'+user.id+'/role',{method:'PUT',body:{role:select.value}});notice('Role saved.');},p);}});
$('passwordButton').onclick=()=>{$('chatlog').append($('passwordPanel'));$('passwordPanel').hidden=!$('passwordPanel').hidden;};
$('passwordForm').onsubmit=e=>{e.preventDefault();guard(async()=>{await api('/password',{method:'POST',body:Object.fromEntries(new FormData(e.target))});location.reload();},e.submitter);};
$('activationForm').onsubmit=e=>{e.preventDefault();guard(async()=>{const token=new URLSearchParams(location.hash.slice(1)).get('invite');await api('/activate',{method:'POST',body:{token,password:e.target.elements.password.value}});history.replaceState(null,'','/');$('activation').hidden=true;$('login').hidden=false;notice('Account ready. Sign in.');},e.submitter);};
$('retryEmail').onclick=()=>guard(async()=>{const result=await api('/email/retry',{method:'POST'});bubble('Email deliveries: '+result.sent+' sent, '+result.failed+' pending.');await refresh();});
guard(async()=>{if(location.hash.startsWith('#invite=')){$('login').hidden=true;$('activation').hidden=false;return;}try{await refresh();}catch(e){if(!/sign in/i.test(e.message))throw e;}});

// Conversation transcripts stay in memory; document data remains on the server.
const chats=[];let currentChat;let busy=false;
function showExcel(){ $('chatlog').append($('excelPanel'));$('excelPanel').hidden=false; }
function renderConversations(){ $('conversations').replaceChildren();for(const chat of chats){const b=button(chat.title,()=>switchChat(chat),$('conversations'));b.className=chat===currentChat?'active':'';} }
function switchChat(chat){if(busy||chat===currentChat)return;document.body.classList.remove('sidebar-open');if(currentChat){currentChat.nodes=Array.from($('chatlog').childNodes).filter(n=>!['detail','excelPanel','usersPanel','passwordPanel'].includes(n.id));currentChat.employee=selected?.id;}for(const id of ['detail','excelPanel','usersPanel','passwordPanel']){$('conversation').append($(id));$(id).hidden=true;}$('chatlog').replaceChildren(...chat.nodes);currentChat=chat;$('chatTitle').textContent=chat.title;selected=null;$('greeting').hidden=chat.nodes.length>0;renderConversations();if(chat.employee)guard(()=>openEmployee(chat.employee));}
function newChat(){if(busy)return;const chat={id:Array.from(crypto.getRandomValues(new Uint32Array(4)),n=>n.toString(16).padStart(8,'0')).join(''),title:'New conversation',nodes:[],employee:null};chats.unshift(chat);switchChat(chat);}
$('newChat').onclick=()=>guard(async()=>{await api('/me');newChat();});
$('peopleToggle').onclick=()=>{$('employees').hidden=!$('employees').hidden;};$('employees').hidden=true;
for(const id of ['manage','passwordButton','logout'])$('accountTools').append($(id));
// Keep only three entry actions; all forms and reviews appear in the chat.
const tools=$('add').parentElement;for(const a of tools.querySelectorAll('a'))a.remove();button('People',()=>send('list'),tools);
$('attach').onclick=()=>{$('attachments').accept='.xls,.xlsx,.pdf,image/*';$('attachments').click();};
async function acceptFiles(files){if(busy)return;busy=true;$('attach').disabled=true;try{await api('/me');for(const file of files){$('attachmentsStatus').textContent='Reading '+file.name+'…';if(/\.xlsx?$/i.test(file.name)){showExcel();const input=$('excelForm').elements.file;const transfer=new DataTransfer();transfer.items.add(file);input.files=transfer.files;await previewExcel(new FormData($('excelForm')));if(files.length>1)bubble('Import this workbook first, then attach the next file.');break;}else{if(!selected){bubble('Choose a person before adding their document.');const b=bubble('People');for(const row of await api('/employees'))button(row.name,async()=>{await openEmployee(row.id);await acceptFiles([file]);},b);break;}const body=new FormData();body.append('file',file);bubble(file.name,'user');const result=await api('/employees/'+selected.id+'/documents',{method:'POST',body});bubble('Document read: '+result.extraction.document_type+'. Check the fields below.');await openEmployee(selected.id);}}}finally{busy=false;$('attach').disabled=false;$('attachmentsStatus').textContent='';$('attachments').value='';}}
$('attachments').onchange=e=>guard(()=>acceptFiles(Array.from(e.target.files)));
let dragDepth=0;document.addEventListener('dragenter',e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files')){e.preventDefault();dragDepth++;$('dropHint').hidden=false;}});document.addEventListener('dragover',e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files'))e.preventDefault();});document.addEventListener('dragleave',()=>{if(--dragDepth<=0){dragDepth=0;$('dropHint').hidden=true;}});document.addEventListener('drop',e=>{e.preventDefault();dragDepth=0;$('dropHint').hidden=true;guard(()=>acceptFiles(Array.from(e.dataTransfer?.files||[])));});
const originalSend=send;send=async text=>{if(busy)return;busy=true;$('chatForm').querySelectorAll('button,input,textarea').forEach(e=>e.disabled=true);try{if(currentChat.title==='New conversation'){currentChat.title=text.slice(0,36);$('chatTitle').textContent=currentChat.title;renderConversations();}await originalSend(text);}finally{busy=false;$('chatForm').querySelectorAll('button,input,textarea').forEach(e=>e.disabled=false);$('chatForm').elements.message.focus();}};
newChat();

$('menuToggle').onclick=()=>document.body.classList.toggle('sidebar-open');
$('sidebarClose').onclick=()=>document.body.classList.remove('sidebar-open');
const messageBox=$('chatForm').elements.message;
messageBox.oninput=()=>{messageBox.style.height='auto';messageBox.style.height=Math.min(messageBox.scrollHeight,200)+'px';};
messageBox.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(messageBox.value.trim()&&!busy)$('chatForm').requestSubmit();}};
