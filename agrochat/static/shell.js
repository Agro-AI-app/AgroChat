(() => {
  const svg = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>';
  function sync() {
    if (location.pathname === '/auth') {
      location.replace('/profiles' + location.search);
      return;
    }
    const sidebar = document.querySelector('#sidebar');
    const userMenu = sidebar?.querySelector('button img[src*="/profile/image"]')?.closest('button');
    if (userMenu && !sidebar.querySelector('.agrochat-account-link')) {
      const link = document.createElement('a');
      link.className = 'agrochat-account-link';
      link.href = '/account';
      link.dataset.sveltekitReload = '';
      link.title = 'Account & memory';
      link.setAttribute('aria-label', 'Account & memory');
      link.innerHTML = svg + '<span>Account &amp; memory</span>';
      userMenu.parentElement.before(link);
    }
    const projects = sidebar?.querySelector('#sidebar-folders-button');
    if (projects) {
      const title = projects.querySelector(':scope > span');
      if (title?.textContent === 'Folders') title.textContent = 'Projects';
      const add = projects.closest('h2')?.parentElement.querySelector('[aria-label="New Folder"]');
      if (add) add.setAttribute('aria-label', 'New Project');
    }
  }
  sync();
  new MutationObserver(sync).observe(document.body, {subtree: true, childList: true});
  addEventListener('popstate', sync);
})();
