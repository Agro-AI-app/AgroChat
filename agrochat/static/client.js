export async function api(path, data, method = 'POST') {
  const response = await fetch('/agrochat/api' + path, data === undefined ? {cache: 'no-store'} : {
    method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(typeof result.detail === 'string' ? result.detail : 'Check the form and try again.');
    error.status = response.status;
    throw error;
  }
  return result;
}

export function resetBrowser() {
  const keep = ['theme', 'locale', 'sidebar', 'sidebarWidth'];
  const settings = keep.map(key => [key, localStorage.getItem(key)]);
  localStorage.clear();
  for (const [key, value] of settings) if (value !== null) localStorage.setItem(key, value);
  sessionStorage.clear();
}

export async function signOut() {
  const response = await fetch('/api/v1/auths/signout', {method: 'POST'});
  if (!response.ok) throw new Error('Could not sign out. Try again.');
  resetBrowser();
}
