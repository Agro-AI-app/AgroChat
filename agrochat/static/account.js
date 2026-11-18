import {api, resetBrowser, signOut} from './client.js';

const $ = selector => document.querySelector(selector);
let account;
let memory;

function showError(error) { $('#error').textContent = error.message; }

function summary(target, title, text) {
  const details = document.createElement('details');
  const label = document.createElement('summary');
  label.textContent = title;
  const content = document.createElement('p');
  content.className = 'summary-text';
  content.textContent = text || 'No summary yet.';
  details.append(label, content);
  target.append(details);
}

async function loadMemory() {
  memory = await api('/account/memory');
  $('#pause').textContent = memory.paused ? 'Resume memory' : 'Pause memory';
  $('#memory-status').textContent = memory.paused ? 'Memory is paused.' : memory.updated_at ?
    'Last checked ' + new Date(memory.updated_at * 1000).toLocaleString() : 'Waiting for the first memory update.';
  const target = $('#memories');
  target.replaceChildren();
  if (memory.paused) return;
  const preferences = Object.entries(memory.preferences).map(([key, value]) => `${key}: ${value}`).join(', ');
  summary(target, 'General profile memory', [memory.profile, preferences].filter(Boolean).join('\n\n'));
  for (const entry of memory.projects) summary(target, `Project: ${entry.name}`, entry.summary);
  for (const entry of memory.chats) summary(target, `Chat: ${entry.title}${entry.project ? ` (${entry.project})` : ''}`, entry.summary);
}

function refreshPhoto() { $('#photo').src = `/api/v1/users/${account.id}/profile/image?v=${Date.now()}`; }

$('#pause').onclick = () => api('/account/memory', {paused: !memory.paused}).then(loadMemory).catch(showError);
$('#reset').onclick = () => {
  if (confirm('Clear all AgroChat memories? Saved chats will be kept. Future chat activity can build new memory.'))
    api('/account/memory', {reset: true}).then(loadMemory).catch(showError);
};
$('#switch').onclick = () => signOut().then(() => location.replace('/profiles')).catch(showError);
$('#remove-photo').onclick = () => api('/account/photo', {image: null}).then(refreshPhoto).catch(showError);
$('#photo-file').onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size > 5 * 1024 * 1024)
      throw new Error('Choose a JPEG, PNG or WebP up to 5 MB.');
    const image = await createImageBitmap(file);
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 256;
    const side = Math.min(image.width, image.height);
    canvas.getContext('2d').drawImage(image, (image.width - side) / 2, (image.height - side) / 2, side, side, 0, 0, 256, 256);
    image.close();
    await api('/account/photo', {image: canvas.toDataURL('image/jpeg', 0.85)});
    refreshPhoto();
  } catch (e) { showError(e); } finally { event.target.value = ''; }
};

const dialog = $('#delete-dialog');
const form = $('#delete-form');
const submit = $('#delete-submit');
$('#review').onclick = () => dialog.showModal();
$('#cancel').onclick = () => dialog.close();
dialog.addEventListener('close', () => { form.reset(); submit.disabled = true; $('#delete-error').textContent = ''; });
form.oninput = () => { submit.disabled = form.elements.full_name.value.trim() !== account.name || !form.elements.password.value; };
form.onsubmit = async event => {
  event.preventDefault();
  submit.disabled = true;
  try {
    await api('/account/delete', Object.fromEntries(new FormData(form)));
    resetBrowser();
    location.replace('/profiles');
  } catch (e) {
    $('#delete-error').textContent = e.message;
    form.oninput();
  }
};

try {
  account = await api('/account');
  $('#name').textContent = $('#confirm-name').textContent = account.name;
  refreshPhoto();
  $('main').hidden = false;
  await loadMemory().catch(showError);
} catch {
  location.replace('/profiles?redirect=/account');
}
