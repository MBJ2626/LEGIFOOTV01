(function(){
  const body = document.body;
  const storageKey = 'legifoot-theme';

  function applyTheme(theme){
    const normalized = (theme === 'dark' || theme === 'deep-night') ? 'oled' : theme;
    body.classList.remove('theme-dark', 'theme-oled', 'theme-deep-night');
    if(normalized === 'oled'){
      body.classList.add('theme-oled', 'theme-deep-night');
    }
    document.querySelectorAll('[data-theme-toggle] .theme-toggle-icon').forEach(icon => {
      icon.textContent = normalized === 'oled' ? '☀' : '◐';
    });
  }
  const savedTheme = localStorage.getItem(storageKey) || 'light';
  applyTheme(savedTheme);

  document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = body.classList.contains('theme-oled') ? 'light' : 'oled';
      localStorage.setItem(storageKey, next);
      applyTheme(next);
    });
  });

  const openBtn = document.querySelector('[data-nav-open]');
  const closeTargets = document.querySelectorAll('[data-nav-close], .sidebar nav a');
  if(openBtn){ openBtn.addEventListener('click', () => body.classList.add('nav-open')); }
  closeTargets.forEach(el => el.addEventListener('click', () => body.classList.remove('nav-open')));

  const input = document.getElementById('files');
  const label = document.querySelector('.dropzone');
  const list = document.getElementById('file-list');
  if(input && list){
    input.addEventListener('change', () => {
      if(!input.files.length){ list.textContent = 'Aucun fichier sélectionné'; return; }
      list.textContent = Array.from(input.files).map(f => f.name).join(' · ');
    });
  }
  if(label){
    ['dragenter','dragover'].forEach(evt => label.addEventListener(evt, e => { e.preventDefault(); label.classList.add('dragover'); }));
    ['dragleave','drop'].forEach(evt => label.addEventListener(evt, e => { e.preventDefault(); label.classList.remove('dragover'); }));
  }

  document.querySelectorAll('.table-filter').forEach(filter => {
    const table = document.getElementById(filter.dataset.table);
    if(!table) return;
    filter.addEventListener('input', () => {
      const q = filter.value.toLowerCase().trim();
      table.querySelectorAll('tbody tr').forEach(row => {
        row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  });

  function applyMobileTableLabels(){
    document.querySelectorAll('table').forEach(table => {
      const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
      table.querySelectorAll('tbody tr').forEach(row => {
        Array.from(row.children).forEach((cell, index) => {
          if(headers[index]) cell.setAttribute('data-label', headers[index]);
        });
      });
    });
  }
  applyMobileTableLabels();

  window.addEventListener('load', () => {
    const loader = document.getElementById('app-loader');
    if(loader){
      setTimeout(() => loader.classList.add('is-hidden'), 350);
    }
  });
})();


// LEGIFOOT premium micro-interactions, favorites, dynamic helpers
(function(){
  const toastStack = document.createElement('div');
  toastStack.className = 'toast-stack';
  document.body.appendChild(toastStack);
  function toast(msg){
    const el=document.createElement('div'); el.className='toast'; el.textContent=msg; toastStack.appendChild(el);
    setTimeout(()=>{el.style.opacity='0'; el.style.transform='translateY(10px)';}, 2400);
    setTimeout(()=>el.remove(), 2900);
  }
  document.querySelectorAll('form').forEach(f=>{
    f.addEventListener('submit',()=>{ if(!f.classList.contains('global-search')) toast('Action envoyée'); });
  });
  const favKey='legifoot-favorites-v1';
  const readFav=()=>JSON.parse(localStorage.getItem(favKey)||'{}');
  const writeFav=(v)=>localStorage.setItem(favKey, JSON.stringify(v));
  function refreshFavorites(){
    const fav=readFav();
    document.querySelectorAll('.favorite-btn').forEach(btn=>{
      const key=(btn.dataset.favType||'item')+':'+(btn.dataset.favId||'');
      const active=!!fav[key];
      btn.classList.toggle('is-favorite', active);
      if(btn.textContent.includes('Suivre')) btn.textContent=active?'★ Suivi':'☆ Suivre';
      else btn.textContent=active?'★':'☆';
    });
  }
  document.querySelectorAll('.favorite-btn').forEach(btn=>{
    btn.addEventListener('click', (e)=>{
      e.preventDefault(); e.stopPropagation();
      const fav=readFav(); const key=(btn.dataset.favType||'item')+':'+(btn.dataset.favId||'');
      fav[key] ? delete fav[key] : fav[key]=true; writeFav(fav); refreshFavorites(); toast(fav[key]?'Ajouté aux suivis':'Retiré des suivis');
    });
  });
  refreshFavorites();
  document.querySelectorAll('textarea').forEach(t=>{
    if(t.placeholder && t.placeholder.includes(';')){
      t.dataset.dynamicList='1';
      const b=document.createElement('button'); b.type='button'; b.className='btn small secondary'; b.textContent='+ Ajouter une ligne exemple';
      b.addEventListener('click',()=>{ t.value += (t.value.trim()?'\n':'') + (t.placeholder.split('\n')[0] || ''); t.focus(); toast('Ligne exemple ajoutée'); });
      t.insertAdjacentElement('afterend', b);
    }
  });
  document.querySelectorAll('table').forEach(table=>{
    const headers=Array.from(table.querySelectorAll('thead th')).map(th=>th.textContent.trim());
    table.querySelectorAll('tbody tr').forEach(tr=>{
      Array.from(tr.children).forEach((td,i)=>td.setAttribute('data-label', headers[i]||''));
    });
  });
})();

// LEGIFOOT UX optimization v25
(function(){
  document.querySelectorAll('[data-filter-toggle]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const card=btn.closest('.filter-drawer-card');
      if(card) card.classList.toggle('open');
    });
  });
  document.querySelectorAll('[data-view-btn]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const panel=document.querySelector(btn.dataset.target);
      if(panel){ panel.dataset.view=btn.dataset.view; localStorage.setItem('legifoot-view-'+(btn.dataset.target||''), btn.dataset.view); }
    });
  });
  document.querySelectorAll('[data-view-panel]').forEach(panel=>{
    const saved=localStorage.getItem('legifoot-view-#'+panel.id);
    if(saved) panel.dataset.view=saved;
  });
  document.querySelectorAll('[data-tabs]').forEach(nav=>{
    const buttons=nav.querySelectorAll('[data-tab]');
    buttons.forEach(btn=>btn.addEventListener('click',()=>{
      buttons.forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
      const panel=document.getElementById(btn.dataset.tab);
      if(panel) panel.classList.add('active');
      history.replaceState(null,'','#'+btn.dataset.tab);
    }));
  });
  const hash=(location.hash||'').replace('#','');
  if(hash){ const btn=document.querySelector(`[data-tab="${hash}"]`); if(btn) btn.click(); }
  const params=new URLSearchParams(location.search);
  const toast=params.get('toast') || params.get('saved');
  if(toast){
    const el=document.createElement('div'); el.className='toast'; el.textContent=toast==='1'?'Action enregistrée':toast;
    document.body.appendChild(el); setTimeout(()=>el.classList.add('show'),100); setTimeout(()=>el.classList.remove('show'),3500);
  }
  function favKey(){return 'legifoot-favorites'}
  function readFavs(){try{return JSON.parse(localStorage.getItem(favKey())||'[]')}catch(e){return[]}}
  function writeFavs(v){localStorage.setItem(favKey(), JSON.stringify(v))}
  document.querySelectorAll('.favorite-btn').forEach(btn=>{
    const item={type:btn.dataset.favType,id:btn.dataset.favId,label:btn.dataset.favLabel||document.querySelector('h1')?.innerText||'Favori',url:location.pathname};
    const exists=()=>readFavs().some(f=>f.type===item.type&&String(f.id)===String(item.id));
    if(exists()){btn.classList.add('fav-active');btn.textContent='★ Suivi'}
    btn.addEventListener('click',()=>{let favs=readFavs(); if(exists()){favs=favs.filter(f=>!(f.type===item.type&&String(f.id)===String(item.id))); btn.classList.remove('fav-active'); btn.textContent='☆ Suivre';} else {favs.push(item); btn.classList.add('fav-active'); btn.textContent='★ Suivi';} writeFavs(favs);});
  });
  const favList=document.getElementById('favorites-list');
  if(favList){ const favs=readFavs(); favList.innerHTML=favs.length?favs.map(f=>`<article class="data-card"><strong>${f.label}</strong><span class="badge outline">${f.type}</span><a class="btn secondary small" href="${f.url}">Ouvrir</a></article>`).join(''):'<p class="empty">Aucun favori enregistré sur ce navigateur.</p>'; }
  document.querySelectorAll('[data-clear-favorites]').forEach(btn=>btn.addEventListener('click',()=>{writeFavs([]); location.reload();}));
})();

// Discipline center: bulk alert selection helpers
(function(){
  const checkboxes = Array.from(document.querySelectorAll('[data-alert-checkbox]'));
  if(!checkboxes.length) return;
  const countEl = document.querySelector('[data-selected-count]');
  const refresh = () => {
    const selected = checkboxes.filter(cb => cb.checked).length;
    if(countEl) countEl.textContent = String(selected);
  };
  checkboxes.forEach(cb => cb.addEventListener('change', refresh));
  document.querySelectorAll('[data-select-visible-alerts]').forEach(btn => {
    btn.addEventListener('click', () => {
      checkboxes.forEach(cb => { cb.checked = true; });
      refresh();
    });
  });
  document.querySelectorAll('[data-clear-alert-selection]').forEach(btn => {
    btn.addEventListener('click', () => {
      checkboxes.forEach(cb => { cb.checked = false; });
      refresh();
    });
  });
  document.querySelectorAll('[data-select-alert-column]').forEach(btn => {
    btn.addEventListener('click', () => {
      const column = btn.closest('.discipline-column');
      if(!column) return;
      column.querySelectorAll('[data-alert-checkbox]').forEach(cb => { cb.checked = true; });
      refresh();
    });
  });
  refresh();
})();
