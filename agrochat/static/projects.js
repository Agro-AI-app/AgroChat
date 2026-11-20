// Open WebUI owns the composer, chat list and folder records. The workspace
// adds project controls alongside them without replacing their event handlers.
const folders = '/api/v1/folders/';
async function request(url, data) {
  const form = data instanceof FormData;
  const response = await fetch(url, data === undefined ? {cache:'no-store'} : {
    method:'POST', headers:form ? {} : {'Content-Type':'application/json'}, body:form ? data : JSON.stringify(data)
  });
  if (response.status === 401) { location.replace('/profiles'); throw Error('Sign in to continue.'); }
  const value = await response.json();
  if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : 'Could not complete the request.');
  return value;
}
function element(tag, text) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  return node;
}
function dialog(title, fields, submit, saveLabel='Save') {
  const box = element('dialog'); box.className = 'agro-dialog'; box.setAttribute('aria-label',title);
  const form = element('form'), status = element('p'), actions = element('footer');
  status.setAttribute('role','status');
  const cancel = element('button',submit ? 'Cancel' : 'Close'); cancel.type='button'; cancel.onclick=()=>box.close();
  actions.append(cancel);
  form.append(element('h2',title), ...fields, status, actions);
  if (submit) {
    const save = element('button',saveLabel); actions.append(save);
    form.onsubmit = async e => {
      e.preventDefault(); save.disabled=cancel.disabled=true; status.textContent='Saving…';
      try { await submit(); box.close(); } catch(err) { status.textContent=err.message; }
      finally { save.disabled=cancel.disabled=false; }
    };
    box.oncancel=e=>{ if(save.disabled)e.preventDefault(); };
  }
  box.append(form); document.body.append(box); box.onclose=()=>box.remove(); box.showModal();
}
function field(label, input) { const node=element('label',label); node.append(input); return node; }
function picker() { const input=element('input'); input.type='file'; input.multiple=true; return input; }
async function upload(input) {
  const files=[];
  for(const file of input.files) {
    const body=new FormData(); body.append('file',file);
    const saved=await request('/api/v1/files/?process_in_background=false',body);
    const processing=await request(`/api/v1/files/${encodeURIComponent(saved.id)}/process/status`);
    if(processing.status!=='completed') throw Error(`Could not process ${file.name}. Check the file and try again.`);
    files.push({id:saved.id,type:'file',name:file.name});
  }
  return files;
}
function createProject() {
  const name=element('input'), instructions=element('textarea'), input=picker();
  name.required=true; name.maxLength=160; name.placeholder='e.g. Spring field trials';
  instructions.placeholder='Describe the goal or add instructions for the assistant.';
  dialog('New project',[field('Name',name),field('What do you want to work on? (optional)',instructions),field('Context files (optional)',input)],async()=>{
    if(!name.value.trim()) throw Error('Enter a project name.');
    const project=await request(folders,{name:name.value.trim(),data:{system_prompt:instructions.value,files:await upload(input)}});
    location.assign('/folders/'+encodeURIComponent(project.id));
  },'Create project');
}
async function manage(id, action) {
  const path=folders+encodeURIComponent(id);
  try {
    if(action==='Memory') {
      const memory=await request(`/agrochat/api/projects/${encodeURIComponent(id)}/memory`);
      dialog('Project memory',[element('p', memory.summary || 'No summary yet. Memory is built from recent project chats during scheduled refreshes.'),element('small',memory.paused?'Memory updates are paused.':'Memory updates are enabled.')]); return;
    }
    const project=await request(path), data=project.data || {};
    if(action==='Instructions') {
      const input=element('textarea'); input.value=data.system_prompt || '';
      dialog('Project instructions',[field('Apply to every chat in this project',input)],()=>request(path+'/update',{data:{system_prompt:input.value}}));
    } else {
      const list=element('div'), items=[...(data.files || [])], input=picker();
      for(const item of items) {
        const row=element('label'), check=element('input'); check.type='checkbox'; check.checked=true;
        check.onchange=()=>{item.keep=check.checked;}; row.append(check,document.createTextNode(item.name || item.id)); list.append(row);
      }
      dialog('Project context',[element('p',items.length?'Keep the files checked to include them in project chats.':'No files attached to this project.'),list,field('Add context files',input)],async()=>request(path+'/update',{data:{files:[...items.filter(i=>i.keep!==false).map(({keep,...item})=>item),...await upload(input)]}}));
    }
  } catch(err) { dialog(action,[element('p',err.message)]); }
}
async function indexPage() {
  const list=document.querySelector('#project-list'), search=document.querySelector('#search-projects');
  document.querySelector('#new-project').onclick=createProject;
  try {
    const projects=(await request(folders)).sort((a,b)=>b.updated_at-a.updated_at);
    function render() {
      list.replaceChildren();
      for(const p of projects.filter(p=>p.name.toLowerCase().includes(search.value.toLowerCase()))) {
        const a=element('a',p.name); a.href='/folders/'+encodeURIComponent(p.id);
        a.append(element('small',new Date(p.updated_at*1000).toLocaleDateString())); list.append(a);
      }
      if(!list.childElementCount) list.textContent=projects.length?'No matching projects.':'Create a project to start your first chat.';
    }
    search.oninput=render; render();
  } catch(err) { list.textContent=err.message; }
}
function workspace() {
  const section=document.querySelector('.folder-workspace'), id=/^\/folders\/([^/]+)\/?$/.exec(location.pathname)?.[1];
  if(!section || !id) return;
  const host=section.parentElement;
  if(host.querySelector('.agro-project-panel')) return;
  host.classList.add('agro-workspace');
  const panel=element('aside'); panel.className='agro-project-panel'; panel.setAttribute('aria-label','Project settings');
  for(const [label,verb] of [['Instructions','Edit'],['Context','Manage'],['Memory','View']]) {
    const button=element('button',label); button.append(element('span',verb));
    button.onclick=()=>manage(location.pathname.split('/')[2],label); panel.append(button);
  }
  const link=element('a','← All projects'); link.href='/projects'; link.dataset.sveltekitReload=''; panel.append(link); host.append(panel);
}
if(document.querySelector('#project-list')) indexPage();
else {
  document.addEventListener('click',e=>{
    if(e.target.closest('#sidebar [aria-label="New Project"], #sidebar [aria-label="New Folder"]')) { e.preventDefault(); e.stopImmediatePropagation(); createProject(); }
  },true);
  new MutationObserver(workspace).observe(document.body,{subtree:true,childList:true}); workspace();
}
