import {api, resetBrowser, signOut} from './client.js';

const list = document.querySelector('#profiles');
const status = document.querySelector('#status');
const dialog = document.querySelector('#dialog');
const form = document.querySelector('#form');
const submit = document.querySelector('#submit');
const error = document.querySelector('#error');
const fields = form.elements;
const params = new URLSearchParams(location.search);
let current;
let requiresCode = false;

function tile(label, slot, create, handler) {
  const button = document.createElement('button');
  button.className = create ? 'tile add' : 'tile';
  const face = document.createElement('span');
  face.className = 'face';
  face.dataset.slot = slot;
  face.setAttribute('aria-hidden', 'true');
  face.textContent = create ? '+' : label.split(' ').map(part => Array.from(part)[0]).slice(0, 2).join('').toUpperCase();
  const name = document.createElement('span');
  name.textContent = label;
  button.append(face, name);
  button.addEventListener('click', handler);
  return button;
}

function open(profile) {
  current = profile;
  form.reset();
  error.textContent = '';
  const create = !current;
  document.querySelector('#dialog-title').textContent = current?.name ?? 'Create a profile';
  document.querySelector('#subtitle').textContent = create ? 'Use your real name and a password of at least 12 characters.' : 'Enter your password to open your workspace.';
  document.querySelector('#new-fields').hidden = !create;
  document.querySelector('#confirmation').hidden = !create;
  document.querySelector('#enrollment').hidden = !(create && requiresCode);
  fields.first_name.required = fields.surname.required = fields.confirm_password.required = create;
  fields.enrollment_code.required = create && requiresCode;
  fields.password.autocomplete = create ? 'new-password' : 'current-password';
  fields.password.minLength = create ? 12 : 0;
  submit.textContent = create ? 'Create profile' : 'Sign in';
  if (!dialog.open) dialog.showModal();
  (create ? fields.first_name : fields.password).focus();
}

async function load() {
  const result = await api('/profiles');
  requiresCode = result.code_required;
  list.replaceChildren(...result.profiles.map(profile => tile(profile.name, profile.slot, false, () => open(profile))));
  if (result.profiles.length < result.limit) list.append(tile('Add profile', '', true, () => open(null)));
  status.textContent = `${result.profiles.length} of ${result.limit} profiles in use`;
  return result.profiles;
}

document.querySelector('#cancel').onclick = () => dialog.close();
dialog.addEventListener('close', () => form.reset());
form.addEventListener('submit', async event => {
  event.preventDefault();
  submit.disabled = true;
  error.textContent = '';
  const data = Object.fromEntries(new FormData(form));
  const selected = current;
  try {
    if (!selected) {
      const profile = await api('/profiles', data);
      await load();
      open(profile);
      return;
    }
    if (localStorage.getItem('token')) await signOut();
    const result = await api('/login', {profile_id: selected.id, password: data.password});
    if (!result.token) throw new Error('Could not start a session.');
    resetBrowser();
    localStorage.setItem('token', result.token);
    const target = new URL(params.get('redirect') || '/', location.origin);
    location.replace(target.origin === location.origin && !['/auth', '/profiles'].includes(target.pathname) ? target.href : '/');
  } catch (e) {
    if (selected && e.status === 404) {
      const profiles = await load().catch(() => null);
      if (profiles && !profiles.some(profile => profile.id === selected.id)) {
        if (current === selected) dialog.close();
        status.textContent = 'That profile is no longer available. The profile list has been refreshed.';
        return;
      }
    }
    error.textContent = e.message;
  } finally {
    submit.disabled = false;
  }
});

if (params.get('state') === 'logout') resetBrowser();
load().catch(e => { status.textContent = e.message; });
