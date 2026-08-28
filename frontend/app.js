// ============================================
// NIMM — app.js
// ============================================

// ══════════════════════════════════════════
// TTS
// ══════════════════════════════════════════

let _currentAudio    = null;
let _currentTTSBtn   = null;
let _loaderInterval  = null;

const spk0 = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 5.5h2.5l4-3v11l-4-3H2z"/></svg>`;
const spk1 = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 5.5h2.5l4-3v11l-4-3H2z"/><path d="M10.5 5.5a3.5 3.5 0 0 1 0 5"/></svg>`;
const spk2 = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 5.5h2.5l4-3v11l-4-3H2z"/><path d="M10.5 5.5a3.5 3.5 0 0 1 0 5"/><path d="M12.5 3.5a6 6 0 0 1 0 9"/></svg>`;
const SVG_ACT = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="4.5" width="8" height="9.5" rx="1.5"/><path d="M3.5 11V2.5h7"/></svg>`;
const SVG_MIC = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="1.5" width="6" height="8" rx="3"/><path d="M3 9a5 5 0 0 0 10 0"/><line x1="8" y1="14" x2="8" y2="11.5"/><line x1="5.5" y1="14" x2="10.5" y2="14"/></svg>`;
const SVG_CHECK = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="2.5,8.5 6.5,12.5 13.5,3.5"/></svg>`;
const SVG_NEWLINE = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="2" x2="8" y2="14"/><polyline points="3,9 8,14 13,9"/></svg>`;
const SVG_LOADING = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6" stroke-dasharray="28" stroke-dashoffset="8"><animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="1s" repeatCount="indefinite"/></circle></svg>`;
const SVG_STOP = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="10" height="10" rx="1.5"/></svg>`;
const SVG_PAUSE = `<svg viewBox="0 0 16 16" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><line x1="4.5" y1="2" x2="4.5" y2="14"/><line x1="11.5" y1="2" x2="11.5" y2="14"/></svg>`;

// Initialisation marked — une seule fois
if (window.marked) {
    marked.setOptions({ breaks: true, gfm: true });
    // Liens externes → nouvel onglet
    const _renderer = new marked.Renderer();
    _renderer.link = (href, title, text) => {
        const h = (href && typeof href === 'object') ? href.href : (href || '');
        const t = (href && typeof href === 'object') ? href.title : (title || '');
        const txt = (href && typeof href === 'object') ? href.text : (text || '');
        return `<a href="${h}" title="${t}" target="_blank" rel="noopener noreferrer">${txt}</a>`;
    };
    marked.setOptions({ renderer: _renderer });
}

// Sécurité (anti-XSS) : échappement HTML + désinfection du Markdown rendu
function _safeHTML(h){ try { return window.DOMPurify ? DOMPurify.sanitize(h, {ADD_ATTR:['target','rel']}) : h; } catch(e){ return h; } }

// Rend cliquables les URLs sans schéma (domaine + chemin) que marked n'auto-lie pas
// (ex. "support.apple.com/fr-fr/122208"). Conservateur : exige un /chemin pour éviter
// les faux positifs (main.py, image.png) ; ignore les liens/URLs déjà formés.
function _linkifyBareUrls(text){
    try {
        return text.replace(
            /(^|[\s(>«"*_])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})(\/[^\s)<>\]»"*_]*)/gi,
            function(m, pre, domain, path){
                var trail = "";
                var mt = path.match(/[.,;:!?]+$/);
                if (mt) { trail = mt[0]; path = path.slice(0, -trail.length); }
                return pre + "[" + domain + path + "](https://" + domain + path + ")" + trail;
            }
        );
    } catch(e) { return text; }
}

// ── Accessibilité : bips de génération ──
const _ac = new (window.AudioContext || window.webkitAudioContext)();
function _bip(freq = 440, duration = 80, gain = 0.08) {
    try {
        const osc = _ac.createOscillator();
        const vol = _ac.createGain();
        osc.connect(vol); vol.connect(_ac.destination);
        osc.type = 'sine';
        osc.frequency.value = freq;
        vol.gain.setValueAtTime(gain, _ac.currentTime);
        vol.gain.exponentialRampToValueAtTime(0.001, _ac.currentTime + duration / 1000);
        osc.start(_ac.currentTime);
        osc.stop(_ac.currentTime + duration / 1000);
    } catch(e) {}
}

// ── Accessibilité : Échap ferme les modales + arrête le stream ──
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => _closeModal(m));
        const stopBtn = document.getElementById('stop-btn');
        if (stopBtn && !stopBtn.hidden) stopStream();
    }
});

// ── Gestion focus/clavier pour les menus déroulants ──
// Appelée à chaque ouverture d'un menu : focus le premier item,
// puis gère flèches, Échap et Tab.
function _menuKeyboard(toggleBtn, menu, hideFn) {
    // Focus immédiat sur le premier item
    const items = () => [...menu.querySelectorAll('[role="menuitem"]:not([disabled])')];
    const first = items()[0];
    if (first) first.focus();

    // Navigation clavier — un seul listener par instance de menu
    if (menu.dataset.kbReady) return;
    menu.dataset.kbReady = '1';
    menu.addEventListener('keydown', (e) => {
        const all = items();
        const idx = all.indexOf(document.activeElement);
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            all[(idx + 1) % all.length]?.focus();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            all[(idx - 1 + all.length) % all.length]?.focus();
        } else if (e.key === 'Escape') {
            e.stopPropagation();
            hideFn();
            toggleBtn?.focus();
        } else if (e.key === 'Tab') {
            hideFn();
        }
    });
}

// ══════════════════════════════════════════
// RECHERCHE WEB — Bouton toggle 🌍
// ══════════════════════════════════════════

let _webSearchActive = false;

function _setWebSearch(active) {
    _webSearchActive = active;
    const btn = document.getElementById('search-web-btn');
    if (!btn) return;
    const prov = document.getElementById('provider-select')?.value || '';
    const isGemini  = prov === 'gemini';
    const isMistral = prov === 'mistral';
    if (active) {
        btn.classList.add('web-active');
        const lbl = isGemini  ? 'Google Search Grounding actif — désactiver'
                  : isMistral ? 'Recherche web Mistral natif active — désactiver'
                  : 'Recherche web Brave/Tavily active — désactiver';
        btn.setAttribute('aria-label', lbl);
        btn.title = isGemini  ? 'Google Search Grounding (Gemini natif)'
                  : isMistral ? 'Recherche Web (Mistral natif)'
                  : 'Recherche Web (Brave/Tavily)';
    } else {
        btn.classList.remove('web-active');
        btn.setAttribute('aria-label', 'Activer la recherche web');
        btn.title = isGemini  ? 'Google Search (Gemini natif)'
                  : isMistral ? 'Recherche Web (Mistral natif)'
                  : 'Recherche Web (Brave/Tavily)';
    }
}

document.getElementById('search-web-btn')?.addEventListener('click', () => {
    _setWebSearch(!_webSearchActive);
});

// SELECTEUR MODE AGENT
// ══════════════════════════════════════════

let _agentMode = '';

function _setAgentMode(mode, save) {
    if (save === undefined) save = true;
    var _prevMode = _agentMode;
    _agentMode = mode || '';
    document.querySelectorAll('.agent-mode-btn').forEach(function(btn) {
        var active = btn.dataset.mode === _agentMode;
        btn.classList.toggle('agent-mode-active', active);
        btn.setAttribute('aria-pressed', String(active));
    });
    // Option Document Vibe dans le menu + : visible uniquement en mode Vibe
    var _vdb = document.getElementById('plus-vibe-doc');
    if (_vdb) _vdb.hidden = (_agentMode !== 'vibe');

    if (_agentMode !== 'vibe' && _agentMode !== _prevMode) {
        // Réinitialiser la recherche web quand on quitte le mode Vibe
        _setWebSearch(false);
    }
    if (mode === 'coanimm') {
        var panel = document.getElementById('coanimm-panel');
        if (panel && panel.hidden) { var tb = document.getElementById('toggle-coanimm'); if (tb) tb.click(); }
    }
    if (save && currentThreadId) {
        fetch('/api/threads/' + currentThreadId + '/agent_mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: _agentMode})
        }).catch(function() {});
    }
}

async function _loadAgentMode(threadId) {
    try {
        var r = await fetch('/api/threads/' + threadId + '/agent_mode');
        var d = await r.json();
        _setAgentMode(d.agent_mode || '', false);
    } catch (e) { _setAgentMode('', false); }
    _refreshVibeButtonVisibility();
}

document.querySelectorAll('.agent-mode-btn').forEach(function(btn) {
    btn.addEventListener('click', function() { _setAgentMode(btn.dataset.mode); });
});

// Le bouton Vibe n'est visible que si une clé Mistral est enregistrée (Vibe = Mistral cloud européen).
let _providerActif = '';

// L'agent Vibe suppose que Mistral RÉPOND : le serveur refuse et retombe sur le
// chat normal si un autre modèle est actif. Le bouton ne dépendait que de la
// PRÉSENCE d'une clé Mistral — on pouvait donc choisir un mode qui n'allait pas
// s'appliquer, sans autre indice qu'un repli après coup. Il suit maintenant le
// modèle réellement actif.
async function _refreshVibeButtonVisibility(keys) {
    var btn = document.getElementById('agent-btn-vibe');
    if (!btn) return;
    try {
        if (!keys) keys = await fetch('/api/settings/api-keys').then(function(r) { return r.json(); });
        var aLaCle = !!(keys && keys.mistral);
        var sel = document.getElementById('provider-select');
        var actif = (sel && sel.value) || _providerActif || '';
        var mistralActif = String(actif).toLowerCase() === 'mistral';
        btn.hidden = !(aLaCle && mistralActif);
        btn.title = mistralActif ? 'Vibe — agent Mistral'
                                 : 'Vibe — nécessite que Mistral soit le modèle actif';
        // Si le mode était sélectionné et ne s'applique plus, on revient au standard.
        if (btn.hidden && btn.getAttribute('aria-pressed') === 'true') {
            _setAgentMode('');
            _srAnnounce("Mode Vibe désactivé : il nécessite Mistral comme modèle actif.");
        }
    } catch (e) { btn.hidden = true; }
}

function _splitSentences(text) {
    // 1. Convertir les \n littéraux en vrais sauts de ligne
    let t = text.replace(/\\n/g, '\n');

    // 2. Nettoyer
    t = t.replace(/<hr\s*\/?>/gi, '\n');
    t = t.replace(/<br\s*\/?>/gi, '\n');
    t = t.replace(/<li[^>]*>(.*?)<\/li>/gis, (_, c) => c.trim().replace(/[.,;:]*$/, '') + '.\n');
    t = t.replace(/<[^>]{1,80}>/g, ' ');
    t = t.replace(/^---+$/gm, '\n');
    t = t.replace(/^[•\-\*]\s+(.*)$/gm, (_, c) => c.trim().replace(/[.,;:]*$/, '') + '.');
    t = t.replace(/^\d+[\.\)]\s+(.*)$/gm, (_, c) => c.trim().replace(/[.,;:]*$/, '') + '.');
    t = t.replace(/\*+/g, '');
    t = t.replace(/#{1,6}\s/g, '');
    t = t.replace(/\s*—\s*/g, ', ');
    // Espace manquant après ponctuation
    t = t.replace(/([.!?])([A-ZÀ-Ÿa-zà-ÿ])/g, '$1 $2');

    // 3. Découper sur fins de phrases ET sauts de ligne
    const raw = t.split(/(?<=[.!?…])\s+|\n+/);

    // 4. Regrouper les fragments trop courts avec le suivant
    const parts = [];
    let buf = '';
    for (const chunk of raw) {
        const c = chunk.trim();
        if (!c) continue;
        buf = buf ? buf + ' ' + c : c;
        if (buf.length >= 20) { parts.push(buf); buf = ''; }
    }
    if (buf) parts.push(buf);

    return parts.filter(s => s.length > 1);
}

function _resolveVoice() {
    // Choix explicite de l'utilisateur -> comportement actuel (voix globale)
    const custom = localStorage.getItem('nimm-voice');
    if (custom) return custom;
    // Sinon : voix par defaut du masque du fil courant si le masque en declare une
    const tid = currentTabId || currentThreadId;
    if (tid) {
        const thread = threads.find(t => t.thread_id === tid);
        if (thread && thread.mask_id && thread.personality_mode === 'mask' && _maskVoice[thread.mask_id]) {
            return _maskVoice[thread.mask_id];
        }
    }
    return 'ff_siwis';
}

async function _fetchAudio(sentence) {
    const r = await fetch('/api/tts/speak', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ text: sentence, voice: _resolveVoice() })
    });
    if (!r.ok) return null;
    const blob = await r.blob();
    return URL.createObjectURL(blob);
}

async function playTTS(text, btn) {
    // Pause/resume sur le même bouton
    if (_currentTTSBtn === btn && btn._playing) {
        if (_currentAudio && !_currentAudio.paused) {
            _currentAudio.pause();
            btn.innerHTML = spk2;
            return;
        } else if (_currentAudio && _currentAudio.paused) {
            _currentAudio.play();
            btn.innerHTML = `<svg viewBox="0 0 16 18" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><line x1="3" y1="1" x2="3" y2="17"/><line x1="13" y1="1" x2="13" y2="17"/></svg>`;
            return;
        }
    }
    stopTTS();

    btn._playing   = true;
    _currentTTSBtn = btn;

    const sentences = _splitSentences(text);
    if (!sentences.length) { stopTTS(); return; }

    // Animation chargement
    const frames = [spk0, spk1, spk2, spk1];
    let fi = 0;
    _loaderInterval = setInterval(() => { btn.innerHTML = frames[fi++ % frames.length]; }, 300);

    try {
        for (let i = 0; i < sentences.length; i++) {
            if (!btn._playing) break;

            // Utiliser l'URL préchargée si disponible, sinon fetcher
            const cachedUrl  = sentences._preloaded?.[i];
            const urlCurrent = cachedUrl || await _fetchAudio(sentences[i]);
            if (sentences._preloaded) delete sentences._preloaded[i];
            if (!urlCurrent) continue;

            clearInterval(_loaderInterval);
            _loaderInterval = null;

            if (!btn._playing) { URL.revokeObjectURL(urlCurrent); break; }

            // Lancer le préchargement de la phrase suivante en parallèle
            const nextPromise = (i + 1 < sentences.length)
                ? _fetchAudio(sentences[i + 1])
                : Promise.resolve(null);

            await new Promise((resolve) => {
                const audio = new Audio(urlCurrent);
                _currentAudio = audio;
                audio.onplay  = () => { btn.innerHTML = SVG_PAUSE; };
                audio.onended = () => { URL.revokeObjectURL(urlCurrent); resolve(); };
                audio.onerror = () => { URL.revokeObjectURL(urlCurrent); resolve(); };
                audio.play();
            });

            // Stocker l'URL préchargée pour la prochaine itération
            await nextPromise.then(url => {
                if (url) {
                    sentences._preloaded = sentences._preloaded || {};
                    sentences._preloaded[i + 1] = url;
                }
            }).catch(() => {});
        }
    } catch(e) {
        console.error('[TTS]', e);
    }

    stopTTS();
}

function stopTTS() {
    clearInterval(_loaderInterval);
    _loaderInterval = null;
    // Vider la file et le cache de préchargement pour éviter tout encombrement
    _ttsQueue   = [];
    _ttsRunning = false;
    _ttsPreload.clear();
    if (_currentAudio) {
        _currentAudio.pause();
        _currentAudio = null;
    }
    if (_currentTTSBtn) {
        _currentTTSBtn.innerHTML = spk2;
        _currentTTSBtn._playing    = false;
        _currentTTSBtn = null;
    }
}

let _selectedVoice  = localStorage.getItem('nimm-voice') || 'ff_siwis';
let _autoTTS        = localStorage.getItem('nimm-autotts') === 'true';
let _currentUserId  = localStorage.getItem('nimm-user-id') || '';
let _unlockTokens   = {};   // userId -> jeton de session (memoire seule, non persiste)

// ── Intercepteur fetch — injecte X-User-ID (+ jeton de session) sur tous les appels /api ──
const _nimmOrigFetch = window.fetch.bind(window);
window.fetch = (url, opts = {}) => {
    if (typeof url === 'string' && url.startsWith('/api') && _currentUserId) {
        const _h = { 'X-User-ID': _currentUserId, ...(opts.headers || {}) };
        if (_unlockTokens[_currentUserId]) _h['X-Unlock-Token'] = _unlockTokens[_currentUserId];
        opts = { ...opts, headers: _h };
    }
    return _nimmOrigFetch(url, opts);
};

// ── Modale PIN — pavé numérique thémé (remplace window.prompt) ──
const _pinModal = {
    el: null, dotsEl: null, errEl: null, titleEl: null, subEl: null, keypadEl: null, cancelBtn: null, inputEl: null,
    buffer: '',
    onSubmit: null,
    onCancel: null,
    _keyHandler: null,

    _build() {
        this.el        = document.getElementById('pin-modal');
        this.dotsEl    = document.getElementById('pin-modal-dots');
        this.statusEl  = document.getElementById('pin-modal-status');
        this.errEl     = document.getElementById('pin-modal-error');
        this.titleEl   = document.getElementById('pin-modal-title');
        this.subEl     = document.getElementById('pin-modal-subtitle');
        this.keypadEl  = document.getElementById('pin-modal-keypad');
        this.cancelBtn = document.getElementById('pin-modal-cancel');
        this.inputEl = document.getElementById('pin-modal-input');
        this.keypadEl.querySelectorAll('.pin-key').forEach(btn => {
            btn.addEventListener('click', () => this._press(btn.dataset.key));
        });
        this.cancelBtn.addEventListener('click', () => this._cancel());
        this.inputEl.addEventListener('input', () => {
            // Garder uniquement les chiffres
            const digits = this.inputEl.value.replace(/\D/g, '');
            this.inputEl.value = digits;
            this.buffer = digits;
            this._render();
        });
        this._keyHandler = (e) => {
            const inInput = document.activeElement === this.inputEl;
            if (inInput) {
                if (e.key === 'Enter')  { this._press('ok'); e.preventDefault(); }
                else if (e.key === 'Escape') { this._cancel(); e.preventDefault(); }
                else if (e.key === 'Tab')    { this._trapTab(e); }
                return;
            }
            if (e.key >= '0' && e.key <= '9') { this._press(e.key); e.preventDefault(); }
            else if (e.key === 'Backspace')   { this._press('back'); e.preventDefault(); }
            else if (e.key === 'Enter')       { this._press('ok'); e.preventDefault(); }
            else if (e.key === 'Escape')      { this._cancel(); e.preventDefault(); }
            else if (e.key === 'Tab')         { this._trapTab(e); }
        };
    },

    _focusableEls() {
        return Array.from(this.el.querySelectorAll('button, input')).filter(b => !b.disabled && b.type !== 'hidden');
    },

    _trapTab(e) {
        const els = this._focusableEls();
        if (!els.length) return;
        const first = els[0], last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
        else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
    },

    // onSubmit(pin) doit retourner true (succes, ferme la modale) ou une chaine/false (erreur, reste ouverte)
    open({ title, subtitle, onSubmit, onCancel }) {
        if (!this.el) this._build();
        this.buffer = '';
        this.onSubmit = onSubmit || null;
        this.onCancel = onCancel || null;
        this.titleEl.textContent = title || '🔒 Code PIN';
        this.subEl.textContent = subtitle || '';
        this.errEl.textContent = '';
        this._render();
        this.el.classList.remove('hidden');
        document.addEventListener('keydown', this._keyHandler);
        this._lastFocused = document.activeElement;
        if (this.inputEl) this.inputEl.value = '';
        setTimeout(() => { if (this.inputEl) this.inputEl.focus(); }, 60);
    },

    close() {
        if (this.el) this.el.classList.add('hidden');
        document.removeEventListener('keydown', this._keyHandler);
        this.buffer = '';
        if (this.inputEl) this.inputEl.value = '';
        if (this._lastFocused && typeof this._lastFocused.focus === 'function') {
            this._lastFocused.focus();
        }
        this._lastFocused = null;
    },

    _cancel() {
        const cb = this.onCancel;
        this.close();
        if (cb) cb();
    },

    async _press(key) {
        if (key === 'back') { this.buffer = this.buffer.slice(0, -1); this._render(); if (this.inputEl) this.inputEl.value = this.buffer; return; }
        if (key === 'ok')   { await this._submit(); return; }
        this.buffer += key;
        this._render();
        if (this.inputEl) this.inputEl.value = this.buffer;
    },

    _render() {
        this.dotsEl.innerHTML = '';
        const len = Math.max(this.buffer.length, 1);
        for (let i = 0; i < len; i++) {
            const d = document.createElement('span');
            d.className = 'pin-dot' + (i < this.buffer.length ? ' filled' : '');
            this.dotsEl.appendChild(d);
        }
        const n = this.buffer.length;
        this.statusEl.textContent = n
            ? n + ' chiffre' + (n > 1 ? 's' : '') + ' saisi' + (n > 1 ? 's' : '')
            : 'Aucun chiffre saisi';
    },

    async _submit() {
        if (!this.onSubmit) { this.close(); return; }
        this.errEl.textContent = '';
        const result = await this.onSubmit(this.buffer);
        if (result === true) {
            this.close();
        } else {
            this.errEl.textContent = (typeof result === 'string' && result) ? result : 'PIN incorrect.';
            this.buffer = '';
            if (this.inputEl) this.inputEl.value = '';
            this._render();
            if (this.inputEl) setTimeout(() => this.inputEl.focus(), 60);
            const box = this.el.querySelector('.pin-modal-box');
            box.classList.remove('pin-shake');
            void box.offsetWidth;
            box.classList.add('pin-shake');
        }
    }
};

// ── Verrou de session : deverrouille un profil a PIN avant d'ecrire (anti-pollution memoire) ──
async function _ensureUnlocked(userId) {
    if (!userId || _unlockTokens[userId]) return true;
    let hasPin = false;
    try {
        const users = await fetch('/api/users').then(r => r.json());
        const u = (users || []).find(x => x.id === userId);
        hasPin = !!(u && u.has_pin);
    } catch (e) { hasPin = false; }
    if (!hasPin) return true;
    return new Promise((resolve) => {
        _pinModal.open({
            title: '🔒 Déverrouiller',
            subtitle: 'Code PIN pour « ' + userId + ' »',
            onCancel: () => resolve(false),
            onSubmit: async (pin) => {
                if (!pin) return 'Code requis.';
                try {
                    const r = await fetch('/api/users/' + encodeURIComponent(userId) + '/unlock', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pin })
                    });
                    if (!r.ok) return 'PIN incorrect.';
                    _unlockTokens[userId] = (await r.json()).token;
                    resolve(true);
                    return true;
                } catch (e) {
                    return 'Deverrouillage impossible.';
                }
            }
        });
    });
}

// Cache masques : id → label (ex: "Glaude 🐺") + voix par defaut (par masque)
let _maskCache = {};
let _maskVoice = {};
(async function _loadMaskCache() {
    try {
        const masks = await fetch('/api/masks').then(r => r.json());
        masks.forEach(m => {
            _maskCache[m.id] = m.label;
            if (m.voice) _maskVoice[m.id] = m.voice;
        });
    } catch(e) {}
})();
let _ttsQueue       = [];
let _ttsRunning     = false;
let _ttsStreamBuf   = '';
const _ttsPreload   = new Map();   // prechargement global -- partage entre push et flush

async function _ttsFlush() {
    if (_ttsRunning) return;
    _ttsRunning = true;

    while (_ttsQueue.length > 0) {
        if (!_autoTTS) break;

        const { sentence, btn } = _ttsQueue.shift();

        try {
            // Fetch courant : déjà lancé par _ttsPush ou à démarrer maintenant
            const urlPromise = _ttsPreload.get(sentence) || _fetchAudio(sentence);
            _ttsPreload.delete(sentence);

            // Précharger les 3 suivantes pendant qu'on attend l'audio courant
            _ttsQueue.slice(0, 3).forEach(({ sentence: s }) => {
                if (!_ttsPreload.has(s)) _ttsPreload.set(s, _fetchAudio(s));
            });

            const url = await urlPromise;
            if (!url) continue;

            _currentTTSBtn = btn;
            btn._playing   = true;

            await new Promise(resolve => {
                const audio = new Audio(url);
                _currentAudio = audio;
                audio.onplay = () => {
                    btn.innerHTML = SVG_PAUSE;
                    // Continuer le préchargement pendant la lecture
                    _ttsQueue.slice(0, 3).forEach(({ sentence: s }) => {
                        if (!_ttsPreload.has(s)) _ttsPreload.set(s, _fetchAudio(s));
                    });
                };
                audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
                audio.onerror = () => { URL.revokeObjectURL(url); resolve(); };
                audio.play();
            });

        } catch(e) {
            console.error('[TTS stream]', e);
        }
    }

    _ttsRunning   = false;
    _currentAudio = null;
    if (_currentTTSBtn) {
        _currentTTSBtn.innerHTML = spk2;
        _currentTTSBtn._playing  = false;
    }
    _currentTTSBtn = null;
}

function _ttsPush(sentence, btn) {
    if (!sentence.trim()) return;
    // Démarrer le fetch immédiatement — avant même que le flush soit prêt
    if (!_ttsPreload.has(sentence)) _ttsPreload.set(sentence, _fetchAudio(sentence));
    _ttsQueue.push({ sentence, btn });
    _ttsFlush();
}

// ══════════════════════════════════════════
// ÉTAT GLOBAL
// ══════════════════════════════════════════

let threads        = [];
let tabs           = [];
let currentThreadId = null;
let currentTabId    = null;
const _threadCostMap = new Map(); // Coût cumulé par fil (euros)

// ── Émojis expressifs par dominante ──
const EMOJI_MOODS = {
    joie:         ['😄', '😁'],
    confiance:    ['🙂', '😌'],
    anticipation: ['😊', '🤔'],
    tristesse:    ['😔', '😢'],
    peur:         ['😟', '😰'],
    colere:       ['😠', '😤'],
    degout:       ['😒', '😑'],
    surprise:     ['😮', '😲'],
    reflexion:    ['🤔', '💭'],
    neutre:       ['🙂', '😊'],
};

let _blinkInterval = null;
let _blinkEmojiEl  = null;
let _blinkSchedule = null;

const EMOJI_MAP = {
    joie:         ['🙂', '😊'],
    confiance:    ['😗', '😙'],
    anticipation: ['🤨', '😑'],
    tristesse:    ['😢', '😔'],
    peur:         ['😨', '😩'],
    colere:       ['😠', '😤'],
    degout:       ['🥴', '🤮'],
    surprise:     ['😮', '😮‍💨'],
    reflexion:    ['🙄', '😣'],
    neutre:       ['🙂', '😊'],
    transition:   ['🙂‍↕️', '😑'],
};

function startBlink(dominant, score = 5) {
    stopBlink();
    const emojis = messagesDiv.querySelectorAll('.message.assistant .bubble-emoji');
    if (!emojis.length) return;
    _blinkEmojiEl = emojis[emojis.length - 1];

    const span = _blinkEmojiEl.querySelector('.emoji-char');
    // Score ≥ 7 → paire expressive (EMOJI_MOODS) · sinon paire calme (EMOJI_MAP)
    const pair = score >= 7
        ? (EMOJI_MOODS[dominant] || EMOJI_MOODS['neutre'])
        : (EMOJI_MAP[dominant]   || EMOJI_MAP['neutre']);
    if (span) {
        span.textContent = pair[0];
        span.dataset.dominant  = dominant;
        span.dataset.moodScore = score;
    }

    function doBlink() {
        const el = _blinkEmojiEl?.querySelector('.emoji-char');
        if (!el) return;
        const s = parseInt(el.dataset.moodScore || '5');
        const p = s >= 7
            ? (EMOJI_MOODS[el.dataset.dominant] || EMOJI_MOODS['neutre'])
            : (EMOJI_MAP[el.dataset.dominant]   || EMOJI_MAP['neutre']);
        el.textContent = p[1];
        setTimeout(() => { if (el) el.textContent = p[0]; }, 300);
        const next = 3000 + Math.random() * 2000;
        _blinkInterval = setTimeout(doBlink, next);
    }

    const first = 3000 + Math.random() * 2000;
    _blinkInterval = setTimeout(doBlink, first);
}

function stopBlink() {
    if (_blinkInterval) { clearTimeout(_blinkInterval); _blinkInterval = null; }
    _blinkEmojiEl = null;
}

// ══════════════════════════════════════════
// DOM
// ══════════════════════════════════════════

const messagesDiv  = document.getElementById('messages');
const userInput    = document.getElementById('user-input');

// Flag : l'utilisateur a scrollé manuellement vers le haut
let _userScrolledUp = false;

// Scramble — effet bruit visuel pendant la génération
let _scrambleInterval = null;
const _SCRAMBLE_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789█▓▒░@#$%';
function _startScramble(noiseSpan) {
    if (_scrambleInterval) clearInterval(_scrambleInterval);
    _scrambleInterval = setInterval(() => {
        const len = 3 + Math.floor(Math.random() * 2);
        noiseSpan.textContent = Array.from({length: len}, () =>
            _SCRAMBLE_CHARS[Math.floor(Math.random() * _SCRAMBLE_CHARS.length)]
        ).join('');
    }, 60);
}
function _stopScramble() {
    if (_scrambleInterval) { clearInterval(_scrambleInterval); _scrambleInterval = null; }
}
let _lastUserScrollTime = 0;
messagesDiv.addEventListener('wheel', () => {
    _userScrolledUp = true;
    _lastUserScrollTime = Date.now();
});
messagesDiv.addEventListener('touchstart', () => {
    _userScrolledUp = true;
    _lastUserScrollTime = Date.now();
}, { passive: true });
messagesDiv.addEventListener('touchmove', () => {
    const distBottom = messagesDiv.scrollHeight - messagesDiv.clientHeight - messagesDiv.scrollTop;
    _userScrolledUp = distBottom > 80;
    if (_userScrolledUp) _lastUserScrollTime = Date.now();
}, { passive: true });
messagesDiv.addEventListener('scroll', () => {
    const distBottom = messagesDiv.scrollHeight - messagesDiv.clientHeight - messagesDiv.scrollTop;
    if (distBottom < 20 && Date.now() - _lastUserScrollTime > 500) _userScrolledUp = false;
});
const sendBtn      = document.getElementById('send-btn');
const micBtn       = document.getElementById('mic-btn');
const threadList   = document.getElementById('thread-list');
const tabsBar      = document.getElementById('tabs-bar');
const historyPanel = document.getElementById('history-panel');

// ══════════════════════════════════════════
// SÉLECTION TEXTE → CITER
// ══════════════════════════════════════════
function setupQuote() {
    const tooltip = document.createElement('div');
    tooltip.id = 'quote-tooltip';
    tooltip.style.display = 'none';
    tooltip.innerHTML = `
        <button id="quote-cite-btn" aria-label="Citer ce texte">❝ Citer</button>
        <button id="quote-copy-btn" aria-label="Copier ce texte">📋 Copier</button>
        <button id="quote-tts-btn" aria-label="Lire à partir d'ici">🔊 Lire ici</button>
    `;
    document.body.appendChild(tooltip);

    function _getSelectionText() {
        return window.getSelection()?.toString().trim() || '';
    }

    function _showTooltip() {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed || sel.toString().trim().length < 2) {
            tooltip.style.display = 'none';
            return;
        }
        const node = sel.anchorNode?.parentElement;
        if (!node?.closest('.message.assistant .message-bubble')) {
            tooltip.style.display = 'none';
            return;
        }
        const range = sel.getRangeAt(0).getBoundingClientRect();
        tooltip.style.display = 'flex';
        tooltip.style.top  = (window.scrollY + range.top - 42) + 'px';
        tooltip.style.left = (window.scrollX + range.left + range.width / 2 - tooltip.offsetWidth / 2) + 'px';
    }

    document.addEventListener('mouseup', _showTooltip);
    document.addEventListener('touchend', _showTooltip);

    document.getElementById('quote-cite-btn').addEventListener('mousedown', (e) => {
        e.preventDefault();
        const text = _getSelectionText();
        if (!text) return;
        const input = document.getElementById('user-input');
        const current = input.value.trim();
        input.value = (current ? current + '\n' : '') + '[Tu as dit : « ' + text + ' »]\n';
        input.dispatchEvent(new Event('input'));
        input.focus();
        tooltip.style.display = 'none';
        window.getSelection()?.removeAllRanges();
    });

    document.getElementById('quote-copy-btn').addEventListener('mousedown', (e) => {
        e.preventDefault();
        const text = _getSelectionText();
        if (!text) return;
        _copyToClipboard(text).then(() => {
            const btn = document.getElementById('quote-copy-btn');
            btn.textContent = '✓';
            setTimeout(() => { btn.textContent = '📋 Copier'; }, 1200);
        });
        tooltip.style.display = 'none';
        window.getSelection()?.removeAllRanges();
    });

    document.getElementById('quote-tts-btn').addEventListener('mousedown', (e) => {
        e.preventDefault();
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed) return;
        // Trouver la bulle message contenant la sélection
        const bubble = sel.anchorNode?.parentElement?.closest('.message.assistant .message-bubble');
        if (!bubble) return;
        const fullText = bubble.innerText || bubble.textContent || '';
        const selectedText = sel.toString().trim();
        // Localiser le début de la sélection dans le texte complet
        const idx = fullText.indexOf(selectedText);
        const textFromHere = idx >= 0 ? fullText.slice(idx) : selectedText;
        tooltip.style.display = 'none';
        window.getSelection()?.removeAllRanges();
        // Bouton de référence : le ttsBtn de la bulle, ou un bouton fantôme
        const refBtn = bubble.closest('.message')?.querySelector('.msg-tts-btn') || document.createElement('button');
        playTTS(textFromHere, refBtn);
    });

    document.addEventListener('mousedown', (e) => {
        if (!tooltip.contains(e.target)) tooltip.style.display = 'none';
    });
}

// ══════════════════════════════════════════
// SÉLECTION UTILISATEUR
// ══════════════════════════════════════════

async function showUserPicker(switchMode = false) {
    const picker = document.getElementById('user-picker');
    if (!picker) return;
    const grid  = document.getElementById('user-picker-grid');
    const title = document.getElementById('user-picker-title');
    if (title) title.textContent = switchMode ? 'Changer de profil' : 'Qui est là ?';
    grid.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px">Chargement…</div>';
    picker.classList.remove('hidden');

    const users = await fetch('/api/users').then(r => r.json()).catch(() => []);
    if (!users.length) {
        // Aucun utilisateur — fermer le picker et laisser l'onboarding NIMM prendre le relais
        picker.classList.add('hidden');
        return;
    }

    grid.innerHTML = '';
    users.forEach(u => {
        const btn = document.createElement('button');
        btn.className = 'user-card';
        btn.innerHTML = `<span class="user-card-emoji">${u.emoji || '👤'}</span><span class="user-card-name">${u.name}</span>`;
        btn.addEventListener('click', () => _selectUser(u, switchMode));
        grid.appendChild(btn);
    });
}

async function _selectUser(user, switchMode = false) {
    _unlockTokens = {};   // changer de session re-verrouille les profils a PIN
    _currentUserId = user.id;
    localStorage.setItem('nimm-user-id',    user.id);
    localStorage.setItem('nimm-user-name',  user.name);
    localStorage.setItem('nimm-user-emoji', user.emoji || '👤');
    // Si cet utilisateur n'est pas encore admin et qu'il est le seul → le passer admin
    if (!user.admin) {
        const allUsers = await fetch('/api/users').then(r => r.json()).catch(() => []);
        if (allUsers.length === 1) {
            await fetch(`/api/users/${user.id}`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ admin: true })
            }).catch(() => {});
        }
    }
    const picker = document.getElementById('user-picker');
    if (picker) picker.classList.add('hidden');
    if (switchMode) {
        // Rechargement complet pour changer de contexte
        window.location.reload();
        return;
    }
    await init();
}

// ── Tuile admin : verrou PIN + identité Tailscale par profil ──
async function _setUserPin(userId, hasPin) {
    let currentPin = '';
    if (hasPin) {
        currentPin = await new Promise(resolve => {
            _pinModal.open({
                title: '🔒 Code PIN actuel',
                subtitle: 'Entrez votre code PIN actuel pour continuer',
                onSubmit: async (pin) => { resolve(pin); return true; },
                onCancel: () => resolve(null),
            });
        });
        if (currentPin === null) return;
    }
    const newPin = await new Promise(resolve => {
        _pinModal.open({
            title: hasPin ? '🔒 Nouveau code PIN' : '🔒 Définir un code PIN',
            subtitle: hasPin ? 'Laissez vide et validez ✓ pour supprimer le PIN' : '',
            onSubmit: async (pin) => { resolve(pin); return true; },
            onCancel: () => resolve(null),
        });
    });
    if (newPin === null) return;
    try {
        const r = await fetch('/api/users/' + encodeURIComponent(userId) + '/set-pin', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin: newPin, current_pin: currentPin })
        });
        if (!r.ok) { _nimm_toast && _nimm_toast('Code PIN actuel incorrect.', 'error'); return; }
        _nimm_toast && _nimm_toast(newPin ? 'Code PIN défini.' : 'Code PIN supprimé.', 'ok');
        _loadUsersTab();
    } catch (e) { _nimm_toast && _nimm_toast('Opération impossible.', 'error'); }
}

async function _removeUserPin(userId) {
    const currentPin = await new Promise(resolve => {
        _pinModal.open({
            title: '🔓 Supprimer le code PIN',
            subtitle: 'Entrez votre PIN actuel pour confirmer la suppression',
            onSubmit: async (pin) => { resolve(pin); return true; },
            onCancel: () => resolve(null),
        });
    });
    if (currentPin === null) return;
    try {
        const r = await fetch('/api/users/' + encodeURIComponent(userId) + '/set-pin', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin: '', current_pin: currentPin })
        });
        if (!r.ok) { _nimm_toast && _nimm_toast('PIN actuel incorrect — suppression annulée.', 'error'); return; }
        _nimm_toast && _nimm_toast('Code PIN supprimé.', 'ok');
        _loadUsersTab();
    } catch (e) { _nimm_toast && _nimm_toast('Opération impossible.', 'error'); }
}

async function _setUserTs(userId) {
    const v = window.prompt('Identité Tailscale à lier à « ' + userId + ' » (ex : prenom@gmail.com ; vide = délier) :');
    if (v === null) return;
    try {
        const r = await fetch('/api/users/' + encodeURIComponent(userId) + '/ts-login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ts_login: v })
        });
        if (!r.ok) { window.alert('Échec.'); return; }
        window.alert(v ? 'Identité Tailscale liée.' : 'Identité Tailscale déliée.');
        _loadUsersTab();
    } catch (e) { window.alert('Opération impossible.'); }
}

async function _loadUsersTab() {
    const wrap = document.getElementById('users-tab-content');
    if (!wrap) return;
    wrap.innerHTML = '<div style="color:var(--text-muted);font-size:0.85rem">Chargement…</div>';

    const [users, serverMode, globalKeys, extKeys] = await Promise.all([
        fetch('/api/users').then(r => r.json()).catch(() => []),
        fetch('/api/settings/server-mode').then(r => r.json()).catch(() => ({ enabled: false })),
        fetch('/api/settings/global-keys').then(r => r.json()).catch(() => ({})),
        fetch('/api/settings/ext-keys').then(r => r.json()).catch(() => ({services:[]})),
    ]);

    const me = users.find(u => u.id === _currentUserId) || { id: _currentUserId, name: _currentUserId, admin: false };
const isAdmin = me.admin;

    let html = `
    <div class="settings-section">
        <h4>👤 Profil actif</h4>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <span style="font-size:2rem">${me.emoji || '👤'}</span>
            <span style="font-weight:600">${me.name}</span>
        </div>
        <button onclick="showUserPicker(true)" style="padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:var(--bg-input);cursor:pointer;font-size:0.85rem">🔄 Changer de profil</button>
        <button onclick="_showNewProfileForm()" style="margin-left:8px;padding:6px 14px;border-radius:8px;border:none;background:var(--accent);color:#000;cursor:pointer;font-size:0.85rem;font-weight:600">+ Nouveau profil</button>
    </div>
    <div id="new-profile-form" style="display:none;margin-top:12px;display:flex;flex-direction:none;gap:8px;align-items:center;flex-wrap:wrap">
        <input id="new-profile-name" type="text" placeholder="Prénom" maxlength="32"
            style="flex:1;padding:7px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-input);color:var(--text);font-size:0.9rem">
        <input id="new-profile-emoji" type="text" placeholder="🙂" maxlength="2"
            style="width:48px;text-align:center;padding:7px;border:1px solid var(--border);border-radius:8px;background:var(--bg-input);color:var(--text);font-size:1.1rem">
        <button onclick="_createNewProfile()" style="padding:7px 14px;border-radius:8px;background:var(--accent);color:#000;border:none;cursor:pointer;font-size:0.85rem;font-weight:600">Créer →</button>
    </div>`;

    if (isAdmin) {
        html += `
    <div class="settings-section">
        <h4>👥 Gérer les profils</h4>
        <div id="users-list-inner" style="display:flex;flex-direction:column;gap:8px;margin-bottom:12px">`;
        users.forEach(u => {
            html += `<div style="display:flex;align-items:center;gap:8px;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--bg-input);flex-wrap:wrap">
                <span style="font-size:1.4rem">${u.emoji || '👤'}</span>
                <span style="flex:1;font-weight:${u.id === _currentUserId ? '700' : '400'}">${u.name}${u.id === _currentUserId ? ' (moi)' : ''}${u.ts_login ? ' 🔗' : ''}</span>
                <button onclick="_setUserPin('${u.id}', ${u.has_pin ? 'true' : 'false'})" aria-label="${u.has_pin ? 'Modifier le code PIN de ' + u.name : 'Définir un code PIN pour ' + u.name}" style="padding:3px 10px;border:1px solid var(--border);background:var(--bg-input);color:var(--text);border-radius:6px;cursor:pointer;font-size:0.8rem">${u.has_pin ? '🔒 Modifier PIN' : '🔓 Définir PIN'}</button>
                ${u.has_pin ? `<button onclick="_removeUserPin('${u.id}')" aria-label="Supprimer le code PIN de ${u.name}" style="padding:3px 10px;border:1px solid #d05050;background:transparent;color:#d05050;border-radius:6px;cursor:pointer;font-size:0.8rem">🔓 Supprimer PIN</button>` : ''}
                <button onclick="_setUserTs('${u.id}')" aria-label="Lier une identite Tailscale a ${u.name}" style="padding:3px 10px;border:1px solid var(--border);background:var(--bg-input);color:var(--text);border-radius:6px;cursor:pointer;font-size:0.8rem">🔗 Tailscale</button>
                ${u.id !== _currentUserId ? `<button onclick="_deleteUser('${u.id}')" aria-label="Supprimer le profil ${u.name}" style="padding:3px 10px;border:none;background:#e55;color:#fff;border-radius:6px;cursor:pointer;font-size:0.8rem">✕</button>` : ''}
            </div>`;
        });
        html += `</div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input id="new-user-name" type="text" placeholder="Prénom" style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg-input);color:var(--text);font-size:0.85rem">
            <input id="new-user-emoji" type="text" placeholder="🙂" maxlength="2" style="width:48px;text-align:center;padding:6px;border:1px solid var(--border);border-radius:8px;background:var(--bg-input);color:var(--text);font-size:1.1rem">
            <button onclick="_addUser()" style="padding:6px 14px;border-radius:8px;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:0.85rem">+ Ajouter</button>
        </div>
    </div>
    <div class="settings-section">
        <h4>🔑 Clés API globales (serveur)</h4>
        <p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:10px">Utilisées par tous les profils sans clé personnelle.</p>
        <div class="api-keys-grid">`;
        _svcIds().forEach(p => {
            const label = p.replace('_',' ');
            const id    = `global-key-${p.replace('_','-')}`;
            const ph    = globalKeys[p] ? '✅ Configurée' : '❌ Non configurée';
            html += `<label for="${id}">${label.charAt(0).toUpperCase()+label.slice(1)}</label>
            <input type="password" id="${id}" placeholder="${ph}" data-global-provider="${p}">`;
        });
        html += `</div>
        <button onclick="_saveGlobalKeys()" style="margin-top:10px;padding:6px 14px;border-radius:8px;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:0.85rem">💾 Sauvegarder clés globales</button>
    </div>

    <div class="settings-section" id="mistral-agents-section">
        <h4>🤖 Agents Mistral (Vibe)</h4>
        <p style="font-size:0.8rem;color:var(--text-muted);margin:0 0 10px">
            Créez et gérez des agents Mistral avec outils (recherche web, code, images, documents).
            Accessibles depuis CoaNIMM avec <code>nimm_mistral_agent()</code>.
        </p>
        <div id="mistral-agents-list" style="margin-bottom:12px">Chargement…</div>
        <details style="border:1px solid var(--border);border-radius:8px;padding:8px 12px">
            <summary style="cursor:pointer;font-size:0.85rem;font-weight:600">➕ Créer un agent</summary>
            <div style="margin-top:10px;display:flex;flex-direction:column;gap:8px">
                <div style="display:flex;gap:8px;align-items:center">
                    <label for="mag-name" style="font-size:0.82rem;white-space:nowrap;min-width:90px">Nom :</label>
                    <input id="mag-name" type="text" placeholder="Mon agent" maxlength="60"
                        style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem" />
                </div>
                <div style="display:flex;gap:8px;align-items:flex-start">
                    <label for="mag-desc" style="font-size:0.82rem;white-space:nowrap;min-width:90px;margin-top:4px">Description :</label>
                    <textarea id="mag-desc" rows="2" placeholder="Rôle de l'agent…"
                        style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem;resize:vertical"></textarea>
                </div>
                <div style="display:flex;gap:8px;align-items:flex-start">
                    <label for="mag-instructions" style="font-size:0.82rem;white-space:nowrap;min-width:90px;margin-top:4px">Instructions :</label>
                    <textarea id="mag-instructions" rows="4" placeholder="System prompt de l'agent…"
                        style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem;resize:vertical"></textarea>
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                    <label for="mag-model" style="font-size:0.82rem;white-space:nowrap;min-width:90px">Modèle :</label>
                    <select id="mag-model" style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem">
                        <option value="mistral-medium-latest">Mistral Medium (recommandé)</option>
                        <option value="mistral-small-latest">Mistral Small (rapide)</option>
                        <option value="mistral-large-latest">Mistral Large (puissant)</option>
                    </select>
                </div>
                <div style="font-size:0.82rem;font-weight:600;margin-top:4px">Outils :</div>
                <div style="display:flex;flex-wrap:wrap;gap:8px">
                    <label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer">
                        <input type="checkbox" value="web_search" class="mag-tool-chk" /> Recherche web
                    </label>
                    <label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer">
                        <input type="checkbox" value="code_interpreter" class="mag-tool-chk" /> Interpréteur de code
                    </label>
                    <label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer">
                        <input type="checkbox" value="image_generation" class="mag-tool-chk" /> Génération d'images
                    </label>
                    <label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer">
                        <input type="checkbox" value="document_library" class="mag-tool-chk" /> Bibliothèque de documents
                    </label>
                </div>
                <button onclick="_magCreate()" style="padding:6px 14px;border-radius:8px;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:0.82rem;margin-top:4px"
                    aria-label="Créer l'agent Mistral">
                    🤖 Créer l'agent
                </button>
                <div id="mag-status" style="font-size:0.8rem;color:var(--text-muted)"></div>
            </div>
        </details>
    </div>
    <div class="settings-section" id="ext-keys-section">
        <h4>🔑 Services externes</h4>
        <p style="font-size:0.8rem;color:var(--text-muted);margin:0 0 10px">
            Clés API pour les services tiers utilisés par CoaNIMM. Stockées chiffrées localement.
        </p>
        <div id="ext-keys-list">Chargement…</div>
    </div>

    <div class="settings-section" id="voice-banking-section">
        <h4>🎙️ Ma voix (Voxtral TTS)</h4>
        <p style="font-size:0.8rem;color:var(--text-muted);margin:0 0 10px">
            Clonez votre voix à partir d'un court enregistrement (5–30 sec).
            Utilise l'API Mistral (clé requise). Votre audio est envoyé à Mistral pour créer un profil vocal réutilisable.
        </p>
        <div id="voice-profiles-list" style="margin-bottom:12px">Chargement…</div>
        <details style="border:1px solid var(--border);border-radius:8px;padding:8px 12px">
            <summary style="cursor:pointer;font-size:0.85rem;font-weight:600">➕ Créer une nouvelle voix</summary>
            <div style="margin-top:10px;display:flex;flex-direction:column;gap:8px">
                <div style="display:flex;gap:8px;align-items:center">
                    <label for="vb-name" style="font-size:0.82rem;white-space:nowrap">Nom :</label>
                    <input id="vb-name" type="text" placeholder="Ma voix" maxlength="50"
                        style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem" />
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                    <label for="vb-lang" style="font-size:0.82rem;white-space:nowrap">Langue :</label>
                    <select id="vb-lang" style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem">
                        <option value="fr">Français</option>
                        <option value="en">Anglais</option>
                        <option value="es">Espagnol</option>
                        <option value="de">Allemand</option>
                        <option value="it">Italien</option>
                        <option value="pt">Portugais</option>
                        <option value="ar">Arabe</option>
                        <option value="hi">Hindi</option>
                        <option value="nl">Néerlandais</option>
                    </select>
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                    <label for="vb-gender" style="font-size:0.82rem;white-space:nowrap">Genre :</label>
                    <select id="vb-gender" style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem">
                        <option value="">Non précisé</option>
                        <option value="female">Féminin</option>
                        <option value="male">Masculin</option>
                    </select>
                </div>
                <div style="font-size:0.82rem;font-weight:600;margin-top:4px">Source audio :</div>
                <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                    <select id="vb-mic-select" aria-label="Choisir le microphone"
                        style="flex:1;min-width:140px;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.82rem"
                        onchange="_vbUpdateMicList()">
                        <option value="">Micro par défaut</option>
                    </select>
                    <button id="vb-rec-btn" onclick="_vbToggleRecord()"
                        style="padding:6px 12px;border-radius:8px;background:var(--danger,#e53935);color:#fff;border:none;cursor:pointer;font-size:0.82rem"
                        aria-label="Démarrer l'enregistrement">
                        🎙️ Enregistrer
                    </button>
                    <span id="vb-rec-timer" style="font-size:0.82rem;color:var(--text-muted)"></span>
                    <span style="font-size:0.8rem;color:var(--text-muted)">— ou —</span>
                    <label style="font-size:0.82rem;cursor:pointer;padding:6px 12px;border-radius:8px;border:1px solid var(--border);background:var(--bg-secondary)">
                        📁 Importer un fichier audio
                        <input id="vb-file-input" type="file" accept="audio/*" style="display:none" onchange="_vbFileSelected(this)" />
                    </label>
                </div>
                <div id="vb-audio-preview" style="display:none;margin-top:4px">
                    <audio id="vb-preview-player" controls style="width:100%;height:32px" aria-label="Aperçu de la voix"></audio>
                </div>
                <button id="vb-create-btn" onclick="_vbCreateVoice()" disabled
                    style="padding:6px 14px;border-radius:8px;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:0.82rem;margin-top:4px;opacity:0.5"
                    aria-label="Créer le profil de voix">
                    ✨ Créer le profil Voxtral
                </button>
                <div id="vb-status" style="font-size:0.8rem;color:var(--text-muted)"></div>
            </div>
        </details>
        <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <label style="font-size:0.82rem;cursor:pointer;padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary)">
                📥 Importer .nimmvoice
                <input type="file" accept=".nimmvoice,.zip" style="display:none" onchange="_vbImportProfile(this)" />
            </label>
            <label style="font-size:0.82rem;display:flex;align-items:center;gap:6px;cursor:pointer">
                <input type="checkbox" id="vb-import-recreate" />
                Recréer la voix chez Mistral (autre clé API)
            </label>
        </div>
    </div>
    <div class="settings-section">
        <h4>🖥️ Mode serveur</h4>
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.9rem">
            <input type="checkbox" id="server-mode-chk" ${serverMode.enabled ? 'checked' : ''}> Désarmer le watchdog (serveur 24/7)
        </label>
    </div>`;
    }

    wrap.innerHTML = html;
    // ── Agents Mistral ──
    (async () => {
        const magEl = document.getElementById('mistral-agents-list');
        if (!magEl) return;
        try {
            const r = await fetch('/api/mistral-agents/list');
            const {agents} = await r.json();
            if (!agents || !agents.length) {
                magEl.innerHTML = '<em style="font-size:0.8rem">Aucun agent configuré.</em>';
                return;
            }
            const _toolLabel = t => ({'web_search':'🔍 web','code_interpreter':'💻 code','image_generation':'🎨 images','document_library':'📚 docs'})[t] || t;
            let h = '<div style="display:flex;flex-direction:column;gap:8px">';
            for (const ag of agents) {
                const tools = (ag.tools || []).map(_toolLabel).join(', ') || 'aucun outil';
                h += `<details style="border:1px solid var(--border);border-radius:8px;padding:8px 12px">
                    <summary style="cursor:pointer;font-size:0.85rem;display:flex;justify-content:space-between;align-items:center">
                        <strong>🤖 ${ag.name}</strong>
                        <span style="font-size:0.75rem;color:var(--text-muted)">${tools}</span>
                    </summary>
                    ${ag.description ? `<div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px">${ag.description}</div>` : ''}
                    <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px">
                        ID : <code>${ag.agent_id}</code> · Modèle : ${ag.model || '?'}
                    </div>
                    <div style="font-size:0.78rem;background:var(--bg-secondary);border-radius:6px;padding:6px;margin-top:6px;font-family:monospace">
                        nimm_mistral_agent("votre question", "${ag.agent_id}")
                    </div>
                    <div style="display:flex;gap:6px;margin-top:8px">
                        <button onclick="_magUploadFile('${ag.agent_id}')" style="padding:3px 8px;border-radius:6px;background:var(--bg-secondary);border:1px solid var(--border);cursor:pointer;font-size:0.75rem" aria-label="Ajouter un document à cet agent">📎 Ajouter doc</button>
                        <button onclick="_magDelete('${ag.agent_id}','${ag.name}',this)" style="padding:3px 8px;border-radius:6px;background:var(--danger,#e53935);color:#fff;border:none;cursor:pointer;font-size:0.75rem" aria-label="Supprimer cet agent">🗑 Supprimer</button>
                    </div>
                </details>`;
            }
            h += '</div>';
            magEl.innerHTML = h;
        } catch(e) {
            magEl.innerHTML = '<em style="font-size:0.8rem;color:var(--danger,red)">Erreur chargement agents.</em>';
        }
    })();
    // ── Lister les micros disponibles ──
    _vbPopulateMicList();
    // ── Profils de voix Voxtral ──
    _vbLoadProfiles();
    // ── Services externes ──
    const _extSvcs = (extKeys && extKeys.services) || [];
    const _extListEl = document.getElementById('ext-keys-list');
    if (_extListEl && _extSvcs.length) {
        let _extHtml = '<div style="display:flex;flex-direction:column;gap:12px">';
        const _cats = [...new Set(_extSvcs.map(s => s.category))];
        for (const cat of _cats) {
            _extHtml += `<div><strong style="font-size:0.8rem;color:var(--text-muted);text-transform:uppercase">${cat}</strong><div style="display:flex;flex-direction:column;gap:6px;margin-top:6px">`;
            for (const svc of _extSvcs.filter(s => s.category === cat)) {
                const configured = svc.configured;
                const configuredBadge = configured
                    ? '<span style="color:var(--success,#4caf50);font-size:0.75rem" aria-label="configuré">✔ configuré</span>'
                    : '<span style="color:var(--text-muted);font-size:0.75rem">non configuré</span>';
                const keyInputId = `ext-key-${svc.id}`;
                _extHtml += `<details style="border:1px solid var(--border);border-radius:6px;padding:6px 10px">
                    <summary style="cursor:pointer;font-size:0.85rem;display:flex;justify-content:space-between;align-items:center">
                        <span><strong>${svc.label}</strong> ${svc.needs_key ? '' : '<em style="font-size:0.75rem">(sans clé)</em>'}</span>
                        ${configuredBadge}
                    </summary>
                    <div style="margin-top:8px;font-size:0.8rem;color:var(--text-muted)">${svc.desc}</div>
                    ${svc.needs_key ? `<div style="display:flex;gap:6px;margin-top:8px;align-items:center">
                        <label for="${keyInputId}" style="font-size:0.8rem;white-space:nowrap">${svc.key_label} :</label>
                        <input id="${keyInputId}" type="password" autocomplete="off" placeholder="${configured ? '••••••••' : 'Saisir la clé'}"
                            style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);font-size:0.8rem" />
                        <button onclick="_saveExtKey('${svc.id}')" style="padding:4px 10px;border-radius:6px;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:0.8rem" aria-label="Enregistrer la clé pour ${svc.label}">💾</button>
                        ${configured ? `<button onclick="_deleteExtKey('${svc.id}', this)" style="padding:4px 10px;border-radius:6px;background:var(--danger,#e53935);color:#fff;border:none;cursor:pointer;font-size:0.8rem" aria-label="Supprimer la clé de ${svc.label}">🗑</button>` : ''}
                    </div>` : '<div style="font-size:0.8rem;color:var(--success,#4caf50);margin-top:6px">✔ Accessible sans clé</div>'}
                </details>`;
            }
            _extHtml += '</div></div>';
        }
        _extHtml += '</div>';
        _extListEl.innerHTML = _extHtml;
    } else if (_extListEl) {
        _extListEl.innerHTML = '<em style="font-size:0.8rem">Aucun service référencé.</em>';
    }

    if (isAdmin) {
        document.getElementById('server-mode-chk')?.addEventListener('change', async e => {
            await fetch('/api/settings/server-mode', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: e.target.checked ? 'true' : 'false' })
            });
        });
    }
}

async function _addUser() {
    const name  = document.getElementById('new-user-name')?.value.trim();
    const emoji = document.getElementById('new-user-emoji')?.value.trim() || '👤';
    if (!name) return;
    const id = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '_');
    await fetch('/api/users', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, name, emoji })
    });
    _loadUsersTab();
}

function _showNewProfileForm() {
    const form = document.getElementById('new-profile-form');
    if (!form) return;
    form.style.display = form.style.display === 'flex' ? 'none' : 'flex';
    if (form.style.display === 'flex') {
        document.getElementById('new-profile-name')?.focus();
    }
}

async function _createNewProfile() {
    const name  = (document.getElementById('new-profile-name')?.value || '').trim();
    const emoji = (document.getElementById('new-profile-emoji')?.value || '').trim() || '👤';
    if (!name) { document.getElementById('new-profile-name')?.focus(); return; }
    const id = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || 'user';
    const newUser = await fetch('/api/users', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, name, emoji, admin: false })
    }).then(r => r.json()).catch(() => null);
    if (!newUser) { alert('Erreur lors de la création du profil.'); return; }
    // Basculer sur le nouveau profil → onboarding se chargera d'initialiser sa DB
    _currentUserId = newUser.id;
    localStorage.setItem('nimm-user-id',    newUser.id);
    localStorage.setItem('nimm-user-name',  newUser.name);
    localStorage.setItem('nimm-user-emoji', newUser.emoji || '👤');
    window.location.reload();
}

async function _deleteUser(userId) {
    if (!confirm(`Supprimer le profil ${userId} ?`)) return;
    await fetch(`/api/users/${userId}`, { method: 'DELETE' });
    _loadUsersTab();
}

async function _saveGlobalKeys() {
    const body = {};
    document.querySelectorAll('[data-global-provider]').forEach(el => {
        const p = el.dataset.globalProvider;
        if (el.value.trim()) body[p] = el.value.trim();
    });
    await fetch('/api/settings/global-keys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    _loadUsersTab();
}

// ══════════════════════════════════════════
// INITIALISATION
// ══════════════════════════════════════════

// Heartbeat — maintient le serveur en vie, arrêt à la fermeture
// Ne pas ping tant qu'aucun utilisateur n'est sélectionné — éviterait
// de créer une DB 'laurent' fantôme via le middleware avant l'onboarding.
setInterval(() => {
    if (_currentUserId) fetch('/api/ping').catch(() => {});
}, 5000);

function _slugify(str) {
    return str.toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, '_')
        .replace(/[^a-z0-9_]/g, '')
        .replace(/^_+|_+$/g, '') || 'user';
}

async function init() {
    // Reconnaissance Tailscale (distant) : identité tailnet liée à un profil → on s'y place d'office.
    let _tsMapped = false;
    try {
        const sess = await fetch('/api/session/identity').then(r => r.json()).catch(() => ({}));
        if (sess && sess.mapped_user) {
            _currentUserId = sess.mapped_user;
            localStorage.setItem('nimm-user-id', sess.mapped_user);
            _tsMapped = true;
        }
    } catch (e) {}

    // Verrou par profil au démarrage : un profil à PIN doit être déverrouillé avant d'entrer.
    // (les proches reconnus par identité Tailscale entrent sans saisir de PIN)
    if (_currentUserId && !_tsMapped) {
        if (!(await _ensureUnlocked(_currentUserId))) {
            _currentUserId = '';
            await showUserPicker();
            return;
        }
    }

    // Sélection profil — avant tout le reste
    if (!_currentUserId) {
        // Vérifier si le mode serveur est actif
        const serverMode = await fetch('/api/settings/server-mode')
            .then(r => r.json()).catch(() => ({ enabled: false }));
        if (serverMode.enabled) {
            // Mode serveur : afficher la grille de sélection
            await showUserPicker();
            return; // _selectUser() rappellera init() une fois le profil choisi
        } else {
            // Mode mono : vérifier s'il existe déjà un utilisateur
            const users = await fetch('/api/users').then(r => r.json()).catch(() => []);
            if (users.length > 0) {
                // Prendre le premier utilisateur automatiquement
                await _selectUser(users[0], false);
                return;
            }
            // Aucun utilisateur — laisser l'onboarding ci-dessous prendre le relais
        }
    }

    // Onboarding — afficher si pas de nom configuré
    try {
        const r    = await fetch('/api/identity');
        const data = await r.json();
        if (!data.name || data.name.trim() === '') {
            const modal        = document.getElementById('onboarding-modal');
            const stepDisclaim = document.getElementById('ob-step-disclaimer');
            const stepName     = document.getElementById('ob-step-name');
            const disclaimBtn  = document.getElementById('ob-disclaimer-ok');
            const nameEl       = document.getElementById('ob-name');
            const okBtn        = document.getElementById('onboarding-ok');

            modal.classList.remove('hidden');

            await new Promise(resolve => {
                // Étape 1 : disclaimer
                disclaimBtn.addEventListener('click', () => {
                    stepDisclaim.classList.add('hidden');
                    stepName.classList.remove('hidden');
                    setTimeout(() => nameEl.focus(), 80);
                }, { once: true });

                // Étape 2 : prénom
                let _saving = false;
                const save = async () => {
                    if (_saving) return;
                    const name = nameEl.value.trim();
                    if (!name) return;
                    _saving = true;
                    okBtn.disabled = true;
                    okBtn.textContent = '...';
                    const dob = document.getElementById('ob-dob').value.trim();
                    _currentUserId = _slugify(name);
                    localStorage.setItem('nimm-user-id', _currentUserId);
                    localStorage.setItem('nimm-user-name', name);
                    localStorage.setItem('user-name', name);
                    // Créer le profil users.json si pas encore existant
                    await fetch('/api/users', {
                        method:  'POST',
                        headers: { 'Content-Type': 'application/json', 'X-User-ID': _currentUserId },
                        body:    JSON.stringify({ id: _currentUserId, name, emoji: '👤', admin: true })
                    }).catch(() => {});
                    await fetch('/api/onboarding', {
                        method:  'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body:    JSON.stringify({ name, dob })
                    });
                    modal.classList.add('hidden');
                    resolve();
                };
                okBtn.addEventListener('click', save);
                nameEl.addEventListener('keydown', e => { if (e.key === 'Enter') save(); });
            });
        } else {
            localStorage.setItem('user-name', data.name);
        }
    } catch(e) {
        console.error('[NIMM] Erreur onboarding :', e);
    }

    await loadThreads();

    // Créer un fil par défaut si aucun
    if (threads.length === 0) {
        await fetch('/api/threads', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ name: 'Conversation générale', mode: 'chat' })
        });
        await loadThreads();
    }

    if (threads.length === 0) return;

    // Reprendre le dernier fil consulté
    const lastThreadId = localStorage.getItem('last-thread-id');
    const target = (lastThreadId && threads.find(t => t.thread_id === lastThreadId))
        ? lastThreadId
        : threads[0].thread_id;

    await selectThread(target);
    loadSettingsIntoUI();
    setupUpload();
    setupQuote();

    // Appliquer la police sauvegardée au démarrage
    const savedFont = localStorage.getItem('nimm-font');
    if (savedFont) document.body.style.fontFamily = savedFont;

    // Listener scroll pour le bouton TTS flottant
    const msgs = document.getElementById('messages');
    if (msgs) {
        msgs.addEventListener('scroll', _positionFloatTTS, { passive: true });
    }
}

// ══════════════════════════════════════════
// SIDEBAR — HAMBURGER
// ══════════════════════════════════════════

const sidebarBackdrop = document.getElementById('sidebar-backdrop');

function isMobile() { return window.innerWidth <= 640; }

function openSidebar() {
    if (isMobile()) {
        historyPanel.classList.add('open');
        sidebarBackdrop.style.display = 'block';
    } else {
        historyPanel.classList.remove('hidden');
        setTimeout(_positionFloatTTS, 220); // après transition CSS 0.2s
    }
}

function closeSidebar() {
    if (isMobile()) {
        historyPanel.classList.remove('open');
        sidebarBackdrop.style.display = 'none';
    } else {
        historyPanel.classList.add('hidden');
        setTimeout(_positionFloatTTS, 220); // après transition CSS 0.2s
    }
}

function toggleSidebar() {
    if (isMobile()) {
        historyPanel.classList.contains('open') ? closeSidebar() : openSidebar();
    } else {
        historyPanel.classList.toggle('hidden');
    }
}

document.getElementById('toggle-history').addEventListener('click', toggleSidebar);
sidebarBackdrop.addEventListener('click', closeSidebar);

// ══════════════════════════════════════════
// FILS (THREADS)
// ══════════════════════════════════════════

async function loadThreads() {
    try {
        const r = await fetch('/api/threads');
        threads  = await r.json();
        // Exclure les onglets de la sidebar
        renderSidebar();
    } catch(e) {
        console.error('[NIMM] Erreur chargement fils :', e);
    }
}

function getPinnedThreads() {
    try { return new Set(JSON.parse(localStorage.getItem('pinned-threads') || '[]')); }
    catch { return new Set(); }
}
function togglePinThread(threadId) {
    const pins = getPinnedThreads();
    if (pins.has(threadId)) pins.delete(threadId); else pins.add(threadId);
    localStorage.setItem('pinned-threads', JSON.stringify([...pins]));
}

function renderSidebar() {
    threadList.innerHTML = '';

    // ── Ligne Recherches + Mémoire côte à côte en tête de liste ──
    const topRow = document.createElement('div');
    topRow.className = 'sidebar-top-row';

    const searchBtn = document.createElement('button');
    searchBtn.id        = 'toggle-search-conversations';
    searchBtn.className = 'sidebar-section-btn sidebar-half-btn';
    searchBtn.title     = 'Recherches (raccourci : Alt+Maj+R)';
    searchBtn.setAttribute('aria-label', 'Recherches');
    searchBtn.innerHTML = '<span aria-hidden="true">🔎</span> Recherches';
    topRow.appendChild(searchBtn);

    const memoryTopBtn = document.createElement('button');
    memoryTopBtn.id        = 'toggle-memory';
    memoryTopBtn.className = 'sidebar-section-btn sidebar-half-btn';
    memoryTopBtn.title     = 'Mémoire (raccourci : Alt+Maj+M)';
    memoryTopBtn.setAttribute('aria-label', 'Mémoire');
    memoryTopBtn.innerHTML = '<span aria-hidden="true">🧠</span> Mémoire';
    topRow.appendChild(memoryTopBtn);

    threadList.appendChild(topRow);

    // ── Ligne Nouveau chat + Nouvel onglet (60/40) ──
    const newChatRow = document.createElement('div');
    newChatRow.className = 'thread-actions-row';

    const newChatBtn = document.createElement('button');
    newChatBtn.className = 'thread-new-chat-btn';
    newChatBtn.id = 'new-thread-btn';
    newChatBtn.innerHTML = '<span aria-hidden="true">💬</span> Nouveau fil';
    newChatBtn.setAttribute('aria-label', 'Nouveau fil');
    newChatBtn.setAttribute('aria-keyshortcuts', 'Alt+N');
    newChatBtn.title = 'Nouveau fil';
    newChatBtn.addEventListener('click', async () => {
        const result = await promptNewThreadModal();
        if (result) {
            if (isMobile()) closeSidebar();
            createThread('💬 Nouveau fil', result.maskId, result.mode, result.ghost);
        }
    });
    newChatRow.appendChild(newChatBtn);

    if (currentThreadId) {
        const newTabBtn = document.createElement('button');
        newTabBtn.className = 'thread-new-tab-btn';
        newTabBtn.id = 'new-tab-btn';
        newTabBtn.innerHTML = '<span aria-hidden="true">📑</span> Onglet';
        newTabBtn.setAttribute('aria-label', 'Nouvel onglet');
        newTabBtn.setAttribute('aria-keyshortcuts', 'Alt+O');
        newTabBtn.title = 'Nouvel onglet';
        newTabBtn.addEventListener('click', async () => {
            const name = await promptModal("Nom de l'onglet");
            if (!name) return;
            await fetch(`/api/threads/${currentThreadId}/tabs`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ name: name.trim() })
            });
            await loadThreads();
            await loadTabs(currentThreadId);
            renderTabsBar();
            renderSidebar();
        });
        newChatRow.appendChild(newTabBtn);
    }

    threadList.appendChild(newChatRow);

    // Afficher uniquement les fils racines (pas les onglets) — épinglés en tête
    const pins = getPinnedThreads();
    const roots = threads
        .filter(t => !t.mode?.startsWith('tab:'))
        .sort((a, b) => {
            const pa = pins.has(a.thread_id) ? 0 : 1;
            const pb = pins.has(b.thread_id) ? 0 : 1;
            return pa - pb;
        });
    roots.forEach(t => {
        const div = document.createElement('div');
        div.className = 'thread-item' + (t.thread_id === currentThreadId ? ' active' : ''); div.dataset.tid = t.thread_id;
        const _ouvrir = () => { if (isMobile()) closeSidebar(); selectThread(t.thread_id); };

        const name = document.createElement('span');
        name.className   = 'thread-name';
        name.setAttribute('role', 'button');
        name.setAttribute('tabindex', '0');
        name.setAttribute('aria-label', (t.name || 'Fil') + (t.thread_id === currentThreadId ? ' (fil actif)' : ''));
        name.textContent = t.name;
        name.addEventListener('click', _ouvrir);
        name.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _ouvrir(); } });

        // Badge onglets (desktop) ou liste puce (mobile)
        const childTabs = threads.filter(x => x.mode === `tab:${t.thread_id}`);
        const tabCount  = childTabs.length;
        if (tabCount > 0 && !isMobile()) {
            const badge = document.createElement('span');
            badge.className   = 'thread-tab-badge';
            badge.textContent = `📑 ${tabCount}`;
            badge.title       = `${tabCount} onglet${tabCount > 1 ? 's' : ''}`;
            name.appendChild(badge);
        }

        // Badge étiquettes
        if (t.tags && t.tags.trim()) {
            const tagBadge = document.createElement('span');
            tagBadge.className   = 'thread-tag-badge';
            tagBadge.textContent = `🏷️ ${t.tags.trim()}`;
            tagBadge.title       = `Étiquettes : ${t.tags.trim()}`;
            name.appendChild(tagBadge);
        }

        // Compteur coût cumulé du fil (ajouté après name dans le flex)
        const _costEl = document.createElement('span');
        _costEl.className = 'thread-cost-badge';
        _costEl.id = 'thread-cost-' + t.thread_id;
        const _costVal = _threadCostMap.get(t.thread_id) || 0;
        if (_costVal > 0.000001) {
            _costEl.textContent = _formatCostEur(_costVal) || '';
            _costEl.setAttribute('aria-label', 'Coût cumulé : ' + (_formatCostEur(_costVal) || ''));
        }

        // Menu ...
        const menuBtn = document.createElement('button');
        menuBtn.className = 'thread-menu-btn';
        menuBtn.textContent = '...';
        menuBtn.setAttribute('aria-label', 'Options : ' + (t.name || 'fil'));
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.thread-dropdown.open').forEach(d => d.classList.remove('open'));
            dropdown.classList.toggle('open');
            if (dropdown.classList.contains('open')) {
                _menuKeyboard(menuBtn, dropdown, () => dropdown.classList.remove('open'));
            }
        });

        const dropdown = document.createElement('div');
        dropdown.className = 'thread-dropdown';
        dropdown.setAttribute('role', 'menu');

        // Renommer
        const renItem = document.createElement('button');
        renItem.className = 'thread-dropdown-item';
        renItem.setAttribute('role', 'menuitem');
        renItem.textContent = 'Renommer';
        renItem.addEventListener('click', async (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open'); menuBtn.focus();
            const newName = await promptModal('Renommer le fil', t.name);
            if (!newName || newName.trim() === t.name) return;
            await fetch(`/api/threads/${t.thread_id}`, {
                method:  'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ name: newName.trim() })
            });
            t.name = newName.trim();
            renderSidebar();
        });

        // Exporter en Markdown
        const expItem = document.createElement('button');
        expItem.className = 'thread-dropdown-item';
        expItem.setAttribute('role', 'menuitem');
        expItem.textContent = 'Exporter en Markdown';
        expItem.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open'); menuBtn.focus();
            const a = document.createElement('a');
            a.href = `/api/threads/${t.thread_id}/export`;
            a.download = '';
            document.body.appendChild(a);
            a.click();
            a.remove();
        });

        // Epingler
        const pinItem = document.createElement('button');
        pinItem.className = 'thread-dropdown-item';
        pinItem.setAttribute('role', 'menuitem');
        const isPinned = pins.has(t.thread_id);
        pinItem.textContent = isPinned ? 'Désépingler' : 'Épingler';
        pinItem.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open'); menuBtn.focus();
            togglePinThread(t.thread_id);
            renderSidebar();
            const _reFocus = document.querySelector('.thread-item[data-tid="' + t.thread_id + '"] .thread-menu-btn');
            if (_reFocus) _reFocus.focus();
        });

        // Étiquettes
        const tagItem = document.createElement('button');
        tagItem.className = 'thread-dropdown-item';
        tagItem.setAttribute('role', 'menuitem');
        tagItem.textContent = 'Étiquettes';
        tagItem.addEventListener('click', async (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open'); menuBtn.focus();
            const newTags = await promptModal('Étiquettes (séparées par des virgules)', t.tags || '');
            if (newTags === null) return;
            await fetch(`/api/threads/${t.thread_id}`, {
                method:  'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ tags: newTags.trim() })
            });
            t.tags = newTags.trim();
            renderSidebar();
        });

        // Supprimer
        const delItem = document.createElement('button');
        delItem.className = 'thread-dropdown-item thread-dropdown-danger';
        delItem.setAttribute('role', 'menuitem');
        delItem.textContent = 'Supprimer';
        delItem.addEventListener('click', async (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open'); menuBtn.focus();
            const action = await deleteThreadModal(t.name);
            if (!action) return;
            if (action === 'archive') await archiveThread(t.thread_id);
            fetch(`/api/threads/${t.thread_id}/memorize`, { method: 'POST' }).catch(() => {});
            const allChildTabs = threads.filter(x => x.mode === `tab:${t.thread_id}`);
            for (const tab of allChildTabs) {
                await fetch(`/api/threads/${tab.thread_id}`, { method: 'DELETE' });
            }
            await fetch(`/api/threads/${t.thread_id}`, { method: 'DELETE' });
            if (currentThreadId === t.thread_id || allChildTabs.some(x => x.thread_id === currentTabId)) {
                currentThreadId = null;
                currentTabId    = null;
            }
            await loadThreads();
            if (!currentThreadId && threads.length > 0) {
                await selectThread(threads[0].thread_id);
            } else if (threads.length === 0) {
                currentThreadId = null;
                currentTabId    = null;
                messagesDiv.innerHTML = `
                    <div id="welcome-screen">
                        <img src="/static/bretzel.png" alt="NIMM"
                             style="width:120px;opacity:0.3;margin-bottom:16px;">
                        <span style="font-size:1rem;color:var(--text-muted);">Ouvre un fil pour commencer a discuter</span>
                    </div>`;
                renderTabsBar();
                renderSidebar();
            }
        });

        // Paramètres du fil
        const paramItem = document.createElement('button');
        paramItem.className = 'thread-dropdown-item';
        paramItem.setAttribute('role', 'menuitem');
        paramItem.textContent = '⚙️ Paramètres du fil';
        paramItem.addEventListener('click', async (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open'); menuBtn.focus();
            await promptThreadParamsModal();
        });

        dropdown.appendChild(renItem);
        dropdown.appendChild(expItem);
        dropdown.appendChild(pinItem);
        dropdown.appendChild(tagItem);
        dropdown.appendChild(paramItem);
        dropdown.appendChild(delItem);

        div.appendChild(name);
        div.appendChild(_costEl);
        div.appendChild(menuBtn);
        div.appendChild(dropdown);
        threadList.appendChild(div);

        // Sur mobile : afficher les onglets comme puces sous le fil
        if (isMobile() && tabCount > 0) {
            const tabsList = document.createElement('div');
            tabsList.className = 'thread-tabs-list';
            childTabs.forEach(tab => {
                const item = document.createElement('div');
                item.className = 'thread-tab-item' + (tab.thread_id === currentTabId ? ' active' : '');

                const lbl = document.createElement('span');
                lbl.className   = 'thread-tab-label';
                lbl.textContent = '📑 ' + tab.name;
                lbl.addEventListener('click', () => {
                    closeSidebar();
                    selectTab(tab.thread_id);
                });

                const tabDel = document.createElement('button');
                tabDel.className   = 'thread-tab-del';
                tabDel.textContent = '❌';
                tabDel.setAttribute('aria-label', 'Supprimer cet onglet');
                tabDel.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await fetch(`/api/threads/${tab.thread_id}`, { method: 'DELETE' });
                    if (currentTabId === tab.thread_id) {
                        currentTabId = null;
                        loadMessages(currentThreadId);
                    }
                    await loadTabs(currentThreadId);
                    renderTabsBar();
                    renderSidebar();
                });

                item.appendChild(lbl);
                item.appendChild(tabDel);
                tabsList.appendChild(item);
            });
            threadList.appendChild(tabsList);
        }
    });

    // ── Séparateur + bouton Promptothèque collé après les fils ──
    const promptSep = document.createElement('div');
    promptSep.className = 'sidebar-section-sep';
    threadList.appendChild(promptSep);

    const promptBtn = document.createElement('button');
    promptBtn.id        = 'toggle-prompt-library';
    promptBtn.className = 'sidebar-section-btn';
    promptBtn.title     = 'Promptothèque (raccourci : Alt+Maj+O)';
    promptBtn.setAttribute('aria-label', 'Promptothèque');
    promptBtn.innerHTML = '<span aria-hidden="true">📝</span> Promptothèque';
    threadList.appendChild(promptBtn);

}

async function selectThread(threadId) {
    if (threadId !== currentThreadId) _purgeVibeDocs();
    currentThreadId = threadId;
    currentTabId    = null;
    localStorage.setItem('last-thread-id', threadId);
    localStorage.removeItem('last-tab-id');

    await loadThreads();
    await loadTabs(threadId);
    renderSidebar();
    renderTabsBar();
    await loadMessages(threadId);

    // Indicateur masque verrouillé
    const thread = threads.find(t => t.thread_id === threadId);
    _updateMaskIndicator(thread);
    await _loadGhostMode(threadId);
    await _loadAgentMode(threadId);

    // Focus sur la zone de saisie après chargement du fil
    document.getElementById('user-input')?.focus();

}

function _updateMaskIndicator(thread) {
    // mask-lock-indicator retiré de la topbar — le nom du masque est affiché dans la bulle via .mask-name-tag
}

async function promptNewThreadModal() {
    // Charger les masques disponibles + la configuration en cours
    const [masks, routing, prov, modelData, keys, extKeys] = await Promise.all([
        fetch('/api/masks').then(r => r.json()).catch(() => []),
        fetch('/api/settings/routing').then(r => r.json()).catch(() => ({})),
        fetch('/api/settings/provider').then(r => r.json()).catch(() => ({})),
        fetch('/api/settings/model').then(r => r.json()).catch(() => ({})),
        fetch('/api/settings/api-keys').then(r => r.json()).catch(() => ({})),
        fetch('/api/settings/ext-keys').then(r => r.json()).catch(() => ({services:[]})),
    ]);
    const sel = document.getElementById('new-thread-mask-select');
    sel.innerHTML = masks.map(m => `<option value="${m.id}">${m.label}</option>`).join('');
    const activeMask = document.getElementById('mask-select')?.value;
    if (activeMask) sel.value = activeMask;

    // Pré-déterminer le mode personnalité d'après le fil courant
    const curThread = threads.find(t => t.thread_id === currentThreadId);
    const curMode = curThread?.personality_mode === 'potards' ? 'potards' : 'mask';

    document.querySelectorAll('.new-thread-mode-btn').forEach(b => b.classList.remove('active'));
    (document.querySelector(`.new-thread-mode-btn[data-mode="${curMode}"]`)
        || document.getElementById('new-thread-mode-mask')).classList.add('active');
    document.getElementById('new-thread-mask-row').style.display = curMode === 'mask' ? '' : 'none';

    // Pré-remplir le routage et le modèle avec la configuration en cours
    const providerSel  = document.getElementById('new-thread-provider-select');
    const memSel        = document.getElementById('new-thread-routing-memory');
    const titreSel      = document.getElementById('new-thread-routing-titre');
    const syntheseSel   = document.getElementById('new-thread-routing-synthese');
    const visionSel    = document.getElementById('new-thread-routing-vision');
    const imageSel     = document.getElementById('new-thread-routing-image');
    const coanimSel    = document.getElementById('new-thread-routing-coanimm');
    const ttsSel       = document.getElementById('new-thread-tts-voice');
    const providerVal   = routing.chat || prov.provider || 'mistral';
    const memVal0       = routing.memoire?.provider  || 'same';
    const titreVal0     = routing.titre?.provider    || 'same';
    const syntheseVal0  = routing.synthese?.provider || 'same';
    const visionVal0   = routing.vision?.provider  || 'same';
    const imageVal0    = routing.image?.provider   || 'same';
    const coanimVal0   = routing.coanimm?.provider || 'same';
    // Charger les voix TTS dans le sélecteur
    const currentVoice = localStorage.getItem('nimm-voice') || '';
    fetch('/api/tts/voices').then(r=>r.json()).then(voices => {
        if (!ttsSel) return;
        const list = voices.voices || voices;
        ttsSel.innerHTML = '<option value="">↩ Voix par défaut</option>' +
            list.map(v => `<option value="${v.id}"${v.id===currentVoice?' selected':''}>${v.label}</option>`).join('');
    }).catch(() => { if (ttsSel) ttsSel.innerHTML = '<option value="">↩ Voix par défaut</option>'; });
    if (visionSel) visionSel.value = visionVal0;
    if (imageSel)  imageSel.value  = imageVal0;
    if (coanimSel) coanimSel.value = coanimVal0;

    providerSel.value = providerVal;
    memSel.value      = memVal0;
    titreSel.value    = titreVal0;
    syntheseSel.value = syntheseVal0;
    await _populateModelSelect(providerVal, modelData.model || null, 'new-thread-model-select');
    _applyProviderConstraints(keys);

    providerSel.onchange = async () => {
        await _populateModelSelect(providerSel.value, null, 'new-thread-model-select');
        _applyProviderConstraints(keys);
    };

    return new Promise(resolve => {
        const modal     = document.getElementById('new-thread-modal');
        const okBtn     = document.getElementById('new-thread-ok');
        const cancelBtn = document.getElementById('new-thread-cancel');
        let selectedMode = curMode;

        // Boutons mode
        document.querySelectorAll('.new-thread-mode-btn').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.new-thread-mode-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                selectedMode = btn.dataset.mode;
                document.getElementById('new-thread-mask-row').style.display =
                    selectedMode === 'mask' ? '' : 'none';
            };
        });

        // Jamais cochée par défaut : ne rien conserver doit rester un choix
        // explicite, jamais un reste de la fois précédente.
        const _ghostBox0 = document.getElementById('new-thread-ghost');
        if (_ghostBox0) _ghostBox0.checked = false;
        modal.classList.remove('hidden');

        // Focus accessible : sur l'élément pertinent selon le mode pré-sélectionné
        setTimeout(() => {
            const focusTarget = curMode === 'mask'
                ? document.getElementById('new-thread-mask-select')
                : document.getElementById('new-thread-mode-potards');
            (focusTarget || modal.querySelector('button, select, input'))?.focus();
        }, 50);

        const cleanup = (result) => {
            modal.classList.add('hidden');
            resolve(result);
        };
        okBtn.onclick = async () => {
            const maskId = selectedMode === 'mask'
                ? document.getElementById('new-thread-mask-select').value
                : null;

            // Persister le routage / modèle s'ils ont été modifiés pour ce fil
            if (providerSel.value !== providerVal) {
                await _saveRouting('chat', providerSel.value);
            }
            const modelSel = document.getElementById('new-thread-model-select');
            if (modelSel && modelSel.value && modelSel.value !== (modelData.model || '')) {
                await fetch('/api/settings/model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model: modelSel.value })
                });
            }
            if (memSel.value !== memVal0) {
                await _saveRouting('memoire', memSel.value === 'same' ? {} : { provider: memSel.value });
            }
            if (titreSel.value !== titreVal0) {
                await _saveRouting('titre', titreSel.value === 'same' ? {} : { provider: titreSel.value });
            }
            if (syntheseSel.value !== syntheseVal0) {
                await _saveRouting('synthese', syntheseSel.value === 'same' ? {} : { provider: syntheseSel.value });
            }
            if (visionSel && visionSel.value !== visionVal0) {
                await _saveRouting('vision', visionSel.value === 'same' ? {} : { provider: visionSel.value });
            }
            if (imageSel && imageSel.value !== imageVal0) {
                await _saveRouting('image', imageSel.value === 'same' ? {} : { provider: imageSel.value });
            }
            if (coanimSel && coanimSel.value !== coanimVal0) {
                await _saveRouting('coanimm', coanimSel.value === 'same' ? {} : { provider: coanimSel.value });
            }
            if (ttsSel && ttsSel.value && ttsSel.value !== currentVoice) {
                localStorage.setItem('nimm-voice', ttsSel.value);
                _selectedVoice = ttsSel.value;
            }

            const _ghostBox = document.getElementById('new-thread-ghost');
            cleanup({ maskId, mode: selectedMode, ghost: !!(_ghostBox && _ghostBox.checked) });
        };
        cancelBtn.onclick = () => cleanup(null);
    });
}

// ======================================================
// MODAL PARAMÈTRES DU FIL (modifier routage sur fil existant)
// ======================================================
async function promptThreadParamsModal() {
    const [routing, prov] = await Promise.all([
        fetch('/api/settings/routing').then(r => r.json()).catch(() => ({})),
        fetch('/api/settings/provider').then(r => r.json()).catch(() => ({})),
    ]);
    const providerSel = document.getElementById('new-thread-provider-select');
    const memSel      = document.getElementById('new-thread-routing-memory');
    const titreSel    = document.getElementById('new-thread-routing-titre');
    const syntheseSel = document.getElementById('new-thread-routing-synthese');
    const visionSel   = document.getElementById('new-thread-routing-vision');
    const imageSel    = document.getElementById('new-thread-routing-image');
    const coanimSel   = document.getElementById('new-thread-routing-coanimm');
    const ttsSel      = document.getElementById('new-thread-tts-voice');
    const providerVal = routing.chat   || prov.provider || 'mistral';
    const memVal0     = routing.memoire?.provider  || 'same';
    const titreVal0   = routing.titre?.provider    || 'same';
    const syntheseVal0= routing.synthese?.provider || 'same';
    const visionVal0  = routing.vision?.provider   || 'same';
    const imageVal0   = routing.image?.provider    || 'same';
    const coanimVal0  = routing.coanimm?.provider  || 'same';
    if (providerSel)  providerSel.value  = providerVal;
    if (memSel)       memSel.value        = memVal0;
    if (titreSel)     titreSel.value      = titreVal0;
    if (syntheseSel)  syntheseSel.value   = syntheseVal0;
    if (visionSel)    visionSel.value     = visionVal0;
    if (imageSel)     imageSel.value      = imageVal0;
    if (coanimSel)    coanimSel.value     = coanimVal0;
    // Peupler la liste de modèles pour le fournisseur courant
    await _populateModelSelect(providerVal, null, 'new-thread-model-select');
    // Mettre à jour les modèles quand le fournisseur change
    if (providerSel) providerSel.onchange = async () => {
        await _populateModelSelect(providerSel.value, null, 'new-thread-model-select');
    };
    const currentVoice = localStorage.getItem('nimm-voice') || '';
    fetch('/api/tts/voices').then(r=>r.json()).then(voices => {
        if (!ttsSel) return;
        const list = voices.voices || voices;
        ttsSel.innerHTML = '<option value="">→ Voix par défaut</option>' +
            list.map(v => `<option value="${v.id}"${v.id===currentVoice?' selected':''}>${v.label}</option>`).join('');
    }).catch(() => {});

    // Adapter le titre et masquer les lignes mode/masque
    const modal     = document.getElementById('new-thread-modal');
    const origTitle = modal.querySelector('h2, .modal-title, h3');
    const modeRows  = modal.querySelectorAll('.new-thread-mode-row, #new-thread-mode-section, #new-thread-mask-row, .new-thread-modes, [data-hide-in-params]');
    const savedTitle = origTitle?.textContent || '';
    if (origTitle) origTitle.textContent = '⚙️ Paramètres du fil';
    modeRows.forEach(r => { r._savedDisplay = r.style.display; r.style.display = 'none'; });

    const okBtn     = document.getElementById('new-thread-ok');
    const cancelBtn = document.getElementById('new-thread-cancel');
    const savedOkText = okBtn.textContent;
    okBtn.textContent = 'Appliquer';

    // Déplier toutes les sections
    modal.querySelectorAll('details.settings-section-details').forEach(d => d.open = true);

    // La case « Ne rien conserver » sert aussi ICI : c'est le seul endroit qui
    // reste pour basculer un fil déjà ouvert, depuis que le bouton de la barre
    // a disparu. Le texte d'aide change, parce que la promesse n'est pas la
    // même : on ne peut pas effacer rétroactivement ce qui est déjà écrit.
    const _ghostBoxP = document.getElementById('new-thread-ghost');
    const _ghostAideP = document.getElementById('new-thread-ghost-aide');
    const _ghostAide0 = _ghostAideP ? _ghostAideP.textContent : '';
    let _ghostAvant = false;
    if (_ghostBoxP && currentThreadId) {
        try {
            const _rg = await fetch(`/api/threads/${currentThreadId}/ghost`);
            _ghostAvant = !!(await _rg.json()).ghost;
        } catch (e) { _ghostAvant = false; }
        _ghostBoxP.checked = _ghostAvant;
        if (_ghostAideP) {
            _ghostAideP.textContent = 'Mode fant\u00f4me : \u00e0 partir de maintenant, plus aucun '
                + 'message, m\u00e9moire ni note de carnet ne sera enregistr\u00e9 pour ce fil. '
                + 'Ce qui a d\u00e9j\u00e0 \u00e9t\u00e9 enregistr\u00e9 avant reste en place : pour ne rien '
                + 'laisser du tout, cr\u00e9e plut\u00f4t un nouveau fil avec la case coch\u00e9e.';
        }
    }

    const _paramsPrevFocus = document.activeElement;
    return new Promise(resolve => {
        const cleanup = () => {
            modal.classList.add('hidden');
            setTimeout(() => { _paramsPrevFocus?.focus(); }, 0);
            if (origTitle) origTitle.textContent = savedTitle;
            modeRows.forEach(r => { r.style.display = r._savedDisplay !== undefined ? r._savedDisplay : ''; });
            okBtn.textContent = savedOkText;
            if (_ghostAideP) _ghostAideP.textContent = _ghostAide0;
            modal.querySelectorAll('details.settings-section-details').forEach(d => d.open = false);
            resolve();
        };
        modal.classList.remove('hidden');
        setTimeout(() => {
            (providerSel || modal.querySelector('select, button'))?.focus();
        }, 80);
        okBtn.onclick = async () => {
            if (providerSel && providerSel.value !== providerVal) await _saveRouting('chat', providerSel.value);
            if (memSel      && memSel.value !== memVal0)          await _saveRouting('memoire',  memSel.value === 'same' ? {} : { provider: memSel.value });
            if (titreSel    && titreSel.value !== titreVal0)      await _saveRouting('titre',    titreSel.value === 'same' ? {} : { provider: titreSel.value });
            if (syntheseSel && syntheseSel.value !== syntheseVal0)await _saveRouting('synthese', syntheseSel.value === 'same' ? {} : { provider: syntheseSel.value });
            if (visionSel   && visionSel.value !== visionVal0)    await _saveRouting('vision',   visionSel.value === 'same' ? {} : { provider: visionSel.value });
            if (imageSel    && imageSel.value !== imageVal0)      await _saveRouting('image',    imageSel.value === 'same' ? {} : { provider: imageSel.value });
            if (coanimSel   && coanimSel.value !== coanimVal0)    await _saveRouting('coanimm',  coanimSel.value === 'same' ? {} : { provider: coanimSel.value });
            if (ttsSel      && ttsSel.value && ttsSel.value !== currentVoice) {
                localStorage.setItem('nimm-voice', ttsSel.value);
                _selectedVoice = ttsSel.value;
            }
            // Bascule du mode fantôme. La route côté serveur est une bascule,
            // pas une affectation : on ne l'appelle donc QUE si l'état a changé,
            // sinon on remettrait le fil dans l'état inverse de celui demandé.
            if (_ghostBoxP && currentThreadId && _ghostBoxP.checked !== _ghostAvant) {
                try {
                    const _rp = await fetch(`/api/threads/${currentThreadId}/ghost`, { method: 'POST' });
                    _ghostMode = !!(await _rp.json()).ghost;
                    const _mg = _ghostMode
                        ? 'Mode fant\u00f4me activ\u00e9 : \u00e0 partir de maintenant, rien n\u2019est conserv\u00e9.'
                        : 'Mode fant\u00f4me d\u00e9sactiv\u00e9 : les messages sont \u00e0 nouveau enregistr\u00e9s.';
                    if (typeof _coanimmAnnounce === 'function') _coanimmAnnounce(_mg);
                    if (typeof showToast === 'function') showToast(_mg, _ghostMode ? 'warning' : 'info');
                } catch (e) {}
            }
            // Sauvegarder le modèle sélectionné
            const modelSel = document.getElementById('new-thread-model-select');
            if (modelSel && modelSel.value) {
                await fetch('/api/settings/model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model: modelSel.value })
                });
            }
            cleanup();
        };
        cancelBtn.onclick = cleanup;
    });
}

async function createThread(name, maskId = null, personalityMode = null, ghost = false) {
    // Passe mémoire silencieuse sur le fil courant avant d'en ouvrir un nouveau
    if (currentThreadId) {
        fetch(`/api/threads/${currentThreadId}/memorize`, { method: 'POST' })
            .catch(() => {});  // Fire and forget — n'attend pas la réponse
    }
    const body = { name, mode: 'chat' };
    if (maskId)          body.mask_id          = maskId;
    if (personalityMode) body.personality_mode = personalityMode === 'mask' ? 'mask' : 'potards';
    // Le mode fantôme part AVEC la création : le serveur inscrit le fil dans la
    // liste avant que le moindre message existe. C'est la seule façon de tenir
    // la promesse « aucune trace » du premier échange au dernier.
    if (ghost)           body.ghost            = true;
    const r = await fetch('/api/threads', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body)
    });
    const t = await r.json();
    await loadThreads();
    await selectThread(t.thread_id);
    if (ghost) {
        _ghostMode = true;
        const _m = 'Fil fant\u00f4me cr\u00e9\u00e9 : rien de cet \u00e9change ne sera conserv\u00e9.';
        if (typeof _coanimmAnnounce === 'function') _coanimmAnnounce(_m);
        if (typeof showToast === 'function') showToast(_m, 'warning');
    }
}

// ══════════════════════════════════════════
// ONGLETS (TABS)
// ══════════════════════════════════════════

async function loadTabs(threadId) {
    try {
        const r = await fetch(`/api/threads/${threadId}/tabs`);
        tabs     = await r.json();
    } catch(e) {
        tabs = [];
    }
}

function renderTabsBar() {
    tabsBar.innerHTML = '';

    // ── Zone scrollable : fil actif + ses onglets ──
    const scroll = document.createElement('div');
    scroll.className = 'tabs-scroll';

    if (currentThreadId) {
        const thread    = threads.find(t => t.thread_id === currentThreadId);
        const threadBtn = document.createElement('button');
        threadBtn.className   = 'tab-btn thread-tab' + (!currentTabId ? ' active' : '');
        threadBtn.textContent = '💬 ' + (thread?.name || 'Chat');
        threadBtn.addEventListener('click', () => {
            currentTabId = null;
            localStorage.removeItem('last-tab-id');
            renderTabsBar();
            loadMessages(currentThreadId);
        });
        scroll.appendChild(threadBtn);
    }

    tabs.forEach(tab => {
        const wrap = document.createElement('div');
        wrap.className = 'tab-wrap' + (tab.thread_id === currentTabId ? ' active' : '');

        const btn = document.createElement('button');
        btn.className   = 'tab-btn-inner';
        btn.textContent = tab.name;
        btn.addEventListener('click', () => selectTab(tab.thread_id));

        const del = document.createElement('button');
        del.className   = 'tab-del';
        del.textContent = '✕';
        del.title       = 'Supprimer cet onglet';
        del.addEventListener('click', async (e) => {
            e.stopPropagation();
            await fetch(`/api/threads/${tab.thread_id}`, { method: 'DELETE' });
            if (currentTabId === tab.thread_id) {
                currentTabId = null;
                loadMessages(currentThreadId);
            }
            await loadTabs(currentThreadId);
            renderTabsBar();
            renderSidebar();
        });

        wrap.appendChild(btn);
        // Bouton synthetiser -- uniquement sur l'onglet actif (PC, cache sur mobile via CSS)
        if (tab.thread_id === currentTabId) {
            const synth = document.createElement('button');
            synth.className = 'tab-synth';
            synth.textContent = '←';
            synth.title = 'Synthetiser dans le fil principal';
            synth.setAttribute('aria-label', 'Synthétiser cet onglet dans le fil principal');
            synth.addEventListener('click', (e) => { e.stopPropagation(); synthesizeTab(); });
            wrap.appendChild(synth);
        }
        wrap.appendChild(del);
        scroll.appendChild(wrap);
    });

    tabsBar.appendChild(scroll);

    // Bandeau -- indicateur mobile uniquement (le PC utilise le bouton dans la tab-wrap)
    const synthBar   = document.getElementById('tab-synth-bar');
    const synthLabel = document.getElementById('tab-synth-label');
    if (synthBar) {
        if (currentTabId) {
            const activeTab = tabs.find(t => t.thread_id === currentTabId);
            synthLabel.textContent = '📑 Onglet actif -- ' + (activeTab?.name || 'Onglet');
            synthBar.classList.remove('hidden');
        } else {
            synthBar.classList.add('hidden');
        }
    }

    renderMobileThreadBtn();
}

async function selectTab(tabId) {
    currentTabId = tabId;
    localStorage.setItem('last-tab-id', tabId);
    renderTabsBar();
    await loadMessages(tabId);
    const parentThread = threads.find(t => t.thread_id === currentThreadId);
    _updateMaskIndicator(parentThread);
}

async function synthesizeTab() {
    if (!currentTabId || !currentThreadId) return;

    // Indicateurs de chargement sur les deux boutons (PC + mobile)
    const tabSynthBtn = document.querySelector('.tab-wrap.active .tab-synth');
    const barBtn      = document.getElementById('tab-synth-btn');
    const savedTabLabel = tabSynthBtn ? tabSynthBtn.textContent : '←';
    const savedBarLabel = barBtn ? barBtn.textContent : '← Synthetiser dans le fil';
    if (tabSynthBtn) { tabSynthBtn.disabled = true; tabSynthBtn.textContent = '⏳'; }
    if (barBtn)      { barBtn.disabled = true; barBtn.textContent = '⏳ Generation...'; }

    let result;
    showLoader();
    try {
        const r = await fetch(`/api/threads/${currentTabId}/synthesize`, { method: 'POST' });
        if (!r.ok) throw new Error('Erreur serveur');
        result = await r.json();
    } catch (e) {
        removeLoader();
        if (tabSynthBtn) { tabSynthBtn.disabled = false; tabSynthBtn.textContent = savedTabLabel; }
        if (barBtn)      { barBtn.disabled = false; barBtn.textContent = savedBarLabel; }
        alert('❌ Impossible de generer la synthese.');
        return;
    }

    removeLoader();
    if (tabSynthBtn) { tabSynthBtn.disabled = false; tabSynthBtn.textContent = savedTabLabel; }
    if (barBtn)      { barBtn.disabled = false; barBtn.textContent = savedBarLabel; }

    // Afficher la modale avec la synthese
    const modal   = document.getElementById('synth-modal');
    const title   = document.getElementById('synth-modal-title');
    const body    = document.getElementById('synth-modal-body');
    const confirm = document.getElementById('synth-modal-confirm');
    const cancel  = document.getElementById('synth-modal-cancel');
    const close   = document.getElementById('synth-modal-close');

    // Capturer les IDs au moment de l'ouverture — immunise contre tout changement de navigation
    const tabIdToClose    = currentTabId;
    const parentThreadId  = currentThreadId;

    title.textContent = '📑 ' + result.tab_name;
    body.textContent  = result.synthesis;
    modal.classList.remove('hidden');

    const _close = () => modal.classList.add('hidden');
    close.onclick  = _close;
    cancel.onclick = _close;
    modal.onclick  = (e) => { if (e.target === modal) _close(); };

    confirm.onclick = async () => {
        confirm.disabled = true;
        confirm.textContent = '⏳ Envoi...';
        try {
            const content = `📑 **Synthese — ${result.tab_name}**\n\n${result.synthesis}`;
            // 1. Envoyer dans le fil principal
            const r = await fetch(`/api/threads/${parentThreadId}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: 'assistant', content })
            });
            if (!r.ok) throw new Error(`Erreur sauvegarde message : ${r.status}`);
            // 2. Supprimer l'onglet
            await fetch(`/api/threads/${tabIdToClose}`, { method: 'DELETE' });
            // 3. Revenir au fil principal
            _close();
            currentTabId = null;
            localStorage.removeItem('last-tab-id');
            await loadTabs(parentThreadId);
            renderTabsBar();
            renderSidebar();
            await loadMessages(parentThreadId);
        } catch(e) {
            console.error('[NIMM] Erreur rapatriement synthese :', e);
            alert('❌ Erreur lors de l\'envoi : ' + e.message);
            confirm.disabled = false;
            confirm.textContent = '← Envoyer dans le fil';
        }
    };
}

document.getElementById('tab-synth-btn')?.addEventListener('click', synthesizeTab);

// ══════════════════════════════════════════
// MOBILE — Bouton titre fil + Panneau onglets
// ══════════════════════════════════════════

function renderMobileThreadBtn() {
    if (!isMobile()) return;
    const btn       = document.getElementById('mobile-thread-btn');
    const label     = document.getElementById('mobile-thread-label');
    const indicator = document.getElementById('mobile-tab-indicator');
    if (!btn || !label || !indicator) return;

    if (!currentThreadId) {
        label.textContent = '💬 NIMM';
        indicator.classList.add('hidden');
        return;
    }

    const thread = threads.find(t => t.thread_id === currentThreadId);
    label.textContent = '💬 ' + (thread?.name || 'Chat');

    if (currentTabId) {
        const tab = tabs.find(t => t.thread_id === currentTabId);
        indicator.textContent = '📑 ' + (tab?.name || 'Onglet');
        indicator.classList.remove('hidden');
    } else {
        indicator.classList.add('hidden');
    }
}

function openTabsPanel() {
    renderTabsPanel();
    const panel = document.getElementById('tabs-panel');
    panel.classList.remove('hidden');
    panel.offsetHeight; // force reflow pour déclencher l'animation
    panel.classList.add('open');
}

function closeTabsPanel() {
    const panel = document.getElementById('tabs-panel');
    panel.classList.remove('open');
    setTimeout(() => {
        if (!panel.classList.contains('open')) panel.classList.add('hidden');
    }, 280);
}

function renderTabsPanel() {
    const content = document.getElementById('tabs-panel-content');
    content.innerHTML = '';

    const thread = threads.find(t => t.thread_id === currentThreadId);

    // En-tête : titre du fil
    const header = document.createElement('div');
    header.className   = 'tabs-panel-header';
    header.textContent = '💬 ' + (thread?.name || 'Chat');
    content.appendChild(header);

    // "📑 Créer un onglet" — toujours en premier
    const createItem = document.createElement('div');
    createItem.className   = 'tabs-panel-item create-tab';
    createItem.textContent = '📑 Créer un onglet';
    createItem.addEventListener('click', async () => {
        closeTabsPanel();
        const name = await promptModal("Nom de l'onglet");
        if (!name) return;
        await fetch(`/api/threads/${currentThreadId}/tabs`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ name: name.trim() })
        });
        await loadThreads();
        await loadTabs(currentThreadId);
        renderTabsBar();
        renderSidebar();
    });
    content.appendChild(createItem);

    // Onglets existants
    tabs.forEach(tab => {
        const item = document.createElement('div');
        item.className = 'tabs-panel-item' + (tab.thread_id === currentTabId ? ' active' : '');

        const lbl = document.createElement('span');
        lbl.textContent = '📑 ' + tab.name;
        lbl.style.flex  = '1';
        lbl.addEventListener('click', () => {
            closeTabsPanel();
            selectTab(tab.thread_id);
        });

        const del = document.createElement('button');
        del.className   = 'tabs-panel-del';
        del.textContent = '❌';
        del.setAttribute('aria-label', 'Supprimer cet onglet');
        del.addEventListener('click', async (e) => {
            e.stopPropagation();
            closeTabsPanel();
            await fetch(`/api/threads/${tab.thread_id}`, { method: 'DELETE' });
            if (currentTabId === tab.thread_id) {
                currentTabId = null;
                loadMessages(currentThreadId);
            }
            await loadTabs(currentThreadId);
            renderTabsBar();
            renderSidebar();
        });

        item.appendChild(lbl);
        item.appendChild(del);
        content.appendChild(item);
    });
}

document.getElementById('mobile-thread-btn').addEventListener('click', () => {
    if (!currentThreadId) return;
    const panel = document.getElementById('tabs-panel');
    panel.classList.contains('open') ? closeTabsPanel() : openTabsPanel();
});

document.getElementById('tabs-panel-backdrop').addEventListener('click', closeTabsPanel);

// ══════════════════════════════════════════
// ══════════════════════════════════════════
// MODE QUIZ
// ══════════════════════════════════════════

let _quizState    = { score: 0, total: 0, active: false };
const _quizStore  = {};   // stockage des donnees par card id

function _resetQuiz() {
    _quizState = { score: 0, total: 0, active: false };
}

function _buildQuizCard(data) {
    const id     = 'quiz_' + Math.random().toString(36).slice(2, 9);
    const isVF   = data.type === 'vf';
    _quizStore[id] = { explication: data.explication || '', theme: data.theme || 'ce point' };

    let optionsHtml = '';
    if (isVF) {
        const cTrue  = (data.correct === true)  ? 'true'  : 'false';
        const cFalse = (data.correct === false)  ? 'true'  : 'false';
        optionsHtml = `
            <button class="quiz-btn" data-idx="vrai"  data-correct="${cTrue}"  data-card="${id}">✅ Vrai</button>
            <button class="quiz-btn" data-idx="faux"  data-correct="${cFalse}" data-card="${id}">❌ Faux</button>`;
    } else {
        const labels = ['A', 'B', 'C', 'D'];
        optionsHtml  = (data.options || []).map((opt, i) =>
            `<button class="quiz-btn" data-idx="${i}" data-correct="${i === data.correct ? 'true' : 'false'}" data-card="${id}">` +
            `<span class="quiz-lbl">${labels[i]}</span>${escapeHtml(opt)}</button>`
        ).join('');
    }

    return `<div class="quiz-card" id="${id}">` +
           `<div class="quiz-question">${escapeHtml(data.question || '')}</div>` +
           `<div class="quiz-options">${optionsHtml}</div>` +
           `<div class="quiz-feedback" style="display:none"></div>` +
           `</div>`;
}

function _buildBilanCard() {
    const s   = _quizState.score;
    const t   = _quizState.total;
    const pct = t > 0 ? Math.round(s / t * 100) : 0;
    const medal = pct >= 80 ? '🏆' : pct >= 60 ? '🥈' : '🥉';
    return `<div class="quiz-bilan">${medal} <span class="quiz-bilan-score">${s} / ${t}</span> &mdash; ${pct} % de bonnes reponses</div>`;
}

function _wrapBareQuiz(text) {
    return text.replace(
        /\{[^{}]*"type"\s*:\s*"(?:qcm|vf)"[^{}]*\}/g,
        function(match, offset) {
            var before = text.slice(Math.max(0, offset - 8), offset);
            if (before.indexOf('%%QUIZ%%') !== -1) return match;
            try { JSON.parse(match); return '%%QUIZ%%' + match + '%%/QUIZ%%'; }
            catch(e) { return match; }
        }
    );
}

function _renderBubble(bubble, rawText) {
    rawText = _wrapBareQuiz(rawText);
    const quizBlocks = [];
    let   hasBilan   = false;

    // 1. Extraire les blocs quiz AVANT marked.parse
    let processed = rawText
        .replace(/%%QUIZ%%([\s\S]*?)%%\/QUIZ%%/g, (_, json) => {
            const idx = quizBlocks.length;
            try   { quizBlocks.push(JSON.parse(json.trim())); }
            catch { quizBlocks.push(null); }
            return `QUIZSLOT${idx}END`;
        })
        .replace(/%%QUIZ_BILAN%%([\s\S]*?)%%\/QUIZ_BILAN%%/g, () => {
            hasBilan = true;
            return 'QUIZBILANSLOT';
        });

    // 2. Nettoyer les tags techniques
    processed = processed
        .replace(/%%DOMINANT:[^%]+%%/g, '')
        .replace(/%%MEM:[^%]+%%/g, '')
        .replace(/%%BILAN:[^%]+%%/g, '')
        .replace(/%%ANECDOTE:[^%]+%%/g, '')
        .replace(/%%SITUATION:[^%]+%%/g, '')
        .replace(/%%RAPPEL:[^%]+%%/g, '')
        .replace(/%%IMAGE:[^%]+%%/g, '')
        .replace(/%%[^%]*%%/g, '')
        .trim();

    // 3. Markdown
    let html = window.marked ? marked.parse(_linkifyBareUrls(processed)) : processed.replace(/\n/g, '<br>');
    html = _safeHTML(html);  // désinfection anti-XSS du contenu rendu

    // 4. Injecter les cartes
    quizBlocks.forEach((data, idx) => {
        if (!_quizState.active && data) { _resetQuiz(); _quizState.active = true; }
        html = html.replace(`QUIZSLOT${idx}END`, data ? _buildQuizCard(data) : '');
    });
    if (hasBilan) {
        html = html.replace('QUIZBILANSLOT', _buildBilanCard());
        _resetQuiz();
    }

    bubble.innerHTML = html;
    _attachQuizListeners(bubble);
    _addCodeCopyButtons(bubble);
}

function _addCodeCopyButtons(container) {
    // Bouton « copier » sur chaque bloc de code rendu (pre) — le code est capturé
    // AVANT d'insérer le bouton, pour ne pas copier son propre texte.
    container.querySelectorAll('pre').forEach(pre => {
        if (pre.dataset.codeCopy) return;
        pre.dataset.codeCopy = '1';
        const code = (pre.textContent || '').replace(/\s+$/, '');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'code-copy-btn';
        btn.textContent = '📋';
        btn.setAttribute('aria-label', 'Copier le code');
        btn.addEventListener('click', () => {
            const done = () => {
                btn.textContent = '✓';
                btn.setAttribute('aria-label', 'Code copié');
                setTimeout(() => {
                    btn.textContent = '📋';
                    btn.setAttribute('aria-label', 'Copier le code');
                }, 1600);
            };
            const copie = (navigator.clipboard && navigator.clipboard.writeText)
                ? navigator.clipboard.writeText(code).catch(() => _copyFallback(code))
                : _copyFallback(code);
            copie.then(done).catch(() => {});
        });
        pre.appendChild(btn);
    });
}

function _attachQuizListeners(bubble) {
    bubble.querySelectorAll('.quiz-btn:not([data-bound])').forEach(btn => {
        btn.dataset.bound = '1';
        btn.addEventListener('click', () => _onQuizAnswer(btn));
    });
}

function _onQuizAnswer(btn) {
    const card = btn.closest('.quiz-card');
    if (!card || card.dataset.answered) return;
    card.dataset.answered = '1';

    const isCorrect  = btn.dataset.correct === 'true';
    const stored     = _quizStore[card.id] || {};
    const explication = stored.explication || '';
    const theme       = stored.theme || 'ce point';

    // Verrouiller tous les boutons
    card.querySelectorAll('.quiz-btn').forEach(b => {
        b.disabled = true;
        if (b.dataset.correct === 'true') b.classList.add('quiz-correct');
        else if (b === btn)               b.classList.add('quiz-wrong');
    });

    _quizState.total++;
    if (isCorrect) _quizState.score++;

    const feedback = card.querySelector('.quiz-feedback');
    feedback.style.display = 'block';

    if (isCorrect) {
        feedback.innerHTML =
            `<span class="quiz-fb-ok">✅ Bonne reponse !</span>` +
            (explication ? `<span class="quiz-xp">${escapeHtml(explication)}</span>` : '');
    } else {
        feedback.innerHTML =
            `<span class="quiz-fb-ko">❌ Pas tout a fait.</span>` +
            (explication ? `<span class="quiz-xp">${escapeHtml(explication)}</span>` : '') +
            `<button class="quiz-fiche-btn" data-theme="${escapeHtml(theme)}">📄 Mini fiche : ${escapeHtml(theme)}</button>`;
        feedback.querySelector('.quiz-fiche-btn')?.addEventListener('click', e => {
            const t = e.currentTarget.dataset.theme;
            userInput.value = `Fais-moi une mini fiche sur : ${t}`;
            sendMessage();
        });
    }

    // Bouton suivant
    const nextBtn = document.createElement('button');
    nextBtn.className   = 'quiz-next-btn';
    nextBtn.textContent = 'Question suivante →';
    nextBtn.addEventListener('click', () => {
        nextBtn.disabled = true;
        userInput.value  = 'Question suivante — format %%QUIZ%% obligatoire.';
        sendMessage();
    });
    feedback.appendChild(nextBtn);

    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// MESSAGES
// ══════════════════════════════════════════

async function loadMessages(conversationId) {
    try {
        const r    = await fetch(`/api/threads/${conversationId}/messages`);
        const msgs = await r.json();
        renderMessages(msgs);
        // Calculer le coût cumulé du fil et mettre à jour le badge de la sidebar
        const _totalCost = msgs.reduce((s, m) => s + (m.cost_eur || 0), 0);
        if (_totalCost > 0) {
            _threadCostMap.set(conversationId, _totalCost);
            _updateThreadCostBadge(conversationId);
        }
        document.getElementById('summary-banner').hidden = true;
        document.getElementById('summary-btn').hidden = false;
    } catch(e) {
        console.error('[NIMM] Erreur chargement messages :', e);
    }
}

function renderMessages(messages) {
    messagesDiv.innerHTML = '';
    _msgCounter = 0;
    _hideFloatTTS();

    if (messages.length === 0) {
        const userName = localStorage.getItem('user-name') || 'toi';
        messagesDiv.innerHTML = `
            <div id="welcome-screen">
                <img src="/static/bretzel.png" alt="NIMM"
                     style="width:120px;opacity:0.35;margin-bottom:8px;">
                <span>Salut ${escapeHtml(userName)}, de quoi veux-tu parler ?</span>
            </div>`;
        return;
    }

    messages.forEach(msg => {
        if (msg.role === 'assistant') {
            const { div: _msgDiv } = appendAssistantMessage(msg.content, 'neutre', false);
        } else {
            appendUserMessage(msg.content);
        }
    });

    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// ── Bulle utilisateur ──
function appendUserMessage(content, fileName = null) {
    const div = document.createElement('div');
    div.className = 'message user';

    const bubble = document.createElement('div');
    bubble.className   = 'message-bubble';
    bubble.textContent = content;

    if (fileName) {
        const chip = document.createElement('div');
        chip.style.cssText = 'margin-top:6px;font-size:0.78rem;color:var(--text-muted);'
            + 'background:var(--bg-input);border:1px solid var(--border);'
            + 'border-radius:6px;padding:2px 8px;display:inline-block;';
        chip.textContent = '📎 ' + fileName;
        bubble.appendChild(chip);
    }

    // ── Menu ⋯ sur les messages utilisateur ──
    const actions  = document.createElement('div');
    actions.className = 'message-actions';

    const actBtn = document.createElement('button');
    actBtn.className = 'copy-btn msg-action-btn';
    actBtn.setAttribute('aria-label', 'Ma saisie');
    actBtn.setAttribute('aria-haspopup', 'menu');
    actBtn.setAttribute('aria-expanded', 'false');
    actBtn.innerHTML = SVG_ACT || '⋯';

    const actMenu = document.createElement('div');
    actMenu.className = 'copy-menu';
    actMenu.setAttribute('role', 'menu');
    actMenu.style.display = 'none'; actBtn.focus();
    actMenu.innerHTML = `
        <button class="copy-menu-item" role="menuitem" data-action="copy">📋 Copier</button>
        <button class="copy-menu-item" role="menuitem" data-action="edit">✏️ Modifier</button>
    `;

    actBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        document.querySelectorAll('.copy-menu').forEach(m => m.style.display = 'none');
        document.querySelectorAll('.msg-action-btn').forEach(b => b.setAttribute('aria-expanded', 'false'));
        if (actMenu.style.display === 'none' || actMenu.style.display === '') {
            _positionMenu(actBtn, actMenu, true);
            actMenu.style.display = 'flex';
            actBtn.setAttribute('aria-expanded', 'true');
            _menuKeyboard(actBtn, actMenu, () => {
                actMenu.style.display = 'none'; actBtn.focus();
                actBtn.setAttribute('aria-expanded', 'false');
            });
        } else {
            actMenu.style.display = 'none'; actBtn.focus();
            actBtn.setAttribute('aria-expanded', 'false');
        }
    });

    actMenu.querySelector('[data-action="copy"]').addEventListener('click', () => {
        actMenu.style.display = 'none'; actBtn.focus();
        navigator.clipboard.writeText(content).catch(() => {});
    });
    actMenu.querySelector('[data-action="edit"]').addEventListener('click', () => {
        actMenu.style.display = 'none'; actBtn.focus();
        editLastUserMessage(div, currentTabId || currentThreadId);
    });

    actions.appendChild(actMenu);
    actions.appendChild(actBtn);
    div.dataset.msgIndex = _msgCounter++;
    div.appendChild(bubble);
    div.appendChild(actions);
    messagesDiv.appendChild(div);
}

// ── Bulle assistant ──
// ── Annotation tokens/coût sous une bulle assistant ──
function _formatCostEur(cost_eur) {
    if (!cost_eur || cost_eur < 0.000001) return null;
    if (cost_eur < 0.01) return cost_eur.toFixed(4).replace('.', ',') + ' €';
    return cost_eur.toFixed(3).replace('.', ',') + ' €';
}
function _attachUsageAnnotation(msgDiv, usageData) {
    if (!msgDiv) return;
    const tokIn  = usageData.tokens_in  || 0;
    const tokOut = usageData.tokens_out || 0;
    const cost   = usageData.cost_eur   || 0;
    if (!tokIn && !tokOut) return;
    // Supprimer une annotation précédente si elle existe
    msgDiv.querySelector('.msg-usage-info')?.remove();
    const approx = usageData.estimated ? '≈ ' : '';
    const costStr = _formatCostEur(cost);
    const label   = `Coût de cette réponse : ${tokIn} tokens en entrée, ${tokOut} en sortie${costStr ? ', estimation ' + costStr : ''}`;
    const text    = `↳ ${tokIn} + ${tokOut} tok${costStr ? ' · ' + approx + costStr : ''}`;
    const p = document.createElement('p');
    p.className  = 'msg-usage-info';
    p.setAttribute('role', 'note');
    p.setAttribute('aria-label', label);
    p.textContent = text;
    // Insérer après .msg-bottom, ou à la fin du div
    const bottom = msgDiv.querySelector('.msg-bottom');
    if (bottom) msgDiv.insertBefore(p, bottom.nextSibling);
    else msgDiv.appendChild(p);
}

function _updateThreadCostBadge(tid) {
    const el = document.getElementById('thread-cost-' + tid);
    if (!el) return;
    const cost = _threadCostMap.get(tid) || 0;
    const str  = cost > 0.000001 ? (_formatCostEur(cost) || '') : '';
    el.textContent = str;
    el.setAttribute('aria-label', str ? 'Coût cumulé : ' + str : '');
}

function appendAssistantMessage(content, dominant = 'neutre', animate = true) {
    const pair = EMOJI_MOODS[dominant] || EMOJI_MOODS['neutre'];

    const div = document.createElement('div');
    div.className = 'message assistant';

    // Retirer l'émoji de toutes les bulles précédentes
    messagesDiv.querySelectorAll('.bubble-emoji').forEach(el => el.remove());

    // Émoji expressif — au-dessus de la bulle
    const emoji = document.createElement('div');
    emoji.className = 'bubble-emoji';
    emoji.setAttribute('aria-hidden', 'true');
    const emojiSpan = document.createElement('span');
    emojiSpan.className = 'emoji-char';
    emojiSpan.textContent = '🤔';
    emojiSpan.dataset.dominant = 'reflexion';
    emoji.appendChild(emojiSpan);

    // Rangée emoji + nom du masque
    const thread = threads.find(t => t.thread_id === (currentTabId || currentThreadId));
    const maskLabel = (thread?.mask_id && thread?.personality_mode === 'mask')
        ? (_maskCache[thread.mask_id] || thread.mask_id)
        : 'NIMM';
    const maskTag = document.createElement('span');
    maskTag.className = 'mask-name-tag';
    maskTag.textContent = maskLabel;
    const emojiRow = document.createElement('div');
    emojiRow.className = 'emoji-row';
    emojiRow.appendChild(emoji);
    emojiRow.appendChild(maskTag);

    // Bulle
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    _renderBubble(bubble, content);

    div.appendChild(emojiRow);
    div.appendChild(bubble);

    // Zone bas : actions
    const bottom = document.createElement('div');
    bottom.className = 'msg-bottom';

    // Actions — toujours visibles
    const actions = document.createElement('div');
    actions.className = 'msg-actions';

    // Bouton TTS individuel pour cette bulle
    const ttsBtn = document.createElement('button');
    ttsBtn.className = 'msg-action-btn msg-tts-btn';
    ttsBtn.innerHTML = spk2;
    ttsBtn.title = 'Ecouter';
    ttsBtn.setAttribute('aria-label', 'Écouter ce message');
    ttsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        playTTS(content, ttsBtn);
    });
    actions.appendChild(ttsBtn);

    const actBtn = document.createElement('button');
    actBtn.className = 'msg-action-btn';
    actBtn.innerHTML = SVG_ACT;
    actBtn.title     = 'Actions';
    actBtn.setAttribute('aria-label', 'La réponse');

    const actMenu = document.createElement('div');
    actMenu.className     = 'copy-menu';
    actMenu.style.display = 'none'; actBtn.focus();
    actMenu.setAttribute('role', 'menu');
    actMenu.innerHTML = `
        <button class="copy-menu-item" role="menuitem" data-action="copy">📋 Copier</button>
        <button class="copy-menu-item" role="menuitem" data-action="tab" aria-label="Envoyer en onglet">→ Onglet</button>
        <button class="copy-menu-item" role="menuitem" data-action="regen">🔄 Régénérer</button>
        <button class="copy-menu-item" role="menuitem" data-action="fork">⑂ Forker ici</button>
        <button class="copy-menu-item" role="menuitem" data-action="mark">⭐ Marquer pour export</button>
        <button class="copy-menu-item" role="menuitem" data-action="verify" data-needs-key="anthropic" aria-label="Vérifier les faits de cette réponse">🔎 Vérifier les faits</button>
    `;
    actBtn.setAttribute('aria-haspopup', 'menu');
    actBtn.setAttribute('aria-expanded', 'false');
    actions.appendChild(actMenu);

    actBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        document.querySelectorAll('.copy-menu').forEach(m => m.style.display = 'none');
        document.querySelectorAll('.msg-action-btn').forEach(b => b.setAttribute('aria-expanded', 'false'));
        if (actMenu.style.display === 'none' || actMenu.style.display === '') {
            _positionMenu(actBtn, actMenu);
            actMenu.style.display = 'flex';
            actBtn.setAttribute('aria-expanded', 'true');
            _menuKeyboard(actBtn, actMenu, () => {
                actMenu.style.display = 'none'; actBtn.focus();
                actBtn.setAttribute('aria-expanded', 'false');
            });
        } else {
            actMenu.style.display = 'none'; actBtn.focus();
            actBtn.setAttribute('aria-expanded', 'false');
        }
    });

    actMenu.querySelector('[data-action="copy"]').addEventListener('click', () => {
        _copyToClipboard(content).then(() => {
            actBtn.innerHTML = '✓';
            setTimeout(() => actBtn.innerHTML = SVG_ACT, 1500);
        });
        actMenu.style.display = 'none'; actBtn.focus();
    });

    actMenu.querySelector('[data-action="tab"]').addEventListener('click', () => {
        sendToNewTab(content);
        actMenu.style.display = 'none'; actBtn.focus();
    });

    actMenu.querySelector('[data-action="regen"]').addEventListener('click', () => {
        actMenu.style.display = 'none'; actBtn.focus();
        regenerateMessage(div, currentTabId || currentThreadId);
    });
    actMenu.querySelector('[data-action="fork"]').addEventListener('click', () => {
        actMenu.style.display = 'none'; actBtn.focus();
        forkFromMessage(div, currentTabId || currentThreadId);
    });
    actMenu.querySelector('[data-action="mark"]').addEventListener('click', () => {
        actMenu.style.display = 'none'; actBtn.focus();
        _toggleExportMark(div, content, 'assistant');
        const btn = actMenu.querySelector('[data-action="mark"]');
        btn.textContent = div.dataset.exportMarked ? '★ Marqué' : '⭐ Marquer pour export';
    });

    { const _v = actMenu.querySelector('[data-action="verify"]');
      if (_v) _v.hidden = !_cleDisponible('anthropic'); }
    actMenu.querySelector('[data-action="verify"]')?.addEventListener('click', () => {
        actMenu.style.display = 'none'; actBtn.focus();
        _verifierReponse(content, div.querySelector('.message-bubble'));
    });

    document.addEventListener('click', () => actMenu.style.display = 'none');
    actions.appendChild(actBtn);
    bottom.appendChild(actions);

    div.dataset.msgIndex = _msgCounter++;
    div.appendChild(bottom);
    messagesDiv.appendChild(div);

    // Mettre à jour le bouton TTS flottant pour pointer vers ce message
    _updateFloatTTS(content, div);

    // Démarrer le cycle blink sur cette bulle
    if (animate) {
        stopBlink();
        _blinkEmojiEl = emoji;
        _blinkSchedule = setTimeout(() => startBlink(dominant), 1000);
    }

    return { div, emoji };
}

// ── Envoyer le contenu dans un nouvel onglet ──
async function sendToNewTab(content) {
    if (!currentThreadId) return;
    // Nom provisoire le temps que le LLM genere le vrai titre
    const nameTmp = content.length > 30 ? content.substring(0, 30).trim() + '...' : content.trim();
    const r = await fetch(`/api/threads/${currentThreadId}/tabs`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ name: nameTmp })
    });
    const newTab = await r.json();
    await loadThreads();
    await loadTabs(currentThreadId);
    renderTabsBar();
    renderSidebar();
    await selectTab(newTab.thread_id);
    await fetch(`/api/threads/${newTab.thread_id}/messages`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ role: 'assistant', content: content })
    });
    appendAssistantMessage(content, 'neutre', false);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    // Generation du titre court en arriere-plan -- mise a jour live
    fetch(`/api/threads/${newTab.thread_id}/title`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ content })
    }).then(res => res.json()).then(data => {
        if (data.name) {
            // Mettre a jour le tab en memoire et re-rendre la barre
            const t = tabs.find(t => t.thread_id === newTab.thread_id);
            if (t) { t.name = data.name; renderTabsBar(); }
        }
    }).catch(() => {});
}

// ══════════════════════════════════════════
// BOUTON TTS FLOTTANT
// ══════════════════════════════════════════

let _floatTTSText   = '';       // texte du dernier message assistant
let _floatTTSActive = false;    // true si un message assistant est present

function _positionFloatTTS() {
    const btn = document.getElementById('float-tts-btn');
    const msgs = document.getElementById('messages');
    if (!btn || !msgs) return;
    if (btn.classList.contains('hidden')) return;

    // Ancrer sur la ligne emoji, pas sur la bulle de texte
    const emojiEls = msgs.querySelectorAll('.message.assistant .bubble-emoji');
    if (!emojiEls.length) {
        // Fallback : positionner en haut a droite de #messages
        const rect = msgs.getBoundingClientRect();
        btn.style.left = (rect.right - btn.offsetWidth - 12) + 'px';
        btn.style.top = (rect.top + 12) + 'px';
        return;
    }
    const lastEmoji = emojiEls[emojiEls.length - 1];
    const rect = lastEmoji.getBoundingClientRect();
    const msgsRect = msgs.getBoundingClientRect();

    // Positionner a droite de la zone messages, aligné verticalement sur l'emoji
    let left = msgsRect.right - btn.offsetWidth - 12;
    // Si la bulle est hors ecran a gauche, coller a droite de #messages
    if (left < msgsRect.left) {
        left = msgsRect.right - btn.offsetWidth - 12;
    }

    // Top : suivre la bulle, mais rester dans la zone visible
    let top = rect.top + 12;
    // Si la bulle est au-dessus de l'ecran, coller en haut de #messages
    if (top < msgsRect.top) {
        top = msgsRect.top + 12;
    }
    // Si la bulle est en dessous de l'ecran, coller en bas de #messages
    if (top > msgsRect.bottom - btn.offsetHeight - 12) {
        top = msgsRect.bottom - btn.offsetHeight - 12;
    }

    btn.style.left = left + 'px';
    btn.style.top = top + 'px';
}

function _updateFloatTTS(content, msgDiv) {
    const btn = document.getElementById('float-tts-btn');
    if (!btn) return;

    // Si un audio manuel est en pause (ancien message), le jeter
    if (_currentAudio && _currentAudio.paused) {
        _currentAudio.pause();
        _currentAudio = null;
        if (_currentTTSBtn && _currentTTSBtn._playing) {
            _currentTTSBtn.innerHTML = spk2;
            _currentTTSBtn._playing = false;
        }
        _currentTTSBtn = null;
    }

    // Stocker le texte du dernier message assistant
    _floatTTSText = content;
    _floatTTSActive = true;

    // Bouton du bas : visible sur tous les messages sauf le dernier
    document.querySelectorAll('.msg-tts-btn').forEach(b => b.style.display = '');
    const currentTtsBtn = msgDiv && msgDiv.querySelector('.msg-tts-btn');
    if (currentTtsBtn) currentTtsBtn.style.display = 'none';

    // Le bouton flottant joue toujours le dernier message
    // playTTS gère lui-même le pause/resume si c'est ce bouton qui jouait
    btn.onclick = () => { playTTS(_floatTTSText, btn); };

    // Afficher le bouton
    btn.classList.remove('hidden');

    // Positionner (le listener scroll est ajoute une seule fois dans init)
    _positionFloatTTS();
}

function _hideFloatTTS() {
    const btn = document.getElementById('float-tts-btn');
    if (!btn) return;
    _floatTTSActive = false;
    _floatTTSText = '';
    btn.classList.add('hidden');
    btn.onclick = null;
}

// ══════════════════════════════════════════
// ÉMOJI EXPRESSIF — CYCLE CLIGNOTEMENT
// ══════════════════════════════════════════

// startEmojiCycle remplacé par startBlink/stopBlink

// ══════════════════════════════════════════
// LOADER
// ══════════════════════════════════════════

// ── Bretzel path data (partagé entre loaders) ──
const _BRETZEL_PATH = `m 317.77777,1459.9999 c 0,0 96.60164,-108.0571 279.99998,-226.6666 183.39834,-118.6095 327.41223,-163.9672 484.44435,-257.77777 126.1042,-75.33426 326.5798,-134.72399 366.6667,-244.44445 36.2712,-99.2767 17.0019,-221.446 -31.1111,-315.55554 -50.4039,-98.59048 -148.5092,-173.26077 -248.8889,-219.99999 -82.1474,-38.24983 -178.4208,-45.17487 -268.88884,-40 -105.65992,6.04386 -219.07726,22.81981 -306.66665,82.22222 -93.30701,63.28005 -160.02857,166.56323 -202.22222,271.1111 -35.21073,87.24552 -45.51656,186.44596 -35.55555,279.99998 10.39283,97.6097 47.77906,193.30413 97.77777,277.77775 58.24823,98.4113 133.79605,192.034 228.88888,255.5556 111.62397,74.5644 221.60306,103.0648 353.33331,128.8889 146.2885,28.6781 317.7257,35.2781 464.4444,8.8888 129.3284,-23.2615 259.9346,-67.7297 371.1111,-137.7777 119.9177,-75.5555 243.6721,-160.5724 320,-280 69.4258,-108.62818 112.6635,-242.2477 108.8889,-371.11112 C 2296.9129,565.721 2260.1345,454.90651 2193.3332,373.33332 2113.329,275.63761 1990.796,210.6982 1868.8888,177.77777 c -95.8374,-25.88039 -202.3099,-22.7673 -297.7778,4.44444 -66.4605,18.94359 -130.9575,28.70574 -195.5555,80 -64.5979,51.29427 -153.3954,149.22093 -182.2222,233.33332 -28.8268,84.1124 -0.9423,183.60082 26.6666,244.44444 37.6598,82.99346 120.5864,120.65517 193.3334,175.55554 120.4277,90.88379 226.0132,163.97729 359.9999,233.33329 110.9245,57.4182 402.8208,243.9279 506.6667,313.3334`;

function _buildBretzelSVG(w, h) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'bretzel-loader-svg');
    svg.setAttribute('width', w);
    svg.setAttribute('height', h);
    svg.setAttribute('viewBox', '-60 -60 2114 1456');

    // Filtre glow pour la tête
    const defs = document.createElementNS(ns, 'defs');
    const filter = document.createElementNS(ns, 'filter');
    filter.setAttribute('id', 'bl-glow');
    filter.setAttribute('x', '-40%'); filter.setAttribute('y', '-40%');
    filter.setAttribute('width', '180%'); filter.setAttribute('height', '180%');
    const blur = document.createElementNS(ns, 'feGaussianBlur');
    blur.setAttribute('stdDeviation', '55'); blur.setAttribute('result', 'blur');
    const merge = document.createElementNS(ns, 'feMerge');
    const mn1 = document.createElementNS(ns, 'feMergeNode'); mn1.setAttribute('in', 'blur');
    const mn2 = document.createElementNS(ns, 'feMergeNode'); mn2.setAttribute('in', 'SourceGraphic');
    merge.appendChild(mn1); merge.appendChild(mn2);
    filter.appendChild(blur); filter.appendChild(merge);
    defs.appendChild(filter); svg.appendChild(defs);

    const g = document.createElementNS(ns, 'g');
    g.setAttribute('transform', 'translate(-312.8468,-147.42696)');

    function mkPath(cls, stroke, opacity, extra) {
        const p = document.createElementNS(ns, 'path');
        p.setAttribute('class', cls);
        p.setAttribute('fill', 'none');
        p.setAttribute('stroke', stroke);
        p.setAttribute('stroke-opacity', opacity);
        p.setAttribute('stroke-width', '160');
        p.setAttribute('stroke-linecap', 'round');
        p.setAttribute('stroke-linejoin', 'round');
        if (extra) p.setAttribute('filter', extra);
        p.setAttribute('d', _BRETZEL_PATH);
        return p;
    }

    g.appendChild(mkPath('bl-base',  '#2a1408', '0.50'));
    g.appendChild(mkPath('bl-tail3', '#4a2c18', '0.15'));
    g.appendChild(mkPath('bl-tail2', '#7a4020', '0.35'));
    g.appendChild(mkPath('bl-tail1', '#b06030', '0.62'));
    g.appendChild(mkPath('bl-head',  '#d4853d', '0.95', 'url(#bl-glow)'));
    svg.appendChild(g);
    return svg;
}

function _startBretzelAnim(svg, loader) {
    const head  = svg.querySelector('.bl-head');
    const tail1 = svg.querySelector('.bl-tail1');
    const tail2 = svg.querySelector('.bl-tail2');
    const tail3 = svg.querySelector('.bl-tail3');

    const len   = head.getTotalLength();
    const speed = len / (3.5 * 60); // ~3.5s par tour à 60fps
    const hSeg  = len * 0.03;       // tête : 3% — point court et lumineux
    const t1Seg = len * 0.10;       // traîne proche
    const t2Seg = len * 0.22;       // traîne moyenne
    const t3Seg = len * 0.40;       // longue queue qui s'éteint

    head.style.strokeDasharray  = `${hSeg}  ${len - hSeg}`;
    tail1.style.strokeDasharray = `${t1Seg} ${len - t1Seg}`;
    tail2.style.strokeDasharray = `${t2Seg} ${len - t2Seg}`;
    tail3.style.strokeDasharray = `${t3Seg} ${len - t3Seg}`;

    let off = 0, rafId = null;
    function tick() {
        off -= speed;
        if (off < -len) off = 0;
        // Tête en avant — traînes décalées derrière (offset positif = segment en retard)
        head.style.strokeDashoffset  = off;
        tail1.style.strokeDashoffset = off + t1Seg;
        tail2.style.strokeDashoffset = off + t2Seg;
        tail3.style.strokeDashoffset = off + t3Seg;
        rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);
    loader._cancelAnim = () => cancelAnimationFrame(rafId);
}

// ── Annonce lecteur d'écran (zone live discrète, hors flux affiché) ──
/**
 * _renderCitations : affiche les sources Mistral web search
 * sous la bulle assistante, dans une region accessible.
 * @param {HTMLElement} msgDiv - le div .message.assistant
 * @param {Array} citations   - tableau {url, title, snippet}
 */
function _renderCitations(msgDiv, citations) {
    if (!msgDiv || !citations || !citations.length) return;
    // Supprimer une eventuelle zone precedente (ne pas dupliquer)
    var old = msgDiv.querySelector('.citations-region');
    if (old) old.remove();

    var region = document.createElement('div');
    region.className = 'citations-region';
    region.setAttribute('role', 'region');
    region.setAttribute('aria-label', 'Sources web');

    var title = document.createElement('p');
    title.className = 'citations-title';
    title.textContent = 'Sources :';
    region.appendChild(title);

    var ol = document.createElement('ol');
    ol.className = 'citations-list';
    citations.forEach(function(c, i) {
        var li = document.createElement('li');
        var a = document.createElement('a');
        a.href = c.url || '#';
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = c.title || c.url || ('Source ' + (i + 1));
        if (c.snippet) {
            var sm = document.createElement('span');
            sm.className = 'citations-snippet';
            sm.textContent = ' — ' + c.snippet.slice(0, 120) + (c.snippet.length > 120 ? '…' : '');
            sm.setAttribute('aria-hidden', 'true');
            a.appendChild(sm);
        }
        li.appendChild(a);
        ol.appendChild(li);
    });
    region.appendChild(ol);

    // Inserer apres la bulle
    var bubble = msgDiv.querySelector('.message-bubble');
    if (bubble && bubble.nextSibling) {
        msgDiv.insertBefore(region, bubble.nextSibling);
    } else {
        msgDiv.appendChild(region);
    }
}

// ── Texte alternatif honnête d'une image produite par NIMM ────────────────
// Un alt qui répète la consigne MENT : il dit ce qu'on a demandé, pas ce qui a
// été produit. Après une retouche c'est pire encore — la consigne est alors une
// instruction (« mets-le en noir et blanc »), pas une description.
// Règle tenue ici : soit une vraie description, soit on écrit qu'il n'y en a
// pas. Jamais la consigne déguisée.
// Hors du chemin critique : l'image est déjà affichée quand on appelle ceci.
async function _decrireImageGeneree(bubble, b64, url, consigne) {
    const imgEl = bubble && bubble.querySelector('img');
    if (!imgEl) return '';
    let desc = '', raison = '';
    try {
        const rd = await fetch('/api/image/decrire', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ b64: b64 || '', url: url || '' })
        });
        const dd = await rd.json();
        desc = (dd.description || '').trim();
        raison = dd.raison || '';
    } catch (e) { raison = e.message; }

    if (desc) {
        imgEl.alt = desc;
        const det = document.createElement('details');
        det.style.cssText = 'margin-top:6px;';
        const sum = document.createElement('summary');
        sum.style.cssText = 'cursor:pointer;font-size:0.8rem;color:var(--text-muted);';
        sum.textContent = "Description de l'image";
        const zone = document.createElement('textarea');
        zone.readOnly = true;
        zone.rows = 4;
        zone.value = desc;
        zone.setAttribute('aria-label', "Description de l'image générée");
        zone.style.cssText = 'width:100%;box-sizing:border-box;font-size:0.82rem;margin-top:4px;';
        det.appendChild(sum); det.appendChild(zone);
        bubble.appendChild(det);
    } else {
        imgEl.alt = 'Image générée à partir de la consigne « ' + (consigne || '')
            + ' ». Description automatique indisponible'
            + (raison ? ' : ' + raison : '.');
    }
    if (typeof _srAnnounce === 'function') {
        _srAnnounce(desc ? 'Image décrite.' : 'Image générée, sans description disponible.');
    }
    return desc;
}

function _srAnnounce(text) {
    const el = document.getElementById('sr-stream-status');
    if (!el) return;
    el.textContent = '';
    // Forcer la ré-annonce même si le texte est identique au précédent
    requestAnimationFrame(() => { el.textContent = text; });
}

function showLoader() {
    const loader = document.createElement('div');
    loader.id        = 'thinking-loader';
    loader.className = 'message assistant';

    const row = document.createElement('div');
    row.className = 'message-row';

    const emojiDiv  = document.createElement('div');
    emojiDiv.className = 'bubble-emoji';
    emojiDiv.setAttribute('aria-hidden', 'true');
    const emojiSpan = document.createElement('span');
    emojiSpan.className        = 'emoji-char loader-emoji';
    emojiSpan.textContent      = '🤔';
    emojiSpan.dataset.dominant = 'reflexion';
    emojiDiv.appendChild(emojiSpan);

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble loader-bretzel';

    const svg = _buildBretzelSVG(30, 20);
    bubble.appendChild(svg);

    row.appendChild(emojiDiv);
    row.appendChild(bubble);
    loader.appendChild(row);
    messagesDiv.appendChild(loader);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    // Démarrer l'animation après insertion dans le DOM (getTotalLength() requiert le DOM)
    requestAnimationFrame(() => _startBretzelAnim(svg, loader));

    _srAnnounce('NIMM réfléchit…');
}

function removeLoader() {
    const loader = document.getElementById('thinking-loader');
    if (loader?._cancelAnim) loader._cancelAnim();
    loader?.remove();
}

function animateEmojiToLoader(preRect = null) {
    // Trouver le dernier emoji dans une bulle assistant (pas le loader)
    const allEmojis = messagesDiv.querySelectorAll('.message.assistant:not(#thinking-loader) .bubble-emoji');
    if (!allEmojis.length) return;
    const sourceEmoji = allEmojis[allEmojis.length - 1];

    // Supprimer immédiatement tous les anciens emojis (pas le dernier)
    Array.from(allEmojis).slice(0, -1).forEach(el => el.remove());

    // Trouver la destination : le slot emoji dans le loader
    const loader = document.getElementById('thinking-loader');
    if (!loader) return;
    const destSlot = loader.querySelector('.loader-emoji');
    if (!destSlot) return;

    // Masquer immédiatement l'emoji source et la destination
    sourceEmoji.style.opacity = '0';
    destSlot.style.opacity = '0';

    // Sur mobile : dézoom source → zoom destination
    if (window.innerWidth <= 640) {
        sourceEmoji.style.transformOrigin = 'center center';
        sourceEmoji.style.animation = 'emojiShrink 0.25s cubic-bezier(0.36, 0, 0.66, -0.56) forwards';
        setTimeout(() => {
            sourceEmoji.remove();
            destSlot.style.opacity = '1';
            destSlot.style.animation = 'maskPop 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both';
        }, 250);
        return;
    }

    // Utiliser la position pré-calculée (avant scroll) ou recalculer
    const srcRect  = preRect || sourceEmoji.getBoundingClientRect();
    const destRect = destSlot.getBoundingClientRect();

    // Si la source est hors viewport, apparition directe sans vol
    if (srcRect.bottom < 0 || srcRect.top > window.innerHeight) {
        sourceEmoji.remove();
        destSlot.style.opacity = '1';
        return;
    }

    // Forcer un reflow pour garantir le masquage avant l'animation
    void sourceEmoji.offsetHeight;

    // Créer le volant
    const flyer = document.createElement('span');
    flyer.className   = 'emoji-flyer';
    flyer.textContent = '🙂‍↕️';
    flyer.style.left  = srcRect.left + 'px';
    flyer.style.top   = srcRect.top  + 'px';
    document.body.appendChild(flyer);

    // Durée du vol
    const duration = 420;

    // Animation JS : interpolation position
    const startX = srcRect.left;
    const startY = srcRect.top;
    const endX   = destRect.left;
    const endY   = destRect.top;
    const startT = performance.now();

    // Appliquer déformation vol
    flyer.style.animation = `emojiFlight ${duration}ms ease-in-out forwards`;

    function step(now) {
        const elapsed  = now - startT;
        const progress = Math.min(elapsed / duration, 1);
        // Easing cubique
        const t = progress < 0.5
            ? 4 * progress * progress * progress
            : 1 - Math.pow(-2 * progress + 2, 3) / 2;

        flyer.style.left = (startX + (endX - startX) * t) + 'px';
        flyer.style.top  = (startY + (endY - startY) * t) + 'px';

        if (progress < 1) {
            requestAnimationFrame(step);
        } else {
            // Atterrissage
            flyer.style.animation = `emojiLand 350ms ease-out forwards`;
            setTimeout(() => {
                flyer.remove();
                sourceEmoji.remove(); // Nettoyer l'emoji source
                destSlot.style.opacity = '1';
            }, 350);
        }
    }

    requestAnimationFrame(step);
}

// ══════════════════════════════════════════
// GÉOLOCALISATION
// ══════════════════════════════════════════

async function _getLocation() {
    return new Promise((resolve) => {
        if (!navigator.geolocation) { resolve(null); return; }
        navigator.geolocation.getCurrentPosition(
            async (pos) => {
                try {
                    const { latitude: lat, longitude: lon } = pos.coords;
                    const r = await fetch(
                        `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&accept-language=fr`,
                        { headers: { 'User-Agent': 'NIMM-Assistant/1.0' } }
                    );
                    const d = await r.json();
                    const a = d.address || {};
                    const commune = a.village || a.town || a.city || a.municipality || '';
                    const dept    = a.county || a.state_district || '';
                    const region  = a.state || '';
                    const loc = [commune, dept, region].filter(Boolean).join(', ');
                    resolve(loc || null);
                } catch { resolve(null); }
            },
            () => resolve(null),
            { timeout: 3000, maximumAge: 30000 }
        );
    });
}

// ══════════════════════════════════════════
// STREAM — MOTEUR COMMUN
// ══════════════════════════════════════════

async function _triggerStream(content, conversationId, images = null, vibeDocs = null) {
    // Capturer la position de l'emoji précédent AVANT que showLoader() scrolle
    const _preEmojis = messagesDiv.querySelectorAll('.message.assistant:not(#thinking-loader) .bubble-emoji');
    const _preEmojiRect = _preEmojis.length
        ? _preEmojis[_preEmojis.length - 1].getBoundingClientRect()
        : null;
    showLoader();
    animateEmojiToLoader(_preEmojiRect);

    // Bouton Stop
    _streamAbortController = new AbortController();
    const stopBtn = document.getElementById('stop-btn');
    const sendBtn = document.getElementById('send-btn');
    if (stopBtn) { stopBtn.hidden = false; stopBtn.onclick = stopStream; }
    if (sendBtn) sendBtn.hidden = true;

    const _location = await _getLocation();

    try {
        const r = await fetch('/api/chat/stream', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            signal:  _streamAbortController.signal,
            body:    JSON.stringify({
                message:    content,
                thread_id:  conversationId,
                web_search: _webSearchActive,
                ...(images ? { images } : {}),
                ...(vibeDocs ? { vibe_docs: vibeDocs } : {}),
                ...(_location ? { location: _location } : {}),
            })
        });

        if (!r.ok) {
            const _status = r.status;
            _notifyServiceError(_status);
            throw new Error(`HTTP ${_status}`);
        }

        _bip(220, 80); // bip grave : début de réponse
        // Retirer la bulle "recherche en cours" / "outil en cours" si elle est encore affichée
        document.getElementById('web-search-loader')?.remove();
        document.getElementById('tool-loading')?.remove();

        // Transformer le loader en bulle de réponse — zéro saut visuel
        const loaderEl = document.getElementById('thinking-loader');
        loaderEl.removeAttribute('id');
        loaderEl.dataset.msgIndex = _msgCounter++;
        const div    = loaderEl;
        const emoji  = div.querySelector('.bubble-emoji');
        const bubble = div.querySelector('.message-bubble');
        loaderEl._cancelAnim?.();
        bubble.classList.remove('loader-bretzel');
        bubble.textContent = '';

        // Nom du masque attaché au fil (ou NIMM par défaut)
        const _streamThread = threads.find(t => t.thread_id === (currentTabId || currentThreadId));
        const _streamMaskLabel = (_streamThread?.mask_id && _streamThread?.personality_mode === 'mask')
            ? (_maskCache[_streamThread.mask_id] || _streamThread.mask_id)
            : 'NIMM';
        const _streamMaskTag = document.createElement('span');
        _streamMaskTag.className = 'mask-name-tag';
        _streamMaskTag.textContent = _streamMaskLabel;
        const _streamEmojiRow = document.createElement('div');
        _streamEmojiRow.className = 'emoji-row';
        emoji.parentNode.insertBefore(_streamEmojiRow, emoji);
        _streamEmojiRow.appendChild(emoji);
        _streamEmojiRow.appendChild(_streamMaskTag);

        // Zone bas (plus de bouton TTS individuel — utilise le flottant)
        const bottom = document.createElement('div');
        bottom.className = 'msg-bottom';

        const msgActions = document.createElement('div');
        msgActions.className = 'msg-actions';

        // Bouton TTS individuel pour cette bulle (stream)
        const streamTtsBtn = document.createElement('button');
        streamTtsBtn.className = 'msg-action-btn msg-tts-btn';
        streamTtsBtn.innerHTML = spk2;
        streamTtsBtn.title = 'Ecouter';
        streamTtsBtn.setAttribute('aria-label', 'Écouter ce message');
        streamTtsBtn.style.display = 'none';
        msgActions.appendChild(streamTtsBtn);

        const actBtn = document.createElement('button');
        actBtn.className = 'msg-action-btn';
        actBtn.innerHTML = SVG_ACT;
        actBtn.title     = 'Actions';
        actBtn.setAttribute('aria-label', 'La réponse');

        const actMenu = document.createElement('div');
        actMenu.className     = 'copy-menu';
        actMenu.style.display = 'none'; actBtn.focus();
        actMenu.setAttribute('role', 'menu');
        actMenu.innerHTML = `
            <button class="copy-menu-item" role="menuitem" data-action="copy">📋 Copier</button>
            <button class="copy-menu-item" role="menuitem" data-action="tab" aria-label="Envoyer en onglet">→ Onglet</button>
            <button class="copy-menu-item" role="menuitem" data-action="regen">🔄 Régénérer</button>
            <button class="copy-menu-item" role="menuitem" data-action="fork">⑂ Forker ici</button>
            <button class="copy-menu-item" role="menuitem" data-action="mark">⭐ Marquer pour export</button>
            <button class="copy-menu-item" role="menuitem" data-action="verify" data-needs-key="anthropic" aria-label="Vérifier les faits de cette réponse">🔎 Vérifier les faits</button>
        `;
        actBtn.setAttribute('aria-haspopup', 'menu');
        actBtn.setAttribute('aria-expanded', 'false');

        actBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.copy-menu').forEach(m => m.style.display = 'none');
            document.querySelectorAll('.msg-action-btn').forEach(b => b.setAttribute('aria-expanded', 'false'));
            if (actMenu.style.display === 'none' || actMenu.style.display === '') {
                _positionMenu(actBtn, actMenu);
                actMenu.style.display = 'flex';
                actBtn.setAttribute('aria-expanded', 'true');
                _menuKeyboard(actBtn, actMenu, () => {
                    actMenu.style.display = 'none'; actBtn.focus();
                    actBtn.setAttribute('aria-expanded', 'false');
                });
            } else {
                actMenu.style.display = 'none'; actBtn.focus();
                actBtn.setAttribute('aria-expanded', 'false');
            }
        });
        document.addEventListener('click', () => actMenu.style.display = 'none');

        msgActions.appendChild(actMenu);
        msgActions.appendChild(actBtn);
        bottom.appendChild(msgActions);
        div.appendChild(bottom);

        let fullText        = '';
        let dominant        = 'neutre';
        let moodScore       = 5;
        let _streamTruncated = false;

        // Rendu par paragraphes avec effet scramble
        let _renderedUpTo = 0;          // nb de paragraphes déjà rendus+animés
        const _paraNodes  = [];         // spans DOM pour chaque paragraphe rendu

        function _scrambleReveal(span, finalHtml) {
            // Phase 1 : effet anaglyphe/glitch sur le texte brut (~320ms)
            // Phase 2 : dissolution vers HTML propre rendu
            const plainText = finalHtml.replace(/<[^>]+>/g, '');
            span.textContent = plainText;
            span.setAttribute('data-text', plainText);
            span.classList.add('glitch-anaglyph');
            let step = 0;
            const steps = 8;
            const iv = setInterval(() => {
                step++;
                // Vibration aléatoire de l'offset à chaque tick
                const dx = (Math.random() * 4 - 2).toFixed(1);
                const dy = (Math.random() * 3 - 1.5).toFixed(1);
                span.style.setProperty('--gx', dx + 'px');
                span.style.setProperty('--gy', dy + 'px');
                if (step >= steps) {
                    clearInterval(iv);
                    span.classList.remove('glitch-anaglyph');
                    span.style.removeProperty('--gx');
                    span.style.removeProperty('--gy');
                    span.innerHTML = finalHtml;
                    _addCodeCopyButtons(span);
                    span.style.opacity = '1';
                    span.style.transition = 'opacity 0.15s ease';
                }
            }, 40);
        }

        function _flushRenderedParagraphs(displayText, force) {
            // Découpe le texte propre en paragraphes séparés par \n\n
            const parts = displayText.split(/\n\n+/);
            // Le dernier fragment est "en cours" sauf si force (fin de stream)
            const limit = force ? parts.length : parts.length - 1;
            for (let i = _renderedUpTo; i < limit; i++) {
                const raw = parts[i].trim();
                if (!raw) continue;
                const html = window.marked ? marked.parse(_linkifyBareUrls(raw)) : raw.replace(/\n/g,'<br>');
                let span;
                if (_paraNodes[i]) {
                    span = _paraNodes[i];
                } else {
                    span = document.createElement('div');
                    span.className = 'stream-para';
                    bubble.appendChild(span);
                    _paraNodes[i] = span;
                }
                _scrambleReveal(span, html);
                _renderedUpTo = i + 1;
            }
            // Paragraphe en cours : texte brut sans balises Markdown visibles
            if (!force && parts.length > 0) {
                const inProgress = parts[parts.length - 1]
                    .replace(/^#{1,6}\s*/gm, '')
                    .replace(/\*\*?|__?/g, '')
                    .replace(/`/g, '');
                let liveSpan = _paraNodes[limit];
                if (!liveSpan) {
                    liveSpan = document.createElement('div');
                    liveSpan.className = 'stream-para stream-para-live';
                    bubble.appendChild(liveSpan);
                    _paraNodes[limit] = liveSpan;
                }
                liveSpan.textContent = inProgress;
                liveSpan.style.opacity = '0.75';
            }
        }

        const reader  = r.body.getReader();
        const decoder = new TextDecoder();
        let   buffer  = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);

                if (data === '[DONE]') break;

                if (data === '[TRUNCATED]') { _streamTruncated = true; continue; }
                if (data.startsWith('[RAISONNEMENT]')) {
                    // Chaîne de pensée d'un modèle de raisonnement : déjà payée,
                    // rendue consultable — mais repliée, pour ne pas doubler la
                    // longueur de ce qu'il y a à lire.
                    try { _streamRaisonnement = JSON.parse(data.slice(14)); } catch (e) {}
                    continue;
                }

                if (data.startsWith('[META]')) {
                    try {
                        const meta = JSON.parse(data.slice(6));
                        dominant  = meta.dominant || 'neutre';
                        moodScore = (meta.mood_vector && meta.mood_vector[0]) ? meta.mood_vector[0].s : 5;
                    } catch(e) {}
                    continue;
                }


                if (data.startsWith('[WEB_SEARCH_LOADING]')) {
                    if (!document.getElementById('web-search-loader')) {
                        const wsDiv = document.createElement('div');
                        wsDiv.id        = 'web-search-loader';
                        wsDiv.className = 'message assistant';
                        const wsEmoji = document.createElement('div');
                        wsEmoji.className = 'bubble-emoji';
                        wsEmoji.setAttribute('aria-hidden', 'true');
                        const wsBubble = document.createElement('div');
                        wsBubble.className = 'message-bubble web-search-loader';
                        wsBubble.innerHTML = '<span>🌐 Recherche en cours…</span><span class="stt-dots"><span></span><span></span><span></span></span>';
                        wsDiv.appendChild(wsEmoji);
                        wsDiv.appendChild(wsBubble);
                        document.getElementById('messages').appendChild(wsDiv);
                        messagesDiv.scrollTop = messagesDiv.scrollHeight;
                        _srAnnounce('Recherche sur le web en cours…');
                    }
                    continue;
                }

                if (data.startsWith('[TOOL_LOADING]')) {
                    const toolName = data.slice('[TOOL_LOADING]'.length).trim();
                    const toolLabels = {
                        search_documents: '📄 Consultation de vos documents…',
                    };
                    const label = toolLabels[toolName] || '🔧 NIMM consulte un outil…';
                    if (!document.getElementById('tool-loading')) {
                        const tlDiv = document.createElement('div');
                        tlDiv.id        = 'tool-loading';
                        tlDiv.className = 'message assistant';
                        const tlEmoji = document.createElement('div');
                        tlEmoji.className = 'bubble-emoji';
                        tlEmoji.setAttribute('aria-hidden', 'true');
                        const tlBubble = document.createElement('div');
                        tlBubble.className = 'message-bubble web-search-loader';
                        tlBubble.innerHTML = '<span>' + label + '</span><span class="stt-dots"><span></span><span></span><span></span></span>';
                        tlDiv.appendChild(tlEmoji);
                        tlDiv.appendChild(tlBubble);
                        document.getElementById('messages').appendChild(tlDiv);
                        messagesDiv.scrollTop = messagesDiv.scrollHeight;
                        _srAnnounce(label);
                    }
                    continue;
                }

                if (data.startsWith('[VIBE_INACTIF]')) {
                    const vMsg = 'Mode Vibe inactif : sélectionne le LLM Mistral dans les réglages. Message envoyé en chat normal.';
                    if (typeof showToast === 'function') showToast(vMsg, 'warning');
                    _srAnnounce(vMsg);
                    continue;
                }

                if (data.startsWith('[VIBE_TOOL]')) {
                    try {
                        const vt = JSON.parse(data.slice(11));
                        const vLbl = (vt.label || vt.tool || 'Outil Vibe') + ' en cours…';
                        if (typeof showToast === 'function') showToast(vLbl, 'info');
                        _srAnnounce(vLbl);
                    } catch(e) {}
                    continue;
                }

                if (data.startsWith('[CITATIONS]')) {
                    try {
                        const cits = JSON.parse(data.slice(11));
                        if (Array.isArray(cits) && cits.length) {
                            _renderCitations(assistantDiv, cits);
                        }
                    } catch(e) {}
                    continue;
                }

                if (data.startsWith('[IMAGE_GEN_LOADING]')) {
                    // Bulle placeholder - bretzel agrandi + label
                    const plDiv = document.createElement('div');
                    plDiv.id        = 'img-gen-loader';
                    plDiv.className = 'message assistant';
                    const plEmoji = document.createElement('div');
                    plEmoji.className   = 'bubble-emoji';
                    plEmoji.setAttribute('aria-hidden', 'true');
                    plEmoji.textContent = '\u{1F3A8}';
                    const plBubble = document.createElement('div');
                    plBubble.className = 'message-bubble loader-bretzel';
                    plBubble.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:10px;padding:18px 24px;';
                    const plSvg = _buildBretzelSVG(80, 55);
                    const plLabel = document.createElement('span');
                    plLabel.textContent = 'G\u00e9n\u00e9ration en cours\u2026';
                    plLabel.style.cssText = 'font-size:0.8rem;color:var(--text-muted);';
                    plBubble.appendChild(plSvg);
                    plBubble.appendChild(plLabel);
                    plDiv.appendChild(plEmoji);
                    plDiv.appendChild(plBubble);
                    document.getElementById('messages').appendChild(plDiv);
                    messagesDiv.scrollTop = messagesDiv.scrollHeight;
                    requestAnimationFrame(() => _startBretzelAnim(plSvg, plDiv));
                    continue;
                }

                if (data.startsWith('[IMAGE_GEN]')) {
                    try {
                        const img = JSON.parse(data.slice(11));
                        const src = img.url ? img.url : `data:image/png;base64,${img.b64}`;
                        const displayPrompt = (img.revised_prompt && img.revised_prompt !== img.prompt)
                            ? img.revised_prompt : img.prompt;
                        // Remplacer le placeholder si présent, sinon créer une nouvelle bulle
                        const placeholder = document.getElementById('img-gen-loader');
                        if (placeholder?._cancelAnim) placeholder._cancelAnim();
                        const imgDiv = placeholder || document.createElement('div');
                        imgDiv.removeAttribute('id');
                        imgDiv.className = 'message assistant';
                        imgDiv.innerHTML = '';
                        const imgEmoji = document.createElement('div');
                        imgEmoji.className   = 'bubble-emoji';
                        imgEmoji.setAttribute('aria-hidden', 'true');
                        imgEmoji.textContent = '🎨';
                        const imgBubble = document.createElement('div');
                        imgBubble.className = 'message-bubble';
                        const imgB64 = img.b64 || '';
                        // Image rechargée depuis l'historique : la description n'est pas conservée
                        // avec le message. On ne la redemande PAS d'office — ce serait un appel
                        // de vision par image à chaque ouverture du fil — mais on ne fait pas
                        // passer la consigne pour une description : on dit ce qu'elle est, et
                        // le bouton « Décrire » la produit à la demande.
                        const _altHist = 'Image générée. Consigne d\'origine : '
                            + (img.prompt || '(inconnue)') + '. Pas de description enregistrée.';
                        imgBubble.innerHTML = `<img src="${src}" alt="${_esc(_altHist)}" style="max-width:100%;border-radius:10px;display:block;margin-bottom:8px;"><span style="font-size:0.8rem;color:var(--text-muted);">${_esc(displayPrompt)}</span><br><div style="display:flex;gap:8px;margin-top:8px;"><button class="img-download-btn" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;" aria-label="Télécharger l'image">⬇ Télécharger</button><button class="img-describe-btn" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;" aria-label="Décrire cette image">🔎 Décrire</button><button class="img-edit-btn" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;" aria-label="Modifier l'image">✏️ Modifier</button></div>`;
                        imgBubble.querySelector('.img-download-btn').addEventListener('click', async () => {
                            try {
                                const resp = await fetch(src);
                                const blob = await resp.blob();
                                const a = document.createElement('a');
                                a.href = URL.createObjectURL(blob);
                                a.download = 'nimm-image.png';
                                a.click();
                                URL.revokeObjectURL(a.href);
                            } catch(e) {
                                const a = document.createElement('a');
                                a.href = src; a.download = 'nimm-image.png'; a.target = '_blank'; a.click();
                            }
                        });
                        imgBubble.querySelector('.img-edit-btn').addEventListener('click', () => {
                            openImageEditModal(imgB64, img.prompt || '');
                        });
                        imgBubble.querySelector('.img-describe-btn')?.addEventListener('click', async function () {
                            this.disabled = true;
                            this.textContent = '🔎 Description…';
                            await _decrireImageGeneree(imgBubble, imgB64, imgB64 ? '' : src,
                                                       img.prompt || '');
                            this.remove();
                        });
                        imgDiv.appendChild(imgEmoji);
                        imgDiv.appendChild(imgBubble);
                        if (!placeholder) document.getElementById('messages').appendChild(imgDiv);
                        messagesDiv.scrollTop = messagesDiv.scrollHeight;
                        // Sauvegarde automatique en arrière-plan
                        (async () => {
                            try {
                                const saveResp = await fetch('/api/images/save', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        b64:       imgB64,
                                        url:       img.url || '',
                                        prompt:    img.prompt || '',
                                        thread_id: currentTabId || currentThreadId || '',
                                    })
                                });
                                if (saveResp.ok) {
                                    const saved = await saveResp.json();
                                    imgDiv.dataset.imgId = saved.id;
                                    imgDiv.dataset.imgFilename = saved.filename;
                                    console.log('[NIMM] Image sauvegardee :', saved.filename);
                                }
                            } catch(e) { console.warn('[NIMM] Sauvegarde image echouee :', e); }
                        })();
                    } catch(e) { console.error('[NIMM] Erreur rendu image generee :', e); }
                    continue;
                }

                if (data.startsWith('[IMAGE_GEN_ERR]')) {
                    const placeholder = document.getElementById('img-gen-loader');
                    if (placeholder?._cancelAnim) placeholder._cancelAnim();
                    placeholder?.remove();
                    const errMsg = data.slice(15);
                    appendAssistantMessage(`\u274c Erreur g\u00e9n\u00e9ration image : ${errMsg}`);
                    continue;
                }

                if (data.startsWith('[USAGE]')) {
                    try {
                        const usage = JSON.parse(data.slice(7));
                        const tid = currentTabId || currentThreadId;
                        if (tid && (usage.cost_eur || 0) > 0) {
                            _threadCostMap.set(tid, (_threadCostMap.get(tid) || 0) + (usage.cost_eur || 0));
                            _updateThreadCostBadge(tid);
                        }
                    } catch(e) { /* silencieux */ }
                    continue;
                }
                if (data.startsWith('[PROVIDER_SWITCH:')) {
                    const p = data.slice(17).replace(']','');
                    const labels = {mistral:'Mistral',gemini:'Gemini',anthropic:'Claude'};
                    _notify('🔀 Recherche web via ' + (labels[p] || p), 'info');
                    continue;
                }

                                document.getElementById('web-search-loader')?.remove();
                                document.getElementById('tool-loading')?.remove();
                                fullText += data.replace(/\\n/g, '\n');
                const cleaned = fullText
                    .replace(/%%DOMINANT:[^%]+%%/g, '')
                    .replace(/%%MEM:[^%]+%%/g, '')
                    .replace(/%%QUIZ%%([\s\S]*?)%%\/QUIZ%%/g, '')
                    .replace(/%%QUIZ_BILAN%%([\s\S]*?)%%\/QUIZ_BILAN%%/g, '')
                    .replace(/%%QUIZ%%[\s\S]*$/, '')
                    .replace(/\{[^{}]*"type"\s*:\s*"(?:qcm|vf)"[^{}]*\}/g, '')
                    .replace(/\{[^{}]*"type"\s*:\s*"(?:qcm|vf)[\s\S]*$/, '');
                const displayText = cleaned.replace(/%%[^%]*$/, '').trimEnd();
                // Rendu progressif par paragraphes avec effet scramble
                _flushRenderedParagraphs(displayText, false);
                // Scroll automatique — suspendu si l'utilisateur a scrollé manuellement
                if (!_userScrolledUp) {
                    const allUserMsgs = messagesDiv.querySelectorAll('.message.user');
                    const lastUser = allUserMsgs[allUserMsgs.length - 1];
                    const target = messagesDiv.scrollHeight - messagesDiv.clientHeight;
                    if (lastUser) {
                        const maxScroll = lastUser.offsetTop + lastUser.offsetHeight - 72;
                        messagesDiv.scrollTop = Math.min(target, maxScroll);
                    } else {
                        messagesDiv.scrollTop = target;
                    }
                }

                if (_autoTTS && data) {
                    const ttsData = data
                        .replace(/\\n/g, ' ')
                        .replace(/%%[^%]*%%/g, '')
                        .replace(/%%[^%]*$/, '');
                    _ttsStreamBuf += ttsData;
                    const m = _ttsStreamBuf.match(/^(.*?[.!?…])\s+([\s\S]*)$/);
                    if (m) {
                        const floatBtn = document.getElementById('float-tts-btn');
                        _ttsPush(m[1].trim(), floatBtn);
                        _ttsStreamBuf = m[2];
                    }
                }
            }
        }

        // Rendu final — injecte les cartes quiz si présentes
        _stopScramble();
        // Vider les stream-para provisoires avant que _renderBubble réécrive la bulle
        bubble.innerHTML = '';
        _renderBubble(bubble, fullText);
        bubble.dataset.rawText = fullText; // conservé pour continuation
        if (!_userScrolledUp) messagesDiv.scrollTop = messagesDiv.scrollHeight;
        const finalContent = bubble.textContent;
        _updateFloatTTS(finalContent, div);
        const _plan = _planDeLaReponse(bubble);
        _srAnnounce(_plan ? `NIMM t'a répondu — ${_plan}` : "NIMM t'a répondu.");
        
        // GARDE-FOU : un flux qui se termine SANS texte ne doit jamais passer
        // pour une réponse. La synthèse vocale annonce « NIMM t'a répondu »,
        // les indicateurs d'outil restent affichés, et il n'y a rien à écouter.
        // Ce contrôle est ici, au plus près de l'affichage : il vaut quelle que
        // soit la cause côté serveur, y compris celles qu'on n'a pas encore vues.
        if (!finalContent.trim()) {
            document.getElementById('web-search-loader')?.remove();
            document.getElementById('tool-loading')?.remove();
            const _vide = "Aucune réponse n'est revenue après la consultation des outils. "
                + "Reformule ta question, ou relance-la sans la recherche web. "
                + "Le journal de fonctionnement en dit peut-être la raison.";
            bubble.textContent = _vide;
            _srAnnounce(_vide);
        }

        // Bouton Continuer si réponse tronquée (max_tokens)
        if (_streamRaisonnement) {
            _ajouterRaisonnement(bubble, _streamRaisonnement);
            _streamRaisonnement = '';
        }
        if (_streamTruncated) {
            _streamTruncated = false;
            addContinueButton(div, conversationId);
            _srAnnounce("Réponse interrompue : elle a atteint la limite de longueur. "
                      + "Un bouton Continuer est disponible en fin de message.");
        }

        // Brancher le bouton TTS individuel de cette bulle
        streamTtsBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            playTTS(finalContent, streamTtsBtn);
        });

        actMenu.querySelector('[data-action="copy"]').addEventListener('click', () => {
        _copyToClipboard(finalContent).then(() => {
                actBtn.innerHTML = '✓';
                setTimeout(() => actBtn.innerHTML = SVG_ACT, 1500);
            });
            actMenu.style.display = 'none'; actBtn.focus();
        });
        actMenu.querySelector('[data-action="tab"]').addEventListener('click', () => {
            sendToNewTab(finalContent);
            actMenu.style.display = 'none'; actBtn.focus();
        });
        actMenu.querySelector('[data-action="regen"]').addEventListener('click', () => {
            actMenu.style.display = 'none'; actBtn.focus();
            regenerateMessage(div, conversationId);
        });
        actMenu.querySelector('[data-action="fork"]').addEventListener('click', () => {
            actMenu.style.display = 'none'; actBtn.focus();
            forkFromMessage(div, conversationId);
        });
        actMenu.querySelector('[data-action="mark"]').addEventListener('click', () => {
            actMenu.style.display = 'none'; actBtn.focus();
            _toggleExportMark(div, finalContent, 'assistant');
            const btn = actMenu.querySelector('[data-action="mark"]');
            btn.textContent = div.dataset.exportMarked ? '★ Marqué' : '⭐ Marquer pour export';
        });

        { const _v = actMenu.querySelector('[data-action="verify"]');
          if (_v) _v.hidden = !_cleDisponible('anthropic'); }
        actMenu.querySelector('[data-action="verify"]')?.addEventListener('click', () => {
            actMenu.style.display = 'none'; actBtn.focus();
            _verifierReponse(bubble?.dataset.rawText || bubble?.textContent || '', bubble);
        });

        // Appliquer l'expression finale
        stopBlink();
        _blinkEmojiEl = emoji;
        _setWebSearch(false); // eteint l'aura apres reponse
        _bip(520, 80); // bip aigu : réponse terminée
        _blinkSchedule = setTimeout(() => startBlink(dominant, moodScore), 300);

        if (_autoTTS && _ttsStreamBuf.trim()) {
            const floatBtn = document.getElementById('float-tts-btn');
            _ttsPush(_ttsStreamBuf.trim(), floatBtn);
            _ttsStreamBuf = '';
        }

        // Reset bouton Stop
        const _stopBtnOk = document.getElementById('stop-btn');
        const _sendBtnOk = document.getElementById('send-btn');
        if (_stopBtnOk) _stopBtnOk.hidden = true;
        if (_sendBtnOk) _sendBtnOk.hidden = false;
        _streamAbortController = null;

        // Auto-titre : si le fil a encore son nom provisoire, le générer maintenant
        if (!currentTabId) {
            const _autoTitleThread = threads.find(t => t.thread_id === conversationId);
            if (_autoTitleThread && _autoTitleThread.name === '💬 Nouveau fil') {
                fetch(`/api/threads/${conversationId}/title`, {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({ content })
                }).then(r => r.json()).then(data => {
                    if (data.name) {
                        const t = threads.find(t => t.thread_id === conversationId);
                        if (t) {
                            t.name = data.name;
                            renderSidebar();
                            if (currentThreadId === conversationId) {
                                const ml = document.getElementById('mobile-thread-label');
                                if (ml) ml.textContent = data.name;
                            }
                        }
                    }
                }).catch(() => {});
            }
        }

    } catch(e) {
        // Reset stop/send buttons
        const _stopBtn = document.getElementById('stop-btn');
        const _sendBtn = document.getElementById('send-btn');
        if (_stopBtn) _stopBtn.hidden = true;
        if (_sendBtn) _sendBtn.hidden = false;
        _streamAbortController = null;

        if (e.name === 'AbortError') {
            // Arrêt volontaire — on retire le loader proprement sans message d'erreur
            removeLoader();
            return;
        }
        removeLoader();
        // TypeError = le fetch lui-même a échoué (réseau coupé, serveur injoignable)
        if (e instanceof TypeError) {
            _notifyServiceError(0);
            appendAssistantMessage('❌ Connexion impossible au serveur.', 'neutre', false);
            _srAnnounce('Connexion impossible au serveur.');
        } else {
            // Erreur HTTP : le toast a déjà été affiché par _notifyServiceError
            appendAssistantMessage(`❌ Le fournisseur n'a pas pu répondre.`, 'neutre', false);
            _srAnnounce(`Le fournisseur n'a pas pu répondre.`);
        }
        console.error('[NIMM] Erreur stream :', e);
    }
}

async function editLastUserMessage(userDiv, conversationId) {
    const tid = conversationId || currentTabId || currentThreadId;
    if (!tid) return;

    // Récupérer le texte du message
    const bubble = userDiv.querySelector('.message-bubble');
    if (!bubble) return;
    const content = bubble.textContent.trim();

    // Supprimer la paire (user + assistant suivant) en DB
    await fetch(`/api/chat/${tid}/last_pair`, { method: 'DELETE' }).catch(() => {});

    // Retirer depuis le DOM : bulle user + bulle assistant suivante
    const nextSibling = userDiv.nextElementSibling;
    if (nextSibling && nextSibling.classList.contains('message') && nextSibling.classList.contains('assistant')) {
        nextSibling.remove();
    }
    userDiv.remove();

    // Remettre le contenu dans le champ de saisie
    userInput.value = content;
    userInput.style.height = 'auto';
    userInput.style.height = userInput.scrollHeight + 'px';
    userInput.focus();
}

async function regenerateMessage(assistantDiv, conversationId) {
    const tid = conversationId || currentTabId || currentThreadId;

    // Récupérer le dernier message utilisateur depuis le DOM
    const userBubbles = messagesDiv.querySelectorAll('.message.user .message-bubble');
    if (!userBubbles.length) return;
    const lastUserContent = userBubbles[userBubbles.length - 1].textContent.trim();

    // Supprimer le dernier message assistant en DB
    if (tid) await fetch(`/api/chat/${tid}/last_assistant`, { method: 'DELETE' }).catch(() => {});

    // Retirer la bulle assistant courante
    assistantDiv.remove();

    // Relancer le stream sur le même message utilisateur
    await _triggerStream(lastUserContent, tid);
}

// ══════════════════════════════════════════
// EXPORT — marquage + génération de fichiers
// ══════════════════════════════════════════

let _exportItems = []; // [{div, role, content}]
let _streamAbortController = null; // AbortController du stream en cours
let _msgCounter = 0;               // Index DOM des messages (pour fork)

function _toggleExportMark(div, content, role) {
    const idx = _exportItems.findIndex(i => i.div === div);
    if (idx >= 0) {
        _exportItems.splice(idx, 1);
        delete div.dataset.exportMarked;
        div.style.outline = '';
    } else {
        _exportItems.push({ div, role, content });
        div.dataset.exportMarked = '1';
        div.style.outline = '2px solid var(--accent, #6ea8fe)';
    }
    _updateExportBadge();
}

function _updateExportBadge() {
    const btn = document.getElementById('export-float-btn');
    if (!btn) return;
    if (_exportItems.length > 0) {
        btn.textContent = `📤 Exporter (${_exportItems.length})`;
        btn.style.display = 'flex';
    } else {
        btn.style.display = 'none';
    }
}

function openExportModal() {
    const modal = document.getElementById('export-modal');
    modal.dataset.prevFocus = null;
    modal.closest('.modal-overlay').__prevFocus = document.activeElement;
    modal.classList.remove('hidden');
    document.getElementById('export-count').textContent =
        `${_exportItems.length} message${_exportItems.length > 1 ? 's' : ''} marqué${_exportItems.length > 1 ? 's' : ''}.`;
    document.getElementById('export-status').textContent = '';
    document.getElementById('export-do-btn').disabled = false;
    modal.querySelector('.close-modal').focus();
}

async function doExport(format) {
    if (_exportItems.length === 0) return;
    const items = _exportItems.map(i => ({ role: i.role, content: i.content }));
    const btn = document.getElementById('export-do-btn');
    const status = document.getElementById('export-status');
    btn.disabled = true;
    status.textContent = 'Génération en cours…';
    try {
        const r = await fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items, format }),
        });
        if (!r.ok) throw new Error(await r.text());
        const blob = await r.blob();
        const disposition = r.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^";]+)"?/);
        const filename = match ? match[1] : `export_nimm.${format}`;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = filename; a.click();
        URL.revokeObjectURL(url);
        status.textContent = `Fichier "${filename}" téléchargé.`;
    } catch (e) {
        status.textContent = `Erreur : ${e.message}`;
    } finally {
        btn.disabled = false;
    }
}

// ── Stop stream ──
function stopStream() {
    _streamAbortController?.abort();
}

// ── Continuation automatique (réponse tronquée par max_tokens) ──
function addContinueButton(assistantDiv, conversationId) {
    const bubble = assistantDiv.querySelector('.message-bubble');
    if (!bubble) return;
    const btn = document.createElement('button');
    btn.className = 'continue-btn';
    btn.textContent = 'Continuer ▶';
    btn.setAttribute('aria-label', 'Continuer la réponse');
    btn.style.cssText = 'display:inline-block;margin-top:8px;background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:3px 12px;cursor:pointer;color:var(--text-muted);font-size:0.82rem;';
    btn.addEventListener('click', () => continueLastMessage(assistantDiv, conversationId));
    bubble.appendChild(btn);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

async function continueLastMessage(assistantDiv, conversationId) {
    const tid = conversationId || currentTabId || currentThreadId;
    if (!tid) return;
    const bubble = assistantDiv.querySelector('.message-bubble');
    if (!bubble) return;

    // Retirer le bouton
    bubble.querySelector('.continue-btn')?.remove();

    // Curseur clignotant pendant la continuation
    const cursor = document.createElement('span');
    cursor.textContent = ' ▌';
    cursor.setAttribute('aria-hidden', 'true');
    bubble.appendChild(cursor);

    _streamAbortController = new AbortController();
    const stopBtn = document.getElementById('stop-btn');
    const sendBtn = document.getElementById('send-btn');
    if (stopBtn) { stopBtn.hidden = false; stopBtn.onclick = stopStream; }
    if (sendBtn) sendBtn.hidden = true;

    let accumulated = '';
    let truncated   = false;

    try {
        const r = await fetch(`/api/chat/${tid}/continue`, {
            method: 'POST',
            signal: _streamAbortController.signal,
        });
        if (!r.ok) {
            const _status = r.status;
            _notifyServiceError(_status);
            throw new Error(`HTTP ${_status}`);
        }

        const reader  = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);
                if (data === '[DONE]') break;
                if (data === '[TRUNCATED]') { truncated = true; continue; }
                if (data.startsWith('[') ) continue; // [META], [ERREUR], [IMAGE…]
                accumulated += data.replace(/\\n/g, '\n');
            }
        }
    } catch(e) {
        cursor.remove();
        if (e.name !== 'AbortError') {
            const errSpan = document.createElement('em');
            errSpan.style.color = 'var(--text-muted)';
            errSpan.textContent = ' [Erreur de continuation]';
            bubble.appendChild(errSpan);
        }
        _streamAbortController = null;
        if (stopBtn) stopBtn.hidden = true;
        if (sendBtn) sendBtn.hidden = false;
        return;
    }

    cursor.remove();

    // Re-render avec le texte complet (original + continuation)
    if (accumulated) {
        const prevRaw = bubble.dataset.rawText || '';
        const newRaw  = prevRaw + accumulated;
        bubble.innerHTML = '';
        _renderBubble(bubble, newRaw);
        bubble.dataset.rawText = newRaw;
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    _streamAbortController = null;
    if (stopBtn) stopBtn.hidden = true;
    if (sendBtn) sendBtn.hidden = false;

    if (truncated) {
        addContinueButton(assistantDiv, conversationId);
    }
}

// ── Fork depuis un message assistant ──
async function forkFromMessage(div, conversationId) {
    const idx = parseInt(div.dataset.msgIndex ?? '-1');
    if (idx < 0 || !conversationId) return;

    try {
        const r = await fetch(`/api/chat/${conversationId}/fork`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ up_to: idx }),
        });
        if (!r.ok) throw new Error(await r.text());
        const { thread_id, name } = await r.json();
        // Charger le nouveau fil
        await loadThreads();
        await selectThread(thread_id);
        _srAnnounce(`Nouveau fil fork : ${name}`);
    } catch(e) {
        console.error('[NIMM] Fork error:', e);
        alert('Erreur lors du fork : ' + e.message);
    }
}

// ── Résumé à la demande ──
async function requestSummary(conversationId) {
    const tid = conversationId || currentTabId || currentThreadId;
    if (!tid) return;
    const btn = document.getElementById('summary-btn');
    const banner = document.getElementById('summary-banner');
    const textEl = document.getElementById('summary-text');
    if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
    try {
        const r = await fetch(`/api/threads/${tid}/summary`, { method: 'POST' });
        if (!r.ok) throw new Error(await r.text());
        const { summary } = await r.json();
        textEl.textContent = summary;
        banner.hidden = false;
        banner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        _srAnnounce('Résumé disponible : ' + summary);
    } catch(e) {
        textEl.textContent = 'Erreur : ' + e.message;
        banner.hidden = false;
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '📋'; }
    }
}

// ══════════════════════════════════════════
// ENVOI MESSAGE
// ══════════════════════════════════════════

async function sendMessage() {
    const content = userInput.value.trim();
    if (!content && !_pendingFile && !_pendingVibeDoc) return;
    if (!(await _ensureUnlocked(_currentUserId))) return;  // session a PIN : deverrouiller avant d'ecrire

    userInput.value = '';
    userInput.style.height = '44px';
    _clearDraft();

    let conversationId = currentTabId || currentThreadId;
    if (!conversationId) {
        await createThread('💬 Nouveau fil');
        conversationId = currentTabId || currentThreadId;
        if (!conversationId) return;
    }

    // Détection préfixe image 🖼️
    if (content.startsWith('🖼️ ')) {
        const prompt = content.slice('🖼️ '.length).trim();
        if (!prompt) return;
        appendUserMessage('🖼️ ' + prompt);
        showLoader();
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        try {
            const r = await fetch('/api/image/generate', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ prompt }),
            });
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${r.status}`);
            }
            const data         = await r.json();
            const src          = data.url ? data.url : `data:image/png;base64,${data.b64}`;
            const revisedPrompt = data.revised_prompt || '';
            removeLoader();
            const div    = document.createElement('div');
            div.className = 'message assistant';
            const emojiEl = document.createElement('div');
            emojiEl.className   = 'bubble-emoji';
            emojiEl.setAttribute('aria-hidden', 'true');
            emojiEl.textContent = '🎨';
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            const promptLabel = revisedPrompt && revisedPrompt !== prompt
                ? `<span style="font-size:0.8rem;color:var(--text-muted);">${revisedPrompt}</span>`
                : `<span style="font-size:0.8rem;color:var(--text-muted);">${_esc(prompt)}</span>`;
            const editB64 = data.b64 || '';
            // L'alt ne reprend PLUS la consigne : dire ce qu'on a demandé à la
            // place de ce qui a été produit, c'est un texte alternatif qui ment
            // dès que le modèle dérive. On pose un alt provisoire honnête, puis
            // on le remplace par la vraie description dès qu'elle arrive.
            bubble.innerHTML = `<img src="${src}" alt="Image générée, description en cours…" style="max-width:100%;border-radius:10px;display:block;margin-bottom:8px;">${promptLabel}<br><div style="display:flex;gap:8px;margin-top:8px;"><button class="img-download-btn" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;" aria-label="Télécharger l'image">⬇ Télécharger</button><button class="img-edit-btn" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;" aria-label="Modifier l'image">✏️ Modifier</button></div>`;
            bubble.querySelector('.img-download-btn').addEventListener('click', async () => {
                try {
                    const resp = await fetch(src);
                    const blob = await resp.blob();
                    const a    = document.createElement('a');
                    a.href     = URL.createObjectURL(blob);
                    a.download = 'nimm-image.png';
                    a.click();
                    URL.revokeObjectURL(a.href);
                } catch(e) {
                    const a    = document.createElement('a');
                    a.href     = src;
                    a.download = 'nimm-image.png';
                    a.target   = '_blank';
                    a.click();
                }
            });
            bubble.querySelector('.img-edit-btn').addEventListener('click', () => {
                openImageEditModal(editB64, prompt);
            });

            // Description accessible, hors du chemin critique (voir _decrireImageGeneree).
            _decrireImageGeneree(bubble, data.b64 || '', data.url || '', prompt);
            div.appendChild(emojiEl);
            div.appendChild(bubble);
            document.getElementById('messages').appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            // Sauvegarde automatique galerie
            (async () => {
                try {
                    const saveResp = await fetch('/api/images/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            b64:       data.b64 || '',
                            url:       data.url || '',
                            prompt:    prompt,
                            thread_id: conversationId || '',
                        })
                    });
                    if (saveResp.ok) {
                        const saved = await saveResp.json();
                        div.dataset.imgId = saved.id;
                        div.dataset.imgFilename = saved.filename;
                        console.log('[NIMM] Image sauvegardee :', saved.filename);
                    }
                } catch(e) { console.warn('[NIMM] Sauvegarde image echouee :', e); }
            })();
            // Sauvegarder en DB pour que le LLM voit l'image dans l'historique
            const _tid = conversationId;
            const _assistantContent = revisedPrompt
                ? `🎨 Image générée.\nPrompt utilisé : ${revisedPrompt}`
                : `🎨 Image générée.\nPrompt : ${prompt}`;
            fetch(`/api/threads/${_tid}/messages`, {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({role:'user', content:'🖼️ ' + prompt})
            }).catch(()=>{});
            fetch(`/api/threads/${_tid}/messages`, {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({role:'assistant', content: _assistantContent})
            }).catch(()=>{});
        } catch(e) {
            removeLoader();
            appendAssistantMessage(`❌ Erreur génération image : ${e.message}`);
        }
        return; // ne pas continuer vers le chat
    }

    const pendingFile = _pendingFile;
    const pendingVibeDoc = _pendingVibeDoc;
    appendUserMessage(content, (pendingFile && pendingFile.name) || (pendingVibeDoc && pendingVibeDoc.name) || null);
    _pendingFile = null;
    _pendingVibeDoc = null;
    document.getElementById('file-chip').style.display = 'none';
    // Scroll initial à l'envoi — montre le bas du fil
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    let _vibeDocsPayload = null;
    if (pendingVibeDoc && pendingVibeDoc.file_id) {
        _vibeDocsPayload = [{ file_id: pendingVibeDoc.file_id, name: pendingVibeDoc.name }];
        _vibeSentDocs.push(pendingVibeDoc.file_id);
    }
    await _triggerStream(
        pendingFile ? content + '\n\n' + pendingFile.text : content,
        conversationId,
        null,
        _vibeDocsPayload
    );
}

// ══════════════════════════════════════════
// ÉVÉNEMENTS SAISIE
// ══════════════════════════════════════════

sendBtn.addEventListener('click', sendMessage);

// ── Bouton Stop ──
document.getElementById('stop-btn')?.addEventListener('click', stopStream);

// ── Bouton Résumé ──
document.getElementById('summary-btn')?.addEventListener('click', () => {
    requestSummary(currentTabId || currentThreadId);
});
document.getElementById('summary-close')?.addEventListener('click', () => {
    document.getElementById('summary-banner').hidden = true;
});

// ══════════════════════════════════════════
// RACCOURCIS CLAVIER GLOBAUX
// ══════════════════════════════════════════

document.addEventListener('keydown', (e) => {
    // Ctrl+Entrée → envoyer (depuis n'importe où, y compris le textarea)
    if (e.ctrlKey && !e.altKey && e.key === 'Enter') {
        if (document.activeElement?.id === 'coanimm-consigne') return;
        e.preventDefault();
        sendMessage();
        return;
    }
    // Alt+lettre → actions (uniquement si le focus n'est pas dans un champ de saisie)
    const inField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)
        || document.activeElement?.isContentEditable;
    // Alt+N : toujours accessible même depuis un champ de saisie
    if (e.altKey && !e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        document.getElementById('new-thread-btn')?.click();
        return;
    }
    if (e.altKey && !e.ctrlKey && !e.shiftKey && !inField) {
        switch (e.key.toLowerCase()) {
            case 'r': {   // Alt+R : régénérer le dernier message assistant
                e.preventDefault();
                const lastAssist = [...messagesDiv.querySelectorAll('.message.assistant')].pop();
                if (lastAssist) regenerateMessage(lastAssist, currentTabId || currentThreadId);
                break;
            }
            case 's': {   // Alt+S : résumé du fil
                e.preventDefault();
                requestSummary(currentTabId || currentThreadId);
                break;
            }
            case 'e': {   // Alt+E : ouvrir le modal export
                e.preventDefault();
                openExportModal();
                break;
            }
            case 'o': {   // Alt+O : nouvel onglet
                e.preventDefault();
                document.getElementById('new-tab-btn')?.click();
                break;
            }
            case 'l': {   // Alt+L : lecture automatique
                e.preventDefault();
                document.getElementById('autotts-toggle')?.click();
                break;
            }
            // Alt+F est LIBRE : il servait au mode fantôme, puis brièvement à
            // la conversation Live. Celle-ci a rejoint la famille Alt+Maj,
            // où vivent tous les panneaux — c'est plus cohérent, et Alt+F
            // seul entrait en concurrence avec les raccourcis du navigateur.
        }
    }
});

// ══════════════════════════════════════════
// BROUILLON AUTOSAUVEGARDÉ
// ══════════════════════════════════════════

const _DRAFT_KEY = 'nimm_draft';

    function _saveDraft() {
        const val = userInput.value;
        if (val.trim()) {
            localStorage.setItem(_DRAFT_KEY, val);
        } else {
            localStorage.removeItem(_DRAFT_KEY);
            _hideDraftIndicator();
        }
    }

function _clearDraft() {
    localStorage.removeItem(_DRAFT_KEY);
    _hideDraftIndicator();
}

function _restoreDraft() {
    const saved = localStorage.getItem(_DRAFT_KEY);
    if (saved && !userInput.value.trim()) {
        userInput.value = saved;
        userInput.style.height = '44px';
        userInput.style.height = Math.min(userInput.scrollHeight, 240) + 'px';
        _showDraftIndicator('Brouillon restauré');
        setTimeout(_hideDraftIndicator, 3000);
    }
}

function _showDraftIndicator(text) {
    const el = document.getElementById('draft-indicator');
    if (el) { el.textContent = text; el.hidden = false; }
}

function _hideDraftIndicator() {
    const el = document.getElementById('draft-indicator');
    if (el) el.hidden = true;
}

// Restaurer le brouillon au démarrage
_restoreDraft();

userInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        if (isMobile()) return; // mobile : Enter = saut de ligne, envoi via bouton uniquement
        e.preventDefault();
        sendMessage();
    }
});

userInput.addEventListener('input', () => {
    userInput.style.height = '44px';
    userInput.style.height = Math.min(userInput.scrollHeight, 240) + 'px';
    // Masquer le bouton ↩️ dès que l'utilisateur tape au clavier
    const nlBtn = document.getElementById('newline-btn');
    if (nlBtn && !nlBtn.dataset.sttOnly) {
        nlBtn.classList.add('hidden');
    }
    // Autosauvegarde du brouillon
    _saveDraft();
});

// ══════════════════════════════════════════
// PARAMÈTRES
// ══════════════════════════════════════════

async function loadVoices() {
    const select = document.getElementById('voice-select');
    if (!select) return;
    try {
        const r    = await fetch('/api/tts/voices');
        const data = await r.json();
        select.innerHTML = '';
        (data.voices || []).forEach(v => {
            const opt = document.createElement('option');
            opt.value       = v.id;
            opt.textContent = v.label;
            if (v.id === _selectedVoice) opt.selected = true;
            select.appendChild(opt);
        });
    } catch(e) {
        console.error('[TTS] Erreur chargement voix :', e);
    }
}

document.getElementById('preview-voice-btn')?.addEventListener('click', async () => {
    const select = document.getElementById('voice-select');
    const btn    = document.getElementById('preview-voice-btn');
    if (!select || !btn) return;
    const voice = select.value;
    btn.innerHTML = SVG_LOADING;
    btn.disabled    = true;
    try {
        const r = await fetch('/api/tts/speak', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ text: "Bonjour, je suis NIMM. Je parle, j'écoute, et j'ai une mémoire d'éléphant — ce qui est plutôt rare pour un logiciel.", voice })
        });
        if (!r.ok) throw new Error();
        const blob  = await r.blob();
        const url   = URL.createObjectURL(blob);
        const audio = new Audio(url);
        const reset = () => { btn.innerHTML = '▶ Écouter'; btn.disabled = false; URL.revokeObjectURL(url); };
        audio.onended = reset;
        audio.onerror = reset;
        const p = audio.play();
        if (p) p.catch(reset);
    } catch(e) {
        btn.innerHTML = '▶ Écouter';
        btn.disabled    = false;
    }
});

// ── Visibilité des options Gemini TTS ──
function _updateGeminiTtsVisibility(hasGeminiKey) {
    const rows = document.getElementById('gemini-tts-rows');
    if (rows) rows.style.display = hasGeminiKey ? '' : 'none';
}

// ── Grisage options routing selon clés configurées ──
function _updatePixtralModelVisibility(visionProvider) {
    const row = document.getElementById('pixtral-model-row');
    if (row) row.style.display = visionProvider === 'mistral' ? '' : 'none';
}

// Clés réellement configurées, mémorisées pour les éléments construits à la volée.
let _clesConfigurees = {};

function _cleDisponible(nom) {
    return !!(_clesConfigurees[nom] || _clesConfigurees[String(nom).replace('-', '_')]);
}

// Règle unique pour TOUTE l'interface : un élément portant data-needs-key n'a de
// sens que si la clé correspondante existe. Une option de liste est GRISÉE (la
// liste garde ses entrées, et l'on comprend pourquoi elle est indisponible) ;
// tout le reste est MASQUÉ — exposer un panneau inutilisable allonge le parcours
// au lecteur d'écran pour rien.
function _majVisibiliteParCle(keys) {
    _clesConfigurees = keys || {};
    document.querySelectorAll('option[data-needs-key]').forEach(opt => {
        const needed = opt.dataset.needsKey;
        opt.disabled = !_cleDisponible(needed);
        opt.title    = opt.disabled ? `Clé « ${needed} » non configurée` : '';
    });
    document.querySelectorAll('[data-needs-key]:not(option)').forEach(el => {
        el.hidden = !_cleDisponible(el.dataset.needsKey);
    });
    document.querySelectorAll('select').forEach(sel => {
        const cur = sel.options[sel.selectedIndex];
        if (cur && cur.disabled) {
            const premier = Array.from(sel.options).find(o => !o.disabled);
            if (premier) sel.value = premier.value;
        }
    });
}

function _applyProviderConstraints(keys) {
    // Bouton Vibe visible uniquement si une clé Mistral est enregistrée.
    _refreshVibeButtonVisibility(keys);
    // Même règle pour la musique : la clé Gemini ouvre Lyria. Un bouton qui
    // mène à un refus n'a rien à faire dans la barre d'outils.
    var _btnMus = document.getElementById('toggle-musique');
    if (_btnMus) _btnMus.hidden = !(keys && keys.gemini);
    var _btnStudio = document.getElementById('plus-studio');
    if (_btnStudio) _btnStudio.hidden = !(keys && keys.gemini);
    _majVisibiliteParCle(keys);
    // 1. Désactiver les options sans clé
    document.querySelectorAll('.routing-select option[data-needs-key]').forEach(opt => {
        const needed  = opt.dataset.needsKey;
        const keyName = needed.replace('-', '_');
        const hasKey  = keys[keyName] || keys[needed];
        opt.disabled  = !hasKey;
        opt.title     = opt.disabled ? `Clé "${needed}" non configurée` : '';
    });

    // 2. Si l'option sélectionnée est maintenant grisée, choisir la première disponible
    document.querySelectorAll('.routing-select').forEach(sel => {
        const cur = sel.options[sel.selectedIndex];
        if (cur && cur.disabled) {
            const first = Array.from(sel.options).find(o => !o.disabled);
            if (first) sel.value = first.value;
        }
    });

    // 3. Avertissement visible si le provider actif manque de clé
    const checks = [
        { selId: 'provider-select', warnId: 'warn-chat'   },
        { selId: 'routing-vision',  warnId: 'warn-vision'  },
        { selId: 'routing-image',   warnId: 'warn-image'   },
        { selId: 'routing-memory',  warnId: 'warn-memory'  },
        { selId: 'routing-titre',   warnId: 'warn-titre'   },
        { selId: 'routing-synthese', warnId: 'warn-synthese' },
        { selId: 'routing-coanimm',  warnId: 'warn-coanimm'  },
        { selId: 'routing-websearch', warnId: 'warn-websearch' },
    ];
    checks.forEach(({ selId, warnId }) => {
        const sel  = document.getElementById(selId);
        const warn = document.getElementById(warnId);
        if (!sel || !warn) return;
        const cur     = sel.options[sel.selectedIndex];
        const needKey = cur?.dataset?.needsKey;
        const keyName = needKey?.replace('-', '_');
        const missing = needKey && !(keys[keyName] || keys[needKey]);
        warn.classList.toggle('hidden', !missing);
        sel.classList.toggle('key-missing', !!missing);
    });
}

// ── Flash vert discret sur l'élément sauvegardé ──
function _autoSaveFlash(el) {
    if (!el) return;
    const prev = el.style.borderColor;
    el.style.transition = 'border-color 0.15s';
    el.style.borderColor = 'var(--accent)';
    setTimeout(() => { el.style.borderColor = prev; el.style.transition = ''; }, 700);
}

// ── Sauvegarde routing partiel (un seul champ modifié) ──
async function _saveRouting(field, value) {
    await fetch('/api/settings/routing', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ [field]: value })
    });
}

// ── Surveille l'état du modèle embeddings (loading → ready) ──
let _embeddingsWatchTimer = null;

function _watchEmbeddingsStatus() {
    clearInterval(_embeddingsWatchTimer);
    const toggle = document.getElementById('embeddings-toggle');
    const msg    = document.getElementById('embeddings-status-msg');
    if (!toggle || !toggle.checked) {
        if (msg) msg.textContent = '';
        return;
    }

    if (msg) msg.innerHTML = '⏳ Téléchargement en cours…';

    _embeddingsWatchTimer = setInterval(async () => {
        try {
            const r = await fetch('/api/embeddings/status');
            const d = await r.json();
            if (d.status === 'ready') {
                clearInterval(_embeddingsWatchTimer);
                _embeddingsWatchTimer = null;
                if (msg) msg.innerHTML = '<span style="color:var(--accent)">✅ Modèle prêt</span>';
            } else if (d.status === 'error') {
                clearInterval(_embeddingsWatchTimer);
                _embeddingsWatchTimer = null;
                const detail = d.detail || 'erreur inconnue';
                if (msg) msg.innerHTML = `<span style="color:#e05c5c">❌ Échec du chargement : ${detail}</span>`;
            } else if (d.status === 'disabled') {
                clearInterval(_embeddingsWatchTimer);
                _embeddingsWatchTimer = null;
                if (msg) msg.textContent = '';
            }
            // 'loading' → on continue de poller
        } catch(e) {
            clearInterval(_embeddingsWatchTimer);
            _embeddingsWatchTimer = null;
            if (msg) msg.innerHTML = '<span style="color:#e05c5c">❌ Impossible de joindre le serveur</span>';
        }
    }, 2000);
}

async function loadSettingsIntoUI() {
    try {
        const [prov, mask, len, keys, routing, masks] = await Promise.all([
            fetch('/api/settings/provider').then(r => r.json()),
            fetch('/api/settings/mask').then(r => r.json()),
            fetch('/api/settings/length').then(r => r.json()),
            fetch('/api/settings/api-keys').then(r => r.json()),
            fetch('/api/settings/routing').then(r => r.json()),
            fetch('/api/masks').then(r => r.json()).catch(() => []),
        ]);

        const provSel = document.getElementById('provider-select');
        if (provSel && routing.chat) provSel.value = routing.chat;
        else if (provSel && prov.provider) provSel.value = prov.provider;

        const maskSel = document.getElementById('mask-select');
        if (maskSel && Array.isArray(masks) && masks.length > 0) {
            maskSel.innerHTML = masks
                .map(m => `<option value="${m.id}">${m.label}</option>`)
                .join('');
        }
        if (maskSel && mask.mask_id) maskSel.value = mask.mask_id;

        const lenSel = document.getElementById('length-select');
        if (lenSel && len.value) lenSel.value = String(len.value);

        // Mettre à jour les sélecteurs de routing
        const visionSel = document.getElementById('routing-vision');
        if (visionSel && routing.vision) visionSel.value = routing.vision;
        _updatePixtralModelVisibility(routing.vision || '');
        try {
            const _pm = await fetch('/api/settings/pixtral-model').then(r => r.json());
            const pmSel = document.getElementById('pixtral-model-select');
            if (pmSel && _pm.model) pmSel.value = _pm.model;
        } catch(e) {}

        const imageSel = document.getElementById('routing-image');
        if (imageSel && routing.image) imageSel.value = routing.image;

        const memorySel = document.getElementById('routing-memory');
        if (memorySel) {
            const memProvider = routing.memoire?.provider;
            memorySel.value = memProvider || 'same';
        }

        const titreSel = document.getElementById('routing-titre');
        if (titreSel) {
            titreSel.value = routing.titre?.provider || 'same';
        }

        const syntheseSel = document.getElementById('routing-synthese');
        if (syntheseSel) {
            syntheseSel.value = routing.synthese?.provider || 'same';
        }

        const coanimmSel = document.getElementById('routing-coanimm');
        if (coanimmSel) {
            coanimmSel.value = routing.coanimm?.provider || 'same';
        }

        const websearchSel = document.getElementById('routing-websearch');
        if (websearchSel) {
            websearchSel.value = routing.web_search?.provider || 'same';
        }

        // Indiquer si les clés sont configurées
        _svcIds().forEach(p => {
            const el = document.getElementById(`api-key-${p.replace('_','-')}`);
            if (el) el.placeholder = keys[p] ? '✅ Configurée' : '❌ Non configurée';
        });

        // Grisage des options incompatibles selon clés présentes
        _applyProviderConstraints(keys);
        _checkProviderBanner();
        _checkBackupBanner();

        // Auto-sélection : si le chat n'est pas encore routé, choisir le premier provider disponible
        if (!routing.chat) {
            const chatProviders = ['anthropic','deepseek','gemini','openai','openrouter','mistral','groq','cerebras'];
            const firstAvailable = chatProviders.find(p => keys[p]);
            if (firstAvailable) {
                const provSel = document.getElementById('provider-select');
                if (provSel) {
                    provSel.value = firstAvailable;
                    await _saveRouting('chat', firstAvailable);
                }
            }
        }

        // Restaurer la police sélectionnée
        // Charger le modele sauvegarde et peupler le selecteur
        try {
            const modelData = await fetch('/api/settings/model').then(r => r.json());
            const currentProvider = document.getElementById('provider-select')?.value || 'deepseek';
            _populateModelSelect(currentProvider, modelData.model || null);
        } catch(e) {
            const currentProvider = document.getElementById('provider-select')?.value || 'deepseek';
            _populateModelSelect(currentProvider, null);
        }

        _initFontPicker();

        // Curseur présence
        try {
            const pres = await fetch('/api/settings/presence').then(r => r.json());
            const slider = document.getElementById('presence-slider');
            if (slider) {
                slider.value = pres.value ?? 0;
                _updatePresenceHint(slider.value);
            }
        } catch(e) {}

        // Curseur mémorisation
        try {
            const mem = await fetch('/api/settings/memoire-mode').then(r => r.json());
            const sel = document.getElementById('memoire-mode-select');
            if (sel && mem.value) sel.value = mem.value;
        } catch(e) {}

        // Potards — mode personnalité par curseurs
        _initPotards();

        // Surveiller l'état embeddings si activé
        _watchEmbeddingsStatus();

        // Options Gemini TTS (modèle + style + voix par défaut)
        try {
            const [gtm, gts, gtdv] = await Promise.all([
                fetch('/api/settings/gemini-tts-model').then(r => r.json()),
                fetch('/api/settings/gemini-tts-style').then(r => r.json()),
                fetch('/api/settings/gemini-tts-default-voice').then(r => r.json()),
            ]);
            const modelSel = document.getElementById('gemini-tts-model-select');
            if (modelSel && gtm.model) modelSel.value = gtm.model;
            const styleInp = document.getElementById('gemini-tts-style');
            if (styleInp) styleInp.value = gts.style || '';
            const dvSel = document.getElementById('gemini-tts-default-voice');
            if (dvSel && gtdv.voice) dvSel.value = gtdv.voice;
            _updateGeminiTtsVisibility(!!keys.gemini);
        } catch(e) {}

    } catch(e) {
        console.error('[NIMM] Erreur chargement settings :', e);
    }
}

// ══════════════════════════════════════════
// PRÉRÉGLAGES (presets de configuration)
// ══════════════════════════════════════════

async function loadPresetsIntoUI() {
    const sel = document.getElementById('preset-select');
    if (!sel) return;
    try {
        const data = await fetch('/api/presets').then(r => r.json());
        const names = Object.keys(data.presets || {}).sort((a, b) => a.localeCompare(b, 'fr'));
        const previous = sel.value;
        sel.innerHTML = names.length
            ? names.map(n => `<option value="${n}">${n}</option>`).join('')
            : '<option value="">— aucun préréglage enregistré —</option>';
        if (names.includes(previous)) sel.value = previous;
    } catch(e) {
        console.error('[NIMM] Erreur chargement préréglages :', e);
    }
}

document.getElementById('preset-save-btn')?.addEventListener('click', async () => {
    const input  = document.getElementById('preset-name-input');
    const status = document.getElementById('preset-status');
    const name   = (input?.value || '').trim();
    if (!name) {
        if (status) status.textContent = 'Indique un nom pour le préréglage.';
        return;
    }
    try {
        await fetch('/api/presets', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        if (input) input.value = '';
        await loadPresetsIntoUI();
        const sel = document.getElementById('preset-select');
        if (sel) sel.value = name;
        if (status) status.textContent = `Préréglage « ${name} » enregistré à partir des réglages actuels.`;
    } catch(e) {
        if (status) status.textContent = "Erreur lors de l'enregistrement du préréglage.";
    }
});

document.getElementById('preset-apply-btn')?.addEventListener('click', async () => {
    const sel    = document.getElementById('preset-select');
    const status = document.getElementById('preset-status');
    const name   = sel?.value;
    if (!name) {
        if (status) status.textContent = 'Choisis un préréglage à appliquer.';
        return;
    }
    try {
        const res = await fetch(`/api/presets/${encodeURIComponent(name)}/apply`, { method: 'POST' });
        if (!res.ok) throw new Error('apply failed');
        if (status) status.textContent = `Préréglage « ${name} » appliqué. Mise à jour des réglages…`;
        // Recharge tous les panneaux de réglages (routage, masque, mode local,
        // moteur de recherche, etc.) en redéclenchant les chargeurs liés à
        // l'ouverture de la fenêtre Paramètres.
        document.getElementById('toggle-settings')?.dispatchEvent(new Event('click'));
        if (status) status.textContent = `Préréglage « ${name} » appliqué.`;
    } catch(e) {
        if (status) status.textContent = "Erreur lors de l'application du préréglage.";
    }
});

document.getElementById('preset-delete-btn')?.addEventListener('click', async () => {
    const sel    = document.getElementById('preset-select');
    const status = document.getElementById('preset-status');
    const name   = sel?.value;
    if (!name) {
        if (status) status.textContent = 'Choisis un préréglage à supprimer.';
        return;
    }
    try {
        await fetch(`/api/presets/${encodeURIComponent(name)}`, { method: 'DELETE' });
        await loadPresetsIntoUI();
        if (status) status.textContent = `Préréglage « ${name} » supprimé.`;
    } catch(e) {
        if (status) status.textContent = 'Erreur lors de la suppression du préréglage.';
    }
});

async function _checkProviderBanner() {
    try {
        const [keys, routing] = await Promise.all([
            fetch('/api/settings/api-keys').then(r => r.json()),
            fetch('/api/settings/routing').then(r => r.json())
        ]);
        const provider = routing.chat || '';
        const LOCAL    = ['ollama'];
        const KEY_MAP  = { anthropic:'anthropic', deepseek:'deepseek', openai:'openai', gemini:'gemini', openrouter:'openrouter', mistral:'mistral', groq:'groq', cerebras:'cerebras', tavily:'tavily' };
        const keyName  = KEY_MAP[provider];
        const missing  = !provider || (!LOCAL.includes(provider) && keyName && !keys[keyName]);
        document.getElementById('no-provider-banner').classList.toggle('hidden', !missing);
    } catch(e) {}
}

document.getElementById('banner-open-settings')?.addEventListener('click', () => {
    document.getElementById('settings-modal').classList.remove('hidden');
    // Retour sur l'onglet Paramètres à chaque ouverture via la bannière
    document.querySelectorAll('.settings-tab').forEach(b => {
        const isParams = b.dataset.tab === 'params';
        b.classList.toggle('active', isParams);
        b.setAttribute('aria-selected', String(isParams));
    });
    document.querySelectorAll('.settings-tab-content').forEach(c => {
        c.classList.toggle('hidden', c.id !== 'settings-tab-params');
    });
    setTimeout(() => { document.querySelector('#settings-modal .close-modal')?.focus(); }, 50);
});

document.getElementById('toggle-settings').addEventListener('click', async () => {
    document.getElementById('settings-modal').classList.remove('hidden');
    setTimeout(() => { document.querySelector('#settings-modal .close-modal')?.focus(); }, 50);
    loadSettingsIntoUI();
    loadPresetsIntoUI();
    loadVoices();
    // Charger l'état embeddings
    try {
        const r = await fetch('/api/settings/embeddings');
        const d = await r.json();
        const tog = document.getElementById('embeddings-toggle');
        if (tog) tog.checked = d.enabled === true;
    } catch(e) {}
});

// Gestion du sélecteur de voix TTS
document.getElementById('voice-select')?.addEventListener('change', (e) => {
    _selectedVoice = e.target.value;
    localStorage.setItem('nimm-voice', _selectedVoice);
});

// Gestion du sélecteur de modèle Gemini TTS
document.getElementById('gemini-tts-model-select')?.addEventListener('change', async (e) => {
    try {
        await fetch('/api/settings/gemini-tts-model', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: e.target.value })
        });
    } catch(err) { console.error('[TTS] Erreur sauvegarde modèle Gemini :', err); }
});

// Gestion de la voix Gemini par défaut
document.getElementById('gemini-tts-default-voice')?.addEventListener('change', async (e) => {
    try {
        await fetch('/api/settings/gemini-tts-default-voice', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ voice: e.target.value })
        });
    } catch(err) { console.error('[TTS] Erreur sauvegarde voix Gemini par défaut :', err); }
});

// Gestion du champ de style Gemini TTS (sauvegarde au blur)
document.getElementById('gemini-tts-style')?.addEventListener('change', async (e) => {
    try {
        await fetch('/api/settings/gemini-tts-style', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ style: e.target.value })
        });
    } catch(err) { console.error('[TTS] Erreur sauvegarde style Gemini :', err); }
});


// ══════════════════════════════════════════
// AUTO-SAVE — chaque contrôle se sauvegarde au changement
// ══════════════════════════════════════════

// ── Modèles CONSEILLÉS par fournisseur (ordre : moins -> plus cher) ──
// Ce n'est PAS le catalogue : le vrai catalogue est interrogé chez le fournisseur
// et fusionné dans le sélecteur (voir _populateModelSelect). Cette liste ne sert
// qu'à mettre en avant quelques modèles avec un libellé parlant — un catalogue
// figé vieillirait à chaque sortie, celui-ci ne fait que des recommandations.
// Conseils revus le 30/07/2026. Un modèle absent d'ici reste accessible sous
// « Autres modèles disponibles ».
const MODELS_BY_PROVIDER = {
    anthropic: [
        { value: 'claude-haiku-4-5-20251001',  label: '💰 Claude Haiku — rapide, economique' },
        { value: 'claude-sonnet-5',             label: '💰💰 Claude Sonnet — equilibre' },
        { value: 'claude-opus-5',               label: '💰💰💰 Claude Opus — le plus puissant' },
    ],
    deepseek: [
        { value: 'deepseek-v4-flash',      label: '💰 DeepSeek V4 Flash — usage general' },
        { value: 'deepseek-reasoner',  label: '💰💰 DeepSeek Reasoner — raisonnement avance' },
    ],
    gemini: [
        { value: 'gemini-3.6-flash',          label: '💰 Gemini 3.6 Flash — rapide, economique' },
        { value: 'gemini-3.5-flash',          label: '💰 Gemini 3.5 Flash — solide, éprouvé' },
        { value: 'gemini-3.1-pro-preview',    label: '💰💰💰 Gemini 3.1 Pro — le plus puissant' },
    ],
    groq: [
        { value: 'llama-3.3-70b-versatile', label: '⚡ Llama 3.3 70B — rapide, polyvalent' },
    ],
    cerebras: [
        { value: 'llama-3.3-70b',           label: '⚡ Llama 3.3 70B — rapide, polyvalent' },
        { value: 'llama3.1-8b',             label: '⚡ Llama 3.1 8B — le plus rapide' },
    ],
    mistral: [
        { value: 'mistral-small-latest',        label: '💰 Mistral Small — léger, économique' },
        { value: 'mistral-medium-latest',       label: '💰💰 Mistral Medium — équilibré' },
        { value: 'mistral-large-latest',        label: '💰💰💰 Mistral Large — le plus puissant' },
        { value: 'magistral-small-latest',      label: '🧠💰 Magistral Small — raisonnement rapide' },
        { value: 'magistral-medium-latest',     label: '🧠💰💰 Magistral Medium — raisonnement approfondi' },
        { value: 'mistral-small-creative-latest', label: '🎨💰 Mistral Small Creative — créatif' },
        { value: 'codestral-latest',            label: '💻💰 Codestral — code & FIM' },
        { value: 'pixtral-12b-2409',            label: '🖼️💰 Pixtral 12B — vision' },
        { value: 'pixtral-large-latest',        label: '🖼️💰💰 Pixtral Large — vision puissant' },
    ],
    openai: [
        { value: 'gpt-4o-mini',   label: '💰 GPT-4o Mini — rapide, economique' },
        { value: 'gpt-4o',        label: '💰💰💰 GPT-4o — le plus puissant' },
    ],
    openrouter: [
        { value: 'mistralai/mistral-7b-instruct', label: '💰 Mistral 7B (defaut OpenRouter)' },
    ],
    ollama: [
        { value: 'llama3',     label: '💰 Llama 3 (local, gratuit)' },
        { value: 'llama3.1',   label: '💰 Llama 3.1 (local, gratuit)' },
        { value: 'gemma4',     label: '💰 Gemma 4 (local, gratuit)' },
        { value: 'gemma3:4b',  label: '💰 Gemma 3 4B (local, gratuit)' },
        { value: 'gemma3:12b', label: '💰 Gemma 3 12B (local, gratuit)' },
        { value: 'mistral',    label: '💰 Mistral (local, gratuit)' },
        { value: 'phi3',       label: '💰 Phi-3 (local, gratuit)' },
        { value: 'qwen2',      label: '💰 Qwen 2 (local, gratuit)' },
    ],
};

async function _populateModelSelect(provider, savedModel, selId = 'model-select') {
    const sel = document.getElementById(selId);
    if (!sel) return;
    const isMainSelect = selId === 'model-select';

    if (provider === 'ollama') {
        sel.innerHTML = '<option value="">⏳ Détection des modèles...</option>';
        try {
            const r = await fetch('/api/ollama/models');
            if (!r.ok) throw new Error();
            const d = await r.json();
            const models = d.models || [];
            if (!models.length) throw new Error();
            sel.innerHTML = models.map(m =>
                `<option value="${m}"${m === savedModel ? ' selected' : ''}>${m}</option>`
            ).join('');
            if (savedModel && models.includes(savedModel)) {
                sel.value = savedModel;
            } else {
                sel.value = models[0];
                if (isMainSelect) {
                    await fetch('/api/settings/model', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model: models[0] })
                    });
                }
            }
        } catch {
            sel.innerHTML = [
                'llama3', 'llama3.1', 'mistral', 'gemma3:4b', 'gemma3:12b', 'phi3', 'qwen2'
            ].map(m => `<option value="${m}">${m}</option>`).join('');

            // Champ texte libre pour les modeles non listes (uniquement Réglages)
            if (isMainSelect && !document.getElementById('ollama-custom-model')) {
                const input = document.createElement('input');
                input.type = 'text';
                input.id = 'ollama-custom-model';
                input.placeholder = 'ou tapez le nom exact (ex: gemma4)';
                input.style.cssText = 'margin-top:6px;width:100%;padding:4px 8px;font-size:0.85rem;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);';
                input.addEventListener('input', () => {
                    const val = input.value.trim();
                    if (!val) return;
                    let opt = sel.querySelector(`option[value="${val}"]`);
                    if (!opt) {
                        opt = document.createElement('option');
                        opt.value = val;
                        opt.text = val;
                        sel.add(opt);
                    }
                    sel.value = val;
                });
                sel.parentNode.insertBefore(input, sel.nextSibling);
            }

            if (isMainSelect) {
                const warn = document.getElementById('ollama-warn');
                if (warn) warn.classList.remove('hidden');
            }
        }
        return;
    }

    const models = MODELS_BY_PROVIDER[provider] || [];
    // Catalogue vivant interrogé chez le fournisseur : les listes codées en dur
    // vieillissent à chaque sortie de modèle. On FUSIONNE au lieu de remplacer —
    // les modèles conseillés (libellés parlants) d'abord, le reste regroupé à part,
    // pour ne pas noyer le sélecteur au lecteur d'écran (OpenRouter en expose des centaines).
    let live = [];
    try {
        const rl = await fetch(`/api/models/${encodeURIComponent(provider)}`);
        const dl = await rl.json();
        live = Array.isArray(dl.models) ? dl.models : [];
    } catch (e) { /* repli silencieux sur la liste conseillée */ }

    if (!models.length && !live.length) {
        sel.innerHTML = '<option value="">— modele par defaut —</option>';
        return;
    }
    const connus = new Set(models.map(m => m.value));
    const autres = live.filter(m => m.id && !connus.has(m.id));
    const opt = (v, lbl) => `<option value="${v}"${v === savedModel ? ' selected' : ''}>${lbl}</option>`;
    let html = '';
    if (models.length) {
        html += autres.length ? '<optgroup label="Modèles conseillés">' : '';
        html += models.map(m => opt(m.value, m.label)).join('');
        html += autres.length ? '</optgroup>' : '';
    }
    if (autres.length) {
        html += `<optgroup label="Autres modèles disponibles (${autres.length})">`;
        html += autres.map(m => opt(m.id, m.label || m.id)).join('');
        html += '</optgroup>';
    }
    sel.innerHTML = html;
    const dispo = new Set([...connus, ...autres.map(m => m.id)]);
    if (savedModel && !dispo.has(savedModel)) {
        sel.value = models.length ? models[0].value : (autres[0] && autres[0].id) || '';
    }
    if (isMainSelect) {
        const warn = document.getElementById('ollama-warn');
        if (warn) warn.classList.add('hidden');
    }
}

document.getElementById('provider-select')?.addEventListener('change', async (e) => {
    _providerActif = e.target.value;
    _refreshVibeButtonVisibility();      // Vibe n'a de sens que si Mistral répond
    await _saveRouting('chat', e.target.value);
    _autoSaveFlash(e.target);
    _checkProviderBanner();
    // Repeupler les modeles selon le nouveau provider (await = on attend la liste Ollama)
    await _populateModelSelect(e.target.value, null);
    // Sauvegarder le premier modele de la liste comme nouveau defaut
    const sel = document.getElementById('model-select');
    if (sel && sel.value) {
        await fetch('/api/settings/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: sel.value })
        });
    }
});

document.getElementById('model-select')?.addEventListener('change', async (e) => {
    await fetch('/api/settings/model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: e.target.value })
    });
    _autoSaveFlash(e.target);
});

document.getElementById('routing-vision')?.addEventListener('change', async (e) => {
    await _saveRouting('vision', e.target.value);
    _updatePixtralModelVisibility(e.target.value);
    _autoSaveFlash(e.target);
});

document.getElementById('pixtral-model-select')?.addEventListener('change', async (e) => {
    try {
        await fetch('/api/settings/pixtral-model', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: e.target.value })
        });
    } catch(err) { console.error('[Vision] Erreur sauvegarde modèle Pixtral :', err); }
});

document.getElementById('routing-image')?.addEventListener('change', async (e) => {
    await _saveRouting('image', e.target.value);
    _autoSaveFlash(e.target);
});

document.getElementById('routing-memory')?.addEventListener('change', async (e) => {
    const val = e.target.value;
    await _saveRouting('memoire', val === 'same' ? {} : { provider: val });
    _autoSaveFlash(e.target);
});

document.getElementById('routing-titre')?.addEventListener('change', async (e) => {
    const val = e.target.value;
    await _saveRouting('titre', val === 'same' ? {} : { provider: val });
    _autoSaveFlash(e.target);
});

document.getElementById('routing-synthese')?.addEventListener('change', async (e) => {
    const val = e.target.value;
    await _saveRouting('synthese', val === 'same' ? {} : { provider: val });
    _autoSaveFlash(e.target);
});

document.getElementById('routing-coanimm')?.addEventListener('change', async (e) => {
    const val = e.target.value;
    await _saveRouting('coanimm', val === 'same' ? {} : { provider: val });
    _autoSaveFlash(e.target);
});

document.getElementById('routing-websearch')?.addEventListener('change', async (e) => {
    const val = e.target.value;
    await _saveRouting('web_search', val === 'same' ? {} : { provider: val });
    _autoSaveFlash(e.target);
});

document.getElementById('mask-select')?.addEventListener('change', async (e) => {
    await fetch('/api/settings/mask', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ mask_id: e.target.value })
    });
    _autoSaveFlash(e.target);
});

// ══════════════════════════════════════════
// POTARDS — mode personnalité par curseurs
// ══════════════════════════════════════════

const _NORMAL_SLIDERS = [
    { id: 'serieux',      left: '😄 Détendu',      right: 'Sérieux 🧐'        },
    { id: 'formel',       left: '👕 Familier',      right: 'Formel 👔'          },
    { id: 'expressif',    left: '😑 Neutre',        right: 'Expressif 🎉'       },
    { id: 'direct',       left: '🌿 Prudent',       right: 'Direct ⚡'          },
    { id: 'metaphorique', left: '📋 Littéral',      right: 'Métaphorique 🌈'   },
    { id: 'bienveillant', left: '😒 Cynique',       right: 'Bienveillant 🤗'   },
    { id: 'collaboratif', left: '👑 Autoritaire',   right: 'Collaboratif 🤝'   },
    { id: 'emojis',       left: '🚫 Sans emojis',   right: 'Emojis 🎊'          },
];

const _WTF_SLIDERS = [
    { id: 'wtf_cafe',       left: '☕ Sobre',          right: '🍹 Champomy'        },
    { id: 'wtf_jargon',     left: '📚 Jargonneux',     right: '🧒 Pédago 5 ans'   },
    { id: 'wtf_ado',        left: '📋 Factuel',        right: '💬 Ado'             },
    { id: 'wtf_theatral',   left: '✂️ Court',           right: '🎭 Théâtral'        },
    { id: 'wtf_metaphores', left: '🏜️ 0 métaphores',   right: '🌊 100 métaphores'  },
    { id: 'wtf_tension',    left: '😴 Calme',          right: '⚡ TENSION !!!'      },
];

let _potardsTimer = null;

    function _buildSliderRow(cfg, val) {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;margin:5px 0;';
        // Noms sans emoji pour aria-valuetext (lisibles à voix haute sans bruit)
        const stripEmoji = s => s.replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '').trim();
        const leftName   = stripEmoji(cfg.left);
        const rightName  = stripEmoji(cfg.right);
        const valueText  = val == 0 ? leftName : val == 2 ? rightName : 'Neutre';
        row.innerHTML = `
            <span style="font-size:0.7rem;width:90px;text-align:right;color:var(--text-muted);flex-shrink:0;" aria-hidden="true">${cfg.left}</span>
            <input type="range" id="potard-${cfg.id}" min="0" max="2" step="1" value="${val}"
                   style="flex:1;accent-color:var(--accent);cursor:pointer;"
                   aria-label="${cfg.left} / ${cfg.right}"
                   aria-valuetext="${valueText}">
            <span style="font-size:0.7rem;width:90px;color:var(--text-muted);flex-shrink:0;" aria-hidden="true">${cfg.right}</span>
        `;
        // Mise à jour aria-valuetext à chaque mouvement du curseur
        const input = row.querySelector('input[type="range"]');
        input.addEventListener('input', () => {
            const v = parseInt(input.value);
            input.setAttribute('aria-valuetext', v === 0 ? leftName : v === 2 ? rightName : 'Neutre');
        });
        return row;
    }

function _applyModeUI(mode) {
    const maskBtn    = document.getElementById('mode-mask-btn');
    const potardsBtn = document.getElementById('mode-potards-btn');
    const panelMask  = document.getElementById('panel-mask');
    const panelPot   = document.getElementById('panel-potards');
    if (!maskBtn || !potardsBtn) return;

    const isMask = mode === 'mask';
    maskBtn.style.background  = isMask ? 'var(--accent)' : 'var(--bg-input)';
    maskBtn.style.color        = isMask ? '#fff' : 'var(--text-main)';
    maskBtn.style.borderColor  = isMask ? 'var(--accent)' : 'var(--border)';
    maskBtn.setAttribute('aria-pressed', String(isMask));
    potardsBtn.style.background = !isMask ? 'var(--accent)' : 'var(--bg-input)';
    potardsBtn.style.color       = !isMask ? '#fff' : 'var(--text-main)';
    potardsBtn.style.borderColor = !isMask ? 'var(--accent)' : 'var(--border)';
    potardsBtn.setAttribute('aria-pressed', String(!isMask));
    if (panelMask)  panelMask.classList.toggle('hidden', !isMask);
    if (panelPot)   panelPot.classList.toggle('hidden', isMask);
}

async function _initPotards() {
    const normalContainer = document.getElementById('potards-normal');
    const wtfContainer    = document.getElementById('potards-wtf');
    if (!normalContainer || !wtfContainer) return;

    // Charger valeurs + mode
    let potards = {}, mode = 'mask';
    try {
        [potards, mode] = await Promise.all([
            fetch('/api/settings/potards').then(r => r.json()),
            fetch('/api/settings/personality-mode').then(r => r.json()).then(d => d.mode || 'mask'),
        ]);
    } catch(e) {}

    // Construire les sliders normaux (une seule fois)
    if (!normalContainer.dataset.built) {
        normalContainer.dataset.built = '1';
        _NORMAL_SLIDERS.forEach(cfg => {
            normalContainer.appendChild(_buildSliderRow(cfg, potards[cfg.id] ?? 5));
        });
    } else {
        // Mettre à jour les valeurs si déjà construits
        _NORMAL_SLIDERS.forEach(cfg => {
            const el = document.getElementById(`potard-${cfg.id}`);
            if (el) el.value = potards[cfg.id] ?? 5;
        });
    }

    // Construire les sliders WTF (une seule fois)
    if (!wtfContainer.dataset.built) {
        wtfContainer.dataset.built = '1';
        _WTF_SLIDERS.forEach(cfg => {
            wtfContainer.appendChild(_buildSliderRow(cfg, potards[cfg.id] ?? 0));
        });
    } else {
        _WTF_SLIDERS.forEach(cfg => {
            const el = document.getElementById(`potard-${cfg.id}`);
            if (el) el.value = potards[cfg.id] ?? 0;
        });
    }

    // WTF toggle
    const wtfToggle = document.getElementById('wtf-toggle');
    if (wtfToggle) {
        wtfToggle.checked = potards.wtf_enabled === true;
        wtfContainer.classList.toggle('hidden', !wtfToggle.checked);
        wtfToggle.addEventListener('change', async () => {
            wtfContainer.classList.toggle('hidden', !wtfToggle.checked);
            await fetch('/api/settings/potards', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ wtf_enabled: wtfToggle.checked })
            });
        }, { once: true });
    }

    // Listeners sliders — debounce 400ms
    [..._NORMAL_SLIDERS, ..._WTF_SLIDERS].forEach(cfg => {
        const el = document.getElementById(`potard-${cfg.id}`);
        if (!el || el.dataset.bound) return;
        el.dataset.bound = '1';
        el.addEventListener('input', () => {
            clearTimeout(_potardsTimer);
            _potardsTimer = setTimeout(async () => {
                await fetch('/api/settings/potards', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ [cfg.id]: parseInt(el.value) })
                });
            }, 400);
        });
    });

    // Boutons de mode
    const maskBtn    = document.getElementById('mode-mask-btn');
    const potardsBtn = document.getElementById('mode-potards-btn');
    if (maskBtn && !maskBtn.dataset.bound) {
        maskBtn.dataset.bound = '1';
        maskBtn.addEventListener('click', async () => {
            await fetch('/api/settings/personality-mode', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ mode: 'mask' })
            });
            _applyModeUI('mask');
        });
    }
    if (potardsBtn && !potardsBtn.dataset.bound) {
        potardsBtn.dataset.bound = '1';
        potardsBtn.addEventListener('click', async () => {
            await fetch('/api/settings/personality-mode', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ mode: 'potards' })
            });
            _applyModeUI('potards');
        });
    }

    // Sauvegarder l'état actuel des curseurs comme masque personnalisé
    const saveBtn    = document.getElementById('potards-save-btn');
    const saveInput  = document.getElementById('potards-save-name');
    const saveStatus = document.getElementById('potards-save-status');
    if (saveBtn && !saveBtn.dataset.bound) {
        saveBtn.dataset.bound = '1';
        saveBtn.addEventListener('click', async () => {
            const name = (saveInput?.value || '').trim();
            if (!name) {
                if (saveStatus) saveStatus.textContent = '⚠️ Donne un nom au masque avant d\'enregistrer.';
                saveInput?.focus();
                return;
            }
            if (saveStatus) saveStatus.textContent = 'Enregistrement…';
            try {
                const r = await fetch('/api/masks/save', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                if (!r.ok) throw new Error('Échec');
                const mask = await r.json();
                if (saveStatus) saveStatus.textContent = `✅ Masque « ${name} » enregistré (utilisable depuis le mode Masque).`;
                if (saveInput) saveInput.value = '';
                _maskCache[mask.id] = mask.label;
                // Ajoute le nouveau masque aux listes déroulantes sans recharger la page.
                [document.getElementById('mask-select'),
                 document.getElementById('new-thread-mask-select')].forEach(sel => {
                    if (!sel) return;
                    if (![...sel.options].some(o => o.value === mask.id)) {
                        const opt = document.createElement('option');
                        opt.value = mask.id;
                        opt.textContent = mask.label;
                        sel.appendChild(opt);
                    }
                });
            } catch (e) {
                if (saveStatus) saveStatus.textContent = '❌ Erreur lors de l\'enregistrement du masque.';
            }
        });
    }

    // Appliquer le mode actuel
    _applyModeUI(mode);
}

document.getElementById('length-select')?.addEventListener('change', async (e) => {
    await fetch('/api/settings/length', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ value: parseInt(e.target.value) })
    });
    _autoSaveFlash(e.target);
});

function _initFontPicker() {
    const picker  = document.getElementById('font-picker');
    const btn     = document.getElementById('font-picker-btn');
    const current = document.getElementById('font-picker-current');
    const list    = document.getElementById('font-picker-list');
    if (!picker || !btn || !list) return;
    if (picker.dataset.initialized) return;
    picker.dataset.initialized = 'true';

    const options = Array.from(list.querySelectorAll('.font-picker-option'));

    function _selectFont(value, name) {
        document.body.style.fontFamily = value;
        localStorage.setItem('nimm-font', value);
        if (current) { current.textContent = name; current.style.fontFamily = value; }
        options.forEach(o => o.setAttribute('aria-selected', o.dataset.font === value ? 'true' : 'false'));
    }

    function _open() {
        const rect      = btn.getBoundingClientRect();
        const maxH      = 280;
        const spaceBelow = window.innerHeight - rect.bottom - 8;
        const spaceAbove = rect.top - 8;
        list.style.position = 'fixed';
        list.style.left  = rect.left + 'px';
        list.style.width = rect.width + 'px';
        if (spaceBelow >= Math.min(maxH, 150) || spaceBelow >= spaceAbove) {
            list.style.top    = rect.bottom + 4 + 'px';
            list.style.bottom = 'auto';
            list.style.maxHeight = Math.max(spaceBelow, 100) + 'px';
        } else {
            list.style.bottom = window.innerHeight - rect.top + 4 + 'px';
            list.style.top    = 'auto';
            list.style.maxHeight = Math.max(spaceAbove, 100) + 'px';
        }
        picker.setAttribute('aria-expanded', 'true');
        list.classList.remove('hidden');
        const sel = list.querySelector('[aria-selected="true"]') || options[0];
        if (sel) sel.focus();
    }

    function _close() {
        picker.setAttribute('aria-expanded', 'false');
        list.classList.add('hidden');
        btn.focus();
    }

    // Restaurer la police sauvegardée
    const saved = localStorage.getItem('nimm-font');
    if (saved) {
        const match = options.find(o => o.dataset.font === saved);
        if (match) _selectFont(saved, match.querySelector('.fpn')?.textContent || saved);
    }

    // Bouton déclencheur
    btn.addEventListener('click', e => {
        e.stopPropagation();
        picker.getAttribute('aria-expanded') === 'true' ? _close() : _open();
    });
    btn.addEventListener('keydown', e => {
        if (['ArrowDown','Enter',' '].includes(e.key)) { e.preventDefault(); _open(); }
        else if (e.key === 'Escape') _close();
    });

    // Options
    options.forEach(opt => {
        opt.setAttribute('tabindex', '-1');
        opt.addEventListener('click', () => {
            _selectFont(opt.dataset.font, opt.querySelector('.fpn')?.textContent || opt.dataset.font);
            _close();
        });
        opt.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                _selectFont(opt.dataset.font, opt.querySelector('.fpn')?.textContent || opt.dataset.font);
                _close();
            } else if (e.key === 'ArrowDown') { e.preventDefault(); opt.nextElementSibling?.focus(); }
            else if (e.key === 'ArrowUp')   { e.preventDefault(); opt.previousElementSibling?.focus(); }
            else if (e.key === 'Escape')    _close();
        });
    });

    // Fermer au clic extérieur
    document.addEventListener('click', e => { if (picker.getAttribute('aria-expanded') === 'true' && !picker.contains(e.target)) _close(); });
}

// ── Thème clair / sombre ──
(function() {
    const saved = localStorage.getItem('nimm-theme');
    if (saved === 'light') document.documentElement.dataset.theme = 'light';
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
        toggle.checked = (localStorage.getItem('nimm-theme') === 'light');
        toggle.addEventListener('change', () => {
            if (toggle.checked) {
                document.documentElement.dataset.theme = 'light';
                localStorage.setItem('nimm-theme', 'light');
            } else {
                delete document.documentElement.dataset.theme;
                localStorage.setItem('nimm-theme', 'dark');
            }
        });
    }
})();

document.getElementById('embeddings-toggle')?.addEventListener('change', async (e) => {
    await fetch('/api/settings/embeddings', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ enabled: e.target.checked })
    });
    if (e.target.checked) {
        fetch('/api/embeddings/warmup', { method: 'POST' });
        _watchEmbeddingsStatus();
    }
});

document.getElementById('presence-slider')?.addEventListener('change', async (e) => {
    await fetch('/api/settings/presence', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ value: parseInt(e.target.value) })
    });
});

document.getElementById('memoire-mode-select')?.addEventListener('change', async (e) => {
    await fetch('/api/settings/memoire-mode', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ value: e.target.value })
    });
    _autoSaveFlash(e.target);
});

// ── Services externes : le formulaire des clés est ENGENDRÉ depuis le
// catalogue serveur (core/services.py). Ajouter un service là-bas suffit :
// les clés d'Exa, Cohere, Voyage et Jina n'avaient nulle part où être saisies
// tant que cette liste était écrite en dur ici, à trois endroits. ──
let _SERVICES = [];

function _svcIds() {
    // Repli sur l'ancienne liste tant que le catalogue n'est pas revenu :
    // le formulaire doit rester utilisable même si la route échoue.
    return _SERVICES.length ? _SERVICES.map(s => s.id)
        : ['anthropic', 'deepseek', 'gemini', 'openai', 'openrouter',
           'mistral', 'groq', 'cerebras', 'stability_ai', 'brave', 'tavily'];
}

function _svcEchappe(t) {
    return String(t == null ? '' : t)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

async function _chargerServices() {
    const hote = document.getElementById('api-keys-auto');
    try {
        const d = await fetch('/api/settings/services').then(r => r.json());
        _SERVICES = (d.familles || []).reduce((a, f) => a.concat(f.services || []), []);
        if (!hote) return;
        hote.innerHTML = (d.familles || []).map(function (f) {
            const titre = '<h5 style="grid-column:1/-1;margin:10px 0 2px;font-size:0.85rem;">'
                        + _svcEchappe(f.libelle) + '</h5>';
            return titre + (f.services || []).map(function (sv) {
                const id = 'api-key-' + sv.html_id;
                const ph = sv.configure ? '✅ Configurée — laisser vide pour ne pas changer'
                                        : (sv.exemple || '');
                // Le rôle du service est porté par aria-describedby : lu au focus,
                // sans alourdir l'étiquette du champ.
                return '<label for="' + id + '">' + _svcEchappe(sv.nom) + '</label>'
                     + '<input type="password" id="' + id + '" placeholder="' + _svcEchappe(ph)
                     + '" aria-describedby="' + id + '-role">'
                     + '<div id="' + id + '-role" style="grid-column:1/-1;font-size:0.75rem;'
                     + 'color:var(--text-muted);margin:-4px 0 8px;">' + _svcEchappe(sv.role || '')
                     + (sv.console ? ' <a href="' + _svcEchappe(sv.console)
                                   + '" target="_blank" rel="noopener">Obtenir une clé</a>' : '')
                     + '</div>';
            }).join('');
        }).join('');
    } catch (e) {
        if (hote) hote.textContent = 'Catalogue des services indisponible : ' + e.message;
    }
}
_chargerServices();

// ── Clés API — bouton dédié (saisie manuelle, on ne sauvegarde pas pendant la frappe) ──
async function _saveApiKeys() {
    const providers = _svcIds();
    const keys = {};
    providers.forEach(p => {
        const val = document.getElementById(`api-key-${p.replace('_','-')}`)?.value.trim();
        if (val && val.length > 5) keys[p] = val;
    });
    if (Object.keys(keys).length === 0) return;

    await fetch('/api/settings/api-keys', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(keys)
    });

    // Feedback + mise à jour des placeholders
    providers.forEach(p => {
        const el = document.getElementById(`api-key-${p.replace('_','-')}`);
        if (el) { el.value = ''; el.placeholder = keys[p] ? '✅ Configurée' : el.placeholder; }
    });

    // Re-appliquer les contraintes de routage avec les nouvelles clés
    const freshKeys = await fetch('/api/settings/api-keys').then(r => r.json());
    _applyProviderConstraints(freshKeys);
    await _chargerServices();   // remet les pastilles « Configurée » à jour

    // Si le provider actuel est Ollama ou vide, basculer automatiquement sur le premier provider configuré
    const currentProvider = await fetch('/api/settings/provider').then(r => r.json()).then(d => d.provider).catch(() => '');
    const llmProviders = ['deepseek','anthropic','openai','gemini','mistral','openrouter','groq','cerebras'];
    if (!currentProvider || currentProvider === 'ollama') {
        const firstAvailable = llmProviders.find(p => keys[p]);
        if (firstAvailable) {
            await fetch('/api/settings/provider', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ provider: firstAvailable })
            });
            // Rechargement pour synchroniser provider + modèle depuis la DB
            setTimeout(() => location.reload(), 500);
        }
    }
}

// ══════════════════════════════════════════
// RETOUCHE IMAGE — modale ✏️
// ══════════════════════════════════════════

let _imageEditB64    = null;
let _imageEditPrompt = '';

function openImageEditModal(b64, prompt) {
    _imageEditB64    = b64;
    _imageEditPrompt = prompt;
    const modal   = document.getElementById('image-edit-modal');
    const preview = document.getElementById('image-edit-preview');
    const input   = document.getElementById('image-edit-prompt');
    preview.src   = b64 ? `data:image/png;base64,${b64}` : '';
    input.value   = prompt;
    modal.classList.remove('hidden');
    input.focus();
}

document.getElementById('image-edit-close')?.addEventListener('click', () => {
    document.getElementById('image-edit-modal').classList.add('hidden');
});
document.getElementById('image-edit-cancel')?.addEventListener('click', () => {
    document.getElementById('image-edit-modal').classList.add('hidden');
});

document.getElementById('image-edit-ok')?.addEventListener('click', async () => {
    const prompt = document.getElementById('image-edit-prompt').value.trim();
    if (!prompt || !_imageEditB64) return;
    document.getElementById('image-edit-modal').classList.add('hidden');

    appendAssistantMessage('🎨 Retouche en cours…');
    try {
        const r = await fetch('/api/image/edit', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ prompt, b64: _imageEditB64 }),
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (!data.b64) throw new Error('Aucune image retournée');

        // Supprimer le message "Retouche en cours…"
        const msgs = document.getElementById('messages');
        if (msgs.lastChild) msgs.lastChild.remove();

        // Afficher le résultat comme une nouvelle image générée
        const src      = `data:image/png;base64,${data.b64}`;
        const imgDiv   = document.createElement('div');
        imgDiv.className = 'message assistant';
        const emoji    = document.createElement('div');
        emoji.className = 'bubble-emoji';
        emoji.setAttribute('aria-hidden', 'true');
        emoji.textContent = '🎨';
        const bubble   = document.createElement('div');
        bubble.className = 'message-bubble';
        // Après une retouche, la consigne est une INSTRUCTION (« mets-le en noir
        // et blanc ») : la mettre en alt serait encore moins utilisable qu'une
        // consigne de création. Alt provisoire, puis vraie description.
        bubble.innerHTML = `<img src="${src}" alt="Image retouchée, description en cours…" style="max-width:100%;border-radius:10px;display:block;margin-bottom:8px;"><span style="font-size:0.8rem;color:var(--text-muted);">${_esc(prompt)}</span><br><div style="display:flex;gap:8px;margin-top:8px;"><button class="img-download-btn" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;" aria-label="Télécharger l'image">⬇ Télécharger</button><button class="img-edit-btn" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;" aria-label="Modifier l'image">✏️ Modifier</button></div>`;
        bubble.querySelector('.img-download-btn').addEventListener('click', async () => {
            try {
                const resp = await fetch(src);
                const blob = await resp.blob();
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'nimm-image-retouche.png';
                a.click();
                URL.revokeObjectURL(a.href);
            } catch(e) {
                const a = document.createElement('a');
                a.href = src; a.download = 'nimm-image-retouche.png'; a.target = '_blank'; a.click();
            }
        });
        bubble.querySelector('.img-edit-btn').addEventListener('click', () => {
            openImageEditModal(data.b64, prompt);
        });
        _decrireImageGeneree(bubble, data.b64 || '', '', prompt);
        imgDiv.appendChild(emoji);
        imgDiv.appendChild(bubble);
        document.getElementById('messages').appendChild(imgDiv);
        document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
    } catch(e) {
        const msgs = document.getElementById('messages');
        if (msgs.lastChild) msgs.lastChild.remove();
        appendAssistantMessage(`❌ Erreur retouche : ${e.message}`);
    }
});

document.getElementById('save-api-keys-btn').addEventListener('click', _saveApiKeys);

// Entree ou perte de focus sur un champ cle -> sauvegarde automatique
['anthropic','deepseek','gemini','openai','openrouter','mistral','groq','cerebras','stability-ai','brave','tavily'].forEach(p => {
    const el = document.getElementById(`api-key-${p}`);
    if (!el) return;
    el.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); _saveApiKeys(); } });
    el.addEventListener('blur', () => { if (el.value.trim().length > 5) _saveApiKeys(); });
});

// ══════════════════════════════════════════
// PRÉSENCE — CURSEUR
// ══════════════════════════════════════════

const _PRESENCE_HINTS = [
    'Aucune référence au temps passé.',
    'Réagit si plus de 24h.',
    'Réagit si plus de 12h.',
    'Réagit si plus de 6h.',
    'Réagit si plus de 3h.',
    'Réagit si plus d\'1h.',
];

function _updatePresenceHint(val) {
    const hint = document.getElementById('presence-hint');
    if (hint) hint.textContent = _PRESENCE_HINTS[parseInt(val)] || '';
}

document.getElementById('presence-slider')?.addEventListener('input', (e) => {
    _updatePresenceHint(e.target.value);
});

// ══════════════════════════════════════════
// MÉMOIRE
// ══════════════════════════════════════════

// ── Bouton toggle TTS auto ──
(function setupAutoTTSToggle() {
    const btn = document.createElement('button');
    btn.id        = 'autotts-toggle';
    btn.title     = 'Lecture automatique';
    btn.setAttribute('aria-label', 'Lecture automatique');
    btn.setAttribute('aria-keyshortcuts', 'Alt+L');
    btn.setAttribute('aria-pressed', _autoTTS ? 'true' : 'false');
    btn.className = 'topbar-icon-btn' + (_autoTTS ? ' active' : '');
    btn.innerHTML = spk2;
    btn.addEventListener('click', () => {
        _autoTTS = !_autoTTS;
        localStorage.setItem('nimm-autotts', _autoTTS);
        btn.classList.toggle('active', _autoTTS);
        btn.setAttribute('aria-pressed', _autoTTS ? 'true' : 'false');
    });
    // Insérer dans la topbar, avant les icônes droite
    const topRight = document.getElementById('top-right');
    if (topRight) topRight.insertBefore(btn, topRight.firstChild);
})();

// ── Bouton mode fantôme ──
let _ghostMode = false;

// ── Notification accessible (aria-live) ─────────────────────────────────────
function _notify(msg, type) {
    type = type || 'info';
    let area = document.getElementById('_nimm-notify-area');
    if (!area) {
        area = document.createElement('div');
        area.id = '_nimm-notify-area';
        area.setAttribute('aria-live', 'polite');
        area.setAttribute('aria-atomic', 'true');
        area.style.cssText = 'position:fixed;bottom:1.2rem;left:50%;transform:translateX(-50%);z-index:9999;display:flex;flex-direction:column;align-items:center;gap:6px;pointer-events:none';
        document.body.appendChild(area);
    }
    const colors = {ok:'#2e7d32', warn:'#e65100', error:'#c62828', info:'#1565c0'};
    const el = document.createElement('div');
    el.setAttribute('role', 'status');
    el.textContent = msg;
    el.style.cssText = (
        'padding:8px 18px;border-radius:8px;font-size:0.85rem;color:#fff;'
        + 'background:' + (colors[type] || colors.info) + ';'
        + 'box-shadow:0 2px 8px rgba(0,0,0,.3);max-width:320px;text-align:center;'
        + 'pointer-events:auto;'
    );
    area.appendChild(el);
    setTimeout(() => { el.remove(); }, 3500);
}

/**
 * Affiche un toast contextuel selon le code HTTP d'une erreur de service.
 * @param {number} status  Code HTTP (0 = erreur réseau / pas de réponse)
 */
function _notifyServiceError(status) {
    if (status === 401 || status === 403) {
        _notify('Clé API invalide ou expirée — vérifiez vos réglages.', 'error');
    } else if (status === 429) {
        _notify('Limite de débit atteinte — réessayez dans quelques instants.', 'warn');
    } else if (status >= 500 && status < 600) {
        _notify('Fournisseur temporairement indisponible — réessayez plus tard.', 'warn');
    } else if (!status) {
        _notify('Connexion impossible — vérifiez votre réseau.', 'warn');
    } else {
        _notify(`Erreur inattendue du fournisseur (code ${status}).`, 'error');
    }
}

async function _saveExtKey(serviceId) {
    const input = document.getElementById(`ext-key-${serviceId}`);
    if (!input) return;
    const key = input.value.trim();
    if (!key) { _notify('Saisir une clé avant de sauvegarder.', 'warn'); return; }
    try {
        const r = await fetch('/api/settings/ext-keys', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({service_id: serviceId, key})
        });
        if (!r.ok) throw new Error(await r.text());
        input.value = '';
        input.placeholder = '••••••••';
        _notify('Clé enregistrée.', 'ok');
        // Marquer comme configuré sans recharger toute la page
        const details = input.closest('details');
        if (details) {
            const badge = details.querySelector('summary span:last-child');
            if (badge) { badge.style.color = 'var(--success,#4caf50)'; badge.textContent = '✔ configuré'; }
        }
    } catch(e) {
        _notify('Erreur : ' + e.message, 'error');
    }
}

async function _deleteExtKey(serviceId, btn) {
    if (!confirm(`Supprimer la clé pour ${serviceId} ?`)) return;
    try {
        const r = await fetch(`/api/settings/ext-keys/${serviceId}`, {method: 'DELETE'});
        if (!r.ok) throw new Error(await r.text());
        _notify('Clé supprimée.', 'ok');
        // Retirer le bouton supprimer + mise à jour badge
        if (btn) btn.remove();
        const details = document.getElementById(`ext-key-${serviceId}`)?.closest('details');
        if (details) {
            const badge = details.querySelector('summary span:last-child');
            if (badge) { badge.style.color = 'var(--text-muted)'; badge.textContent = 'non configuré'; }
            const inp = document.getElementById(`ext-key-${serviceId}`);
            if (inp) inp.placeholder = 'Saisir la clé';
        }
    } catch(e) {
        _notify('Erreur : ' + e.message, 'error');
    }
}


// ══════════════════════════════════════════
// VOICE BANKING — fonctions JS
// ══════════════════════════════════════════

let _vbMediaRecorder = null;
let _vbChunks = [];
let _vbRecording = false;
let _vbAudioBlob = null;
let _vbTimerInterval = null;
let _vbTimerSec = 0;

function _vbToggleRecord() {
    const btn = document.getElementById('vb-rec-btn');
    const timer = document.getElementById('vb-rec-timer');
    if (_vbRecording) {
        // Arrêter
        _vbMediaRecorder && _vbMediaRecorder.stop();
        _vbRecording = false;
        btn.textContent = '🎙️ Enregistrer';
        btn.setAttribute('aria-label', "Démarrer l'enregistrement");
        clearInterval(_vbTimerInterval);
        timer.textContent = '';
        return;
    }
    // Démarrer — utiliser le micro sélectionné si disponible
    const _micSel = document.getElementById('vb-mic-select');
    const _micId = _micSel ? _micSel.value : '';
    const _audioConstraint = _micId ? {deviceId: {exact: _micId}} : true;
    navigator.mediaDevices.getUserMedia({audio: _audioConstraint}).then(stream => {
        _vbChunks = [];
        _vbMediaRecorder = new MediaRecorder(stream);
        _vbMediaRecorder.ondataavailable = e => { if (e.data.size > 0) _vbChunks.push(e.data); };
        _vbMediaRecorder.onstop = () => {
            _vbAudioBlob = new Blob(_vbChunks, {type: 'audio/webm'});
            const url = URL.createObjectURL(_vbAudioBlob);
            const preview = document.getElementById('vb-audio-preview');
            const player = document.getElementById('vb-preview-player');
            if (preview && player) { player.src = url; preview.style.display = ''; }
            const createBtn = document.getElementById('vb-create-btn');
            if (createBtn) { createBtn.disabled = false; createBtn.style.opacity = '1'; }
            stream.getTracks().forEach(t => t.stop());
        };
        _vbMediaRecorder.start();
        _vbRecording = true;
        btn.textContent = '⏹ Arrêter';
        btn.setAttribute('aria-label', "Arrêter l'enregistrement");
        _vbTimerSec = 0;
        timer.textContent = '0s';
        _vbTimerInterval = setInterval(() => {
            _vbTimerSec++;
            timer.textContent = _vbTimerSec + 's';
            if (_vbTimerSec >= 60) _vbToggleRecord(); // auto-stop à 60s
        }, 1000);
    }).catch(e => {
        _notify('Microphone inaccessible : ' + e.message, 'error');
    });
}

async function _vbPopulateMicList() {
    const sel = document.getElementById('vb-mic-select');
    if (!sel || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    try {
        // Demander permission micro pour débloquer les labels
        await navigator.mediaDevices.getUserMedia({audio: true}).then(s => s.getTracks().forEach(t => t.stop())).catch(() => {});
        const devices = await navigator.mediaDevices.enumerateDevices();
        const mics = devices.filter(d => d.kind === 'audioinput');
        sel.innerHTML = '<option value="">Micro par défaut</option>';
        mics.forEach((m, i) => {
            const opt = document.createElement('option');
            opt.value = m.deviceId;
            opt.textContent = m.label || ('Microphone ' + (i + 1));
            sel.appendChild(opt);
        });
    } catch(e) { console.warn('[VB] enumerateDevices :', e); }
}
function _vbUpdateMicList() { /* appelé au changement, rien à faire */ }

function _vbFileSelected(input) {
    if (!input.files || !input.files[0]) return;
    _vbAudioBlob = input.files[0];
    const url = URL.createObjectURL(_vbAudioBlob);
    const preview = document.getElementById('vb-audio-preview');
    const player = document.getElementById('vb-preview-player');
    if (preview && player) { player.src = url; preview.style.display = ''; }
    const createBtn = document.getElementById('vb-create-btn');
    if (createBtn) { createBtn.disabled = false; createBtn.style.opacity = '1'; }
}

async function _vbCreateVoice() {
    if (!_vbAudioBlob) { _notify('Enregistrez ou importez un audio d\'abord.', 'warn'); return; }
    const name = (document.getElementById('vb-name')?.value || '').trim() || 'Ma voix';
    const lang = document.getElementById('vb-lang')?.value || 'fr';
    const gender = document.getElementById('vb-gender')?.value || '';
    const status = document.getElementById('vb-status');
    const btn = document.getElementById('vb-create-btn');
    if (status) status.textContent = '⏳ Création du profil en cours…';
    if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
    try {
        const fd = new FormData();
        const ext = _vbAudioBlob.name ? _vbAudioBlob.name.split('.').pop() : 'webm';
        fd.append('name', name);
        fd.append('language', lang);
        fd.append('gender', gender);
        fd.append('file', _vbAudioBlob, `sample.${ext}`);
        const r = await fetch('/api/voice/create', {method: 'POST', body: fd});
        if (!r.ok) { const t = await r.text(); throw new Error(t); }
        const data = await r.json();
        if (status) status.textContent = `✅ Profil "${data.name}" créé avec succès !`;
        _notify(`Voix "${data.name}" créée.`, 'ok');
        _vbAudioBlob = null;
        // Supprimer l’ancien profil si c’est une recréation
        const _section = document.getElementById('voice-banking-section');
        const _oldPid = _section?.dataset?.replacePid;
        if (_oldPid && _oldPid !== data.id) {
            delete _section.dataset.replacePid;
            try { await fetch(`/api/voice/profile/${_oldPid}`, {method: 'DELETE'}); } catch(_) {}
            _notify(`Ancien profil supprimé automatiquement.`, 'ok');
        }
        // Recharger la liste des voix et profils
        await _vbLoadProfiles();
        loadVoices && loadVoices();
        setTimeout(() => { document.getElementById('voice-banking-section')?.scrollIntoView({behavior:'smooth'}); }, 200);
    } catch(e) {
        if (status) status.textContent = '❌ Erreur : ' + e.message;
        _notify('Erreur création voix : ' + e.message, 'error');
        if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
}

async function _vbSetDefault(pid) {
    try {
        const r = await fetch(`/api/voice/default/${pid}`, {method: 'POST'});
        if (!r.ok) throw new Error(await r.text());
        _notify('Voix définie par défaut.', 'ok');
        await _vbLoadProfiles();
        loadVoices && loadVoices();
    } catch(e) { _notify('Erreur : ' + e.message, 'error'); }
}


async function _vbLoadProfiles() {
    const vbListEl = document.getElementById('voice-profiles-list');
    if (!vbListEl) return;
    try {
        const r = await fetch('/api/voice/profiles');
        const {profiles} = await r.json();
        if (!profiles || !profiles.length) {
            vbListEl.innerHTML = '<em style="font-size:0.8rem">Aucun profil créé.</em>';
            return;
        }
        let h = '<div style="display:flex;flex-direction:column;gap:8px">';
        for (const p of profiles) {
            const isDefault = p.is_default;
            h += `<div style="border:1px solid var(--border);border-radius:8px;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;gap:8px">
                <div>
                    <strong style="font-size:0.85rem">🟠 ${p.name}</strong>
                    ${isDefault ? '<span style="font-size:0.75rem;color:var(--success,#4caf50)"> ⭐ par défaut</span>' : ''}
                    <div style="font-size:0.75rem;color:var(--text-muted)">${(p.language||'fr').toUpperCase()} ${p.gender ? '· ' + p.gender : ''} · créé le ${(p.created_at||'').slice(0,10)}</div>
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
                    <button onclick="_vbPreview('voxtral:${p.mistral_voice_id}', this)" style="padding:3px 8px;border-radius:6px;background:var(--bg-secondary);border:1px solid var(--border);cursor:pointer;font-size:0.75rem" aria-label="Écouter un aperçu de cette voix">🔊 Aperçu</button>
                    <button data-pid="${p.id}" data-name="${p.name}" onclick="_vbDelete(this.dataset.pid, this.dataset.name)" style="padding:3px 8px;border-radius:6px;background:var(--bg-secondary);border:1px solid var(--border);cursor:pointer;font-size:0.75rem;color:var(--danger,#c00)" aria-label="Supprimer ce profil vocal">🗑️ Supprimer</button>
                    ${!isDefault ? `<button onclick="_vbSetDefault('${p.id}')" style="padding:3px 8px;border-radius:6px;background:var(--bg-secondary);border:1px solid var(--border);cursor:pointer;font-size:0.75rem" aria-label="Définir comme voix par défaut">⭐ Défaut</button>` : ''}
                    <button onclick="_vbExport('${p.id}','${p.name}')" style="padding:3px 8px;border-radius:6px;background:var(--bg-secondary);border:1px solid var(--border);cursor:pointer;font-size:0.75rem" aria-label="Exporter la voix">💾 Export</button>
                    <button data-pid="${p.id}" data-name="${p.name}" onclick="_vbRecreate(this.dataset.pid, this.dataset.name)" style="padding:3px 8px;border-radius:6px;background:var(--bg-secondary);border:1px solid var(--border);cursor:pointer;font-size:0.75rem" aria-label="Recréer ce profil avec un nouvel audio">♻️ Recréer</button>
                </div>
            </div>`;
        }
        h += '</div>';
        vbListEl.innerHTML = h;
    } catch(e) {
        vbListEl.innerHTML = '<em style="font-size:0.8rem;color:var(--danger,red)">Erreur chargement profils.</em>';
    }
}

async function _vbPreview(voiceId, btn) {
    const orig = btn.textContent;
    btn.textContent = '⏳'; btn.disabled = true;
    try {
        const r = await fetch('/api/tts/speak', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: "Bonjour, voici un aperçu de ma voix personnalisée dans NIMM.", voice: voiceId})
        });
        if (!r.ok) {
            const t = await r.text();
            let msg = t;
            try { msg = JSON.parse(t).detail || t; } catch(_) {}
            _notify('Aperçu impossible : ' + msg, 'error');
            btn.textContent = orig; btn.disabled = false;
            return;
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        // Utiliser le player déjà dans le DOM + le rendre visible
        let player = document.getElementById('vb-preview-player');
        if (!player) {
            // Repli : reproduire les MÊMES attributs que le lecteur du panneau.
            // Sans « controls », l'aperçu démarre et ne peut plus être arrêté.
            player = document.createElement('audio');
            player.id = 'vb-preview-player';
            player.controls = true;
            player.setAttribute('aria-label', 'Aperçu de la voix');
            player.style.cssText = 'width:100%;height:32px';
            (document.getElementById('vb-audio-preview') || document.body).appendChild(player);
        }
        const previewDiv = document.getElementById('vb-audio-preview');
        if (previewDiv) previewDiv.style.display = 'block';
        player.src = url;
        player.onended = () => { btn.textContent = orig; btn.disabled = false; URL.revokeObjectURL(url); };
        player.onerror = (e) => {
            btn.textContent = orig; btn.disabled = false;
            _notify('Erreur lecture audio : ' + (e.message||''), 'error');
        };
        const p = player.play();
        _notify("Lecture de l'aperçu en cours…", 'ok');
        if (p) p.catch(err => {
            _notify('Autoplay bloqué : cliquez sur le lecteur audio affiché.', 'info');
            btn.textContent = orig; btn.disabled = false;
        });
    } catch(e) { btn.textContent = orig; btn.disabled = false; _notify('Aperçu impossible : ' + e.message, 'error'); }
}

async function _vbDelete(pid, name) {
    if (!confirm(`Supprimer le profil vocal "${name}" ? Cette action est irréversible (suppression aussi chez Mistral).`)) return;
    try {
        const r = await fetch(`/api/voice/profile/${pid}`, {method: 'DELETE'});
        if (!r.ok) { const t = await r.text(); throw new Error(t); }
        _notify(`Profil "${name}" supprimé.`, 'ok');
        const section = document.getElementById('voice-banking-section');
        if (section) delete section.dataset.replacePid;
        await _vbLoadProfiles();
        loadVoices && loadVoices();
    } catch(e) { _notify('Erreur suppression : ' + e.message, 'error'); }
}

function _vbRecreate(pid, name) {
    const section = document.getElementById('voice-banking-section');
    if (section) section.dataset.replacePid = pid;
    const nameInput = document.getElementById('vb-name');
    if (nameInput) nameInput.value = name;
    section?.scrollIntoView({behavior: 'smooth'});
    setTimeout(() => {
        const lbl = document.querySelector('label[for="vb-file-input"]');
        (lbl || document.getElementById('vb-file-input'))?.focus();
    }, 400);
    _notify(`Choisissez un nouvel audio pour recréer la voix "${name}". L’ancien profil sera supprimé automatiquement après création.`, 'info');
}


function _vbExport(pid, name) {
    const a = document.createElement('a');
    a.href = `/api/voice/export/${pid}`;
    a.download = name.replace(/\s+/g,'_').toLowerCase() + '.nimmvoice';
    a.click();
}

async function _vbImportProfile(input) {
    if (!input.files || !input.files[0]) return;
    const recreate = document.getElementById('vb-import-recreate')?.checked ? '1' : '0';
    const fd = new FormData();
    fd.append('file', input.files[0], input.files[0].name);
    fd.append('recreate', recreate);
    _notify(recreate === '1' ? 'Import et recréation chez Mistral en cours…' : 'Import en cours…', 'info');
    try {
        const r = await fetch('/api/voice/import', {method:'POST', body: fd});
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        _notify(`Voix "${data.name}" importée${data.recreated ? ' et recréée chez Mistral' : ''}.`, 'ok');
        await _vbLoadProfiles();
        loadVoices && loadVoices();
    } catch(e) { _notify('Erreur import : ' + e.message, 'error'); }
}


// ══════════════════════════════════════════
// AGENTS MISTRAL — fonctions JS
// ══════════════════════════════════════════

async function _magCreate() {
    const name = (document.getElementById('mag-name')?.value || '').trim();
    if (!name) { _notify('Nom de l\'agent requis.', 'warn'); return; }
    const description = document.getElementById('mag-desc')?.value || '';
    const instructions = document.getElementById('mag-instructions')?.value || '';
    const model = document.getElementById('mag-model')?.value || 'mistral-medium-latest';
    const tools = [...document.querySelectorAll('.mag-tool-chk:checked')].map(c => ({type: c.value}));
    const status = document.getElementById('mag-status');
    if (status) status.textContent = '⏳ Création en cours…';
    try {
        const r = await fetch('/api/mistral-agents/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description, instructions, model, tools})
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (status) status.textContent = `✅ Agent "${data.name}" créé (ID : ${data.agent_id})`;
        _notify(`Agent "${data.name}" créé.`, 'ok');
        // Effacer le formulaire
        ['mag-name','mag-desc','mag-instructions'].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = '';
        });
        document.querySelectorAll('.mag-tool-chk').forEach(c => c.checked = false);
    } catch(e) {
        if (status) status.textContent = '❌ ' + e.message;
        _notify('Erreur : ' + e.message, 'error');
    }
}

async function _magDelete(agentId, name, btn) {
    if (!confirm(`Supprimer l'agent "${name}" ? Cette action le supprime aussi chez Mistral.`)) return;
    try {
        const r = await fetch(`/api/mistral-agents/${agentId}`, {method: 'DELETE'});
        if (!r.ok) throw new Error(await r.text());
        _notify(`Agent "${name}" supprimé.`, 'ok');
        btn?.closest('details')?.remove();
    } catch(e) { _notify('Erreur : ' + e.message, 'error'); }
}

function _magUploadFile(agentId) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.pdf,.txt,.md,.docx,.csv';
    input.onchange = async () => {
        if (!input.files || !input.files[0]) return;
        const fd = new FormData();
        fd.append('file', input.files[0], input.files[0].name);
        try {
            _notify('Upload en cours…', 'ok');
            const r = await fetch(`/api/mistral-agents/${agentId}/upload-file`, {method: 'POST', body: fd});
            if (!r.ok) throw new Error(await r.text());
            const data = await r.json();
            _notify(`Fichier "${data.filename}" ajouté à l'agent.`, 'ok');
        } catch(e) { _notify('Erreur upload : ' + e.message, 'error'); }
    };
    input.click();
}


async function _loadGhostMode(threadId) {
    if (!threadId) { _ghostMode = false; return; }
    try {
        const r = await fetch(`/api/threads/${threadId}/ghost`);
        const d = await r.json();
        _ghostMode = d.ghost || false;
    } catch(e) { _ghostMode = false; }
    // Plus de bouton à rafraîchir : l'état sert à renseigner la case des
    // Paramètres du fil, et à l'annoncer à l'ouverture d'un fil fantôme.
    if (_ghostMode && typeof _coanimmAnnounce === 'function') {
        _coanimmAnnounce('Fil fant\u00f4me : rien de cet \u00e9change n\u2019est conserv\u00e9.');
    }
}

// Le bouton « fantôme » a QUITTÉ la barre du haut, et c'est volontaire.
// À cet endroit, il ne pouvait être actionné qu'APRÈS coup — donc après que
// les premiers échanges avaient déjà été écrits. La promesse « aucune trace »
// ne tient que si elle est faite avant le premier mot : le réglage vit
// désormais dans la modale de création du fil (case « Ne rien conserver »),
// et reste modifiable ensuite dans les Paramètres du fil.
// La place libérée dans la barre va au mode Live, qui prend le raccourci
// Alt+Maj+K — la famille où vivent déjà tous les panneaux de NIMM.

// ============================================
// AGENDA
// ============================================

const _TYPE_BADGE = {
    critique: '🔴',
    important: '🟠',
    normal: '🟡',
    flexible: '⚪',
};

let _agendaShowAll = false;

async function loadAgenda() {
    const url = _agendaShowAll ? '/api/rappels?all=true' : '/api/rappels';
    const r = await fetch(url);
    const rappels = await r.json();
    renderAgenda(rappels);
}

function _formatDate(dateStr) {
    if (!dateStr) return 'Sans echeance';
    try {
        const [y, m, d] = dateStr.split('T')[0].split('-');
        return d + '/' + m + '/' + y;
    } catch { return dateStr; }
}

function renderAgenda(rappels) {
    const list = document.getElementById('agenda-list');
    if (!list) return;
    if (!rappels.length) {
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.88rem;text-align:center;padding:20px 0;">Aucun rappel.</p>';
        return;
    }
    list.innerHTML = rappels.map(function(r) {
        const badge   = _TYPE_BADGE[r.type] || '⚪';
        const dateStr = _formatDate(r.date_echeance);
        const cls     = r.statut === 'perime' ? 'perime' : r.statut === 'clos' ? 'clos' : '';
        const actif   = r.statut === 'actif';
        return '<div class=\"agenda-item ' + cls + '\" data-id=\"' + r.id + '\" data-desc=\"' + _esc(r.description) + '\" data-date=\"' + (r.date_echeance || '') + '\" data-type=\"' + r.type + '\">' +
            '<span style=\"font-size:1.1rem;margin-top:1px;\">' + badge + '</span>' +
            '<div class=\"agenda-item-body\">' +
                '<div class=\"agenda-item-desc\">' + _esc(r.description) + '</div>' +
                '<div class=\"agenda-item-date\">📅 ' + dateStr + '</div>' +
                '<div class=\"agenda-edit-form hidden\" id=\"edit-form-' + r.id + '\">' +
                    '<label class=\"sr-only\" for=\"edit-desc-' + r.id + '\">Description du rappel</label>' +
                    '<input type=\"text\" id=\"edit-desc-' + r.id + '\" class=\"edit-desc\" value=\"' + _esc(r.description) + '\" placeholder=\"Description\">' +
                    '<label class=\"sr-only\" for=\"edit-date-' + r.id + '\">Date d\'échéance</label>' +
                    '<input type=\"date\" id=\"edit-date-' + r.id + '\" class=\"edit-date\" value=\"' + (r.date_echeance ? r.date_echeance.split('T')[0] : '') + '\">' +
                    '<label class=\"sr-only\" for=\"edit-type-' + r.id + '\">Importance</label>' +
                    '<select id=\"edit-type-' + r.id + '\" class=\"edit-type\">' +
                        '<option value=\"normal\"'    + (r.type==='normal'   ?'selected':'') + '>🟡 Normal</option>' +
                        '<option value=\"important\"' + (r.type==='important'?'selected':'') + '>🟠 Important</option>' +
                        '<option value=\"critique\"'  + (r.type==='critique' ?'selected':'') + '>🔴 Critique</option>' +
                        '<option value=\"flexible\"'  + (r.type==='flexible' ?'selected':'') + '>⚪ Flexible</option>' +
                    '</select>' +
                    '<div class=\"agenda-edit-actions\">' +
                        '<button class=\"btn-secondary edit-cancel-btn\" data-id=\"' + r.id + '\">Annuler</button>' +
                        '<button class=\"btn-primary  edit-save-btn\"   data-id=\"' + r.id + '\">Enregistrer</button>' +
                    '</div>' +
                '</div>' +
            '</div>' +
            '<div class=\"agenda-item-actions\">' +
                (actif ? '<button class=\"agenda-edit-btn\"  data-id=\"' + r.id + '\" aria-label=\"Modifier\">✏️</button>' : '') +
                (actif ? '<button class=\"agenda-clos-btn\"  data-id=\"' + r.id + '\" aria-label=\"Marquer comme fait\">✔</button>' : '') +
            '</div>' +
        '</div>';
    }).join('');

    // Edition inline
    list.querySelectorAll('.agenda-edit-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var id   = btn.dataset.id;
            var form = document.getElementById('edit-form-' + id);
            form.classList.toggle('hidden');
        });
    });

    list.querySelectorAll('.edit-cancel-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.getElementById('edit-form-' + btn.dataset.id)?.classList.add('hidden');
        });
    });

    list.querySelectorAll('.edit-save-btn').forEach(function(btn) {
        btn.addEventListener('click', async function() {
            var id   = btn.dataset.id;
            var form = document.getElementById('edit-form-' + id);
            var desc = form.querySelector('.edit-desc').value.trim();
            var date = form.querySelector('.edit-date').value;
            var type = form.querySelector('.edit-type').value;
            if (!desc) return;
            await fetch('/api/rappels/' + id, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ description: desc, date_echeance: date || null, type_rappel: type })
            });
            loadAgenda();
        });
    });

    list.querySelectorAll('.agenda-clos-btn').forEach(function(btn) {
        btn.addEventListener('click', async function() {
            await fetch('/api/rappels/' + btn.dataset.id, { method: 'DELETE' });
            loadAgenda();
        });
    });
}

function _esc(str) {
    return String(str == null ? '' : str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ══════════════════════════════════════════
// GALERIE IMAGES
// ══════════════════════════════════════════

let _galerieRenameId = null;

async function _galerieLoad() {
    const grid = document.getElementById('galerie-grid');
    if (!grid) return;
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:40px 0;">Chargement…</div>';
    try {
        const resp = await fetch('/api/images');
        const images = await resp.json();
        if (!images.length) {
            grid.innerHTML = '<div id="galerie-empty" style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:40px 0;">Aucune image sauvegardée.</div>';
            return;
        }
        grid.innerHTML = '';
        images.forEach(img => {
            const card = document.createElement('div');
            card.style.cssText = 'background:var(--bg-input);border:1px solid var(--border);border-radius:10px;overflow:hidden;display:flex;flex-direction:column;';
            // Les images ne sont plus toutes des .png depuis que le format suit
            // celui rendu par le modèle : on retire l'extension, quelle qu'elle soit.
            const displayName = img.filename.replace(/\.(png|jpg|jpeg|webp)$/i, '');
            // Texte alternatif : la description enregistrée si elle existe. Sinon
            // on DIT qu'il n'y en a pas — mettre la consigne à la place ferait
            // passer une intention pour une description.
            const altTexte = (img.alt || '').trim()
                ? img.alt
                : (img.prompt
                    ? 'Image sans description enregistrée. Consigne d\'origine : ' + img.prompt
                    : 'Image sans description enregistrée : ' + displayName);
            card.innerHTML = `
                <img src="/api/images/file/${encodeURIComponent(img.filename)}"
                     alt="${_esc(altTexte)}"
                     loading="lazy"
                     style="width:100%;aspect-ratio:1;object-fit:cover;display:block;cursor:pointer;"
                     title="${_esc(img.prompt || '')}"
                     data-img-id="${img.id}">
                <div style="padding:6px 8px;font-size:0.75rem;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${displayName}">${displayName}</div>
                <div style="display:flex;gap:4px;padding:0 6px 6px;flex-wrap:wrap;">
                    <button class="galerie-dl-btn" data-id="${img.id}" data-filename="${img.filename}"
                        style="flex:1;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;padding:3px 6px;font-size:0.75rem;cursor:pointer;color:var(--text-muted);"
                        aria-label="Télécharger ${displayName}">⬇</button>
                    <button class="galerie-rename-btn" data-id="${img.id}" data-filename="${img.filename}"
                        style="flex:1;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;padding:3px 6px;font-size:0.75rem;cursor:pointer;color:var(--text-muted);"
                        aria-label="Renommer ${displayName}">✏️</button>
                    <button class="galerie-del-btn" data-id="${img.id}" data-filename="${img.filename}"
                        style="flex:1;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;padding:3px 6px;font-size:0.75rem;cursor:pointer;color:var(--text-muted);"
                        aria-label="Supprimer ${displayName}">🗑️</button>
                </div>`;
            // Clic sur l'image — ouvre en plein écran dans un nouvel onglet
            card.querySelector('img').addEventListener('click', () => {
                window.open(`/api/images/file/${encodeURIComponent(img.filename)}`, '_blank');
            });
            // Télécharger
            card.querySelector('.galerie-dl-btn').addEventListener('click', async () => {
                try {
                    const r = await fetch(`/api/images/file/${encodeURIComponent(img.filename)}`);
                    const blob = await r.blob();
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = img.filename;
                    a.click();
                    URL.revokeObjectURL(a.href);
                } catch(e) {
                    window.open(`/api/images/file/${encodeURIComponent(img.filename)}`, '_blank');
                }
            });
            // Renommer
            card.querySelector('.galerie-rename-btn').addEventListener('click', () => {
                _galerieRenameId = img.id;
                const input = document.getElementById('galerie-rename-input');
                input.value = img.filename.replace(/\.png$/, '');
                document.getElementById('galerie-rename-modal').classList.remove('hidden');
                setTimeout(() => input.focus(), 50);
            });
            // Supprimer
            card.querySelector('.galerie-del-btn').addEventListener('click', async () => {
                if (!confirm(`Supprimer "${displayName}" ?`)) return;
                try {
                    await fetch(`/api/images/${img.id}`, { method: 'DELETE' });
                    _galerieLoad();
                } catch(e) { console.error('[NIMM] Erreur suppression image :', e); }
            });
            grid.appendChild(card);
        });
    } catch(e) {
        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:40px 0;">Erreur de chargement.</div>';
        console.error('[NIMM] Erreur galerie :', e);
    }
}

// Ouverture galerie
document.getElementById('toggle-galerie')?.addEventListener('click', function() {
    document.getElementById('galerie-modal').classList.remove('hidden');
    _galerieLoad();
});

// Fermeture galerie
document.getElementById('galerie-close')?.addEventListener('click', function() {
    document.getElementById('galerie-modal').classList.add('hidden');
});
document.getElementById('galerie-modal')?.addEventListener('click', function(e) {
    if (e.target === this) this.classList.add('hidden');
});

// Renommage — validation
document.getElementById('galerie-rename-ok')?.addEventListener('click', async function() {
    if (!_galerieRenameId) return;
    const newName = document.getElementById('galerie-rename-input').value.trim();
    if (!newName) return;
    try {
        await fetch(`/api/images/${_galerieRenameId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: newName })
        });
        document.getElementById('galerie-rename-modal').classList.add('hidden');
        _galerieRenameId = null;
        _galerieLoad();
    } catch(e) { console.error('[NIMM] Erreur renommage :', e); }
});
document.getElementById('galerie-rename-cancel')?.addEventListener('click', function() {
    document.getElementById('galerie-rename-modal').classList.add('hidden');
    _galerieRenameId = null;
});
document.getElementById('galerie-rename-close')?.addEventListener('click', function() {
    document.getElementById('galerie-rename-modal').classList.add('hidden');
    _galerieRenameId = null;
});
// Entrée clavier dans le champ renommage
document.getElementById('galerie-rename-input')?.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') document.getElementById('galerie-rename-ok')?.click();
    if (e.key === 'Escape') document.getElementById('galerie-rename-cancel')?.click();
});

// Bouton agenda
document.getElementById('toggle-agenda')?.addEventListener('click', function() {
    document.getElementById('agenda-modal').classList.remove('hidden');
    loadAgenda();
    setTimeout(function() { document.getElementById('agenda-form-toggle')?.focus(); }, 50);
});

// Filtres
document.getElementById('agenda-filter-actifs')?.addEventListener('click', function() {
    _agendaShowAll = false;
    document.getElementById('agenda-filter-actifs').classList.add('agenda-filter-active');
    document.getElementById('agenda-filter-actifs').setAttribute('aria-pressed', 'true');
    document.getElementById('agenda-filter-tous').classList.remove('agenda-filter-active');
    document.getElementById('agenda-filter-tous').setAttribute('aria-pressed', 'false');
    loadAgenda();
});
document.getElementById('agenda-filter-tous')?.addEventListener('click', function() {
    _agendaShowAll = true;
    document.getElementById('agenda-filter-tous').classList.add('agenda-filter-active');
    document.getElementById('agenda-filter-tous').setAttribute('aria-pressed', 'true');
    document.getElementById('agenda-filter-actifs').classList.remove('agenda-filter-active');
    document.getElementById('agenda-filter-actifs').setAttribute('aria-pressed', 'false');
    loadAgenda();
});

// Toggle formulaire ajout
document.getElementById('agenda-form-toggle')?.addEventListener('click', function() {
    var form = document.getElementById('agenda-form');
    form.classList.toggle('hidden');
    if (!form.classList.contains('hidden')) {
        document.getElementById('agenda-desc')?.focus();
    }
});
document.getElementById('agenda-form-cancel')?.addEventListener('click', function() {
    document.getElementById('agenda-form').classList.add('hidden');
    document.getElementById('agenda-desc').value = '';
    document.getElementById('agenda-date').value = '';
    document.getElementById('agenda-type').value = 'normal';
});

// Sauvegarde nouveau rappel
document.getElementById('agenda-form-save')?.addEventListener('click', async function() {
    var desc = document.getElementById('agenda-desc').value.trim();
    var date = document.getElementById('agenda-date').value;
    var type = document.getElementById('agenda-type').value;
    if (!desc) {
        document.getElementById('agenda-desc').focus();
        return;
    }
    await fetch('/api/rappels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: desc, date_echeance: date || null, type_rappel: type })
    });
    document.getElementById('agenda-desc').value = '';
    document.getElementById('agenda-date').value = '';
    document.getElementById('agenda-type').value = 'normal';
    document.getElementById('agenda-form').classList.add('hidden');
    loadAgenda();
});


// ══════════════════════════════════════════
// BIBLIOTHÈQUE
// ══════════════════════════════════════════

document.addEventListener('click', (e) => {
    if (e.target.closest('#toggle-memory')) {
        document.getElementById('memory-modal').classList.remove('hidden');
        loadMemory();
        setTimeout(() => { if (!_isMobile) document.getElementById('memory-search')?.focus(); }, 120);
    }
    if (e.target.closest('#toggle-prompt-library')) {
        document.getElementById('prompt-library-modal').classList.remove('hidden');
        loadPromptLibrary();
        setTimeout(() => { if (!_isMobile) document.getElementById('prompt-save-current-btn')?.focus(); }, 120);
    }
    if (e.target.closest('#toggle-search-conversations')) {
        document.getElementById('search-conversations-modal').classList.remove('hidden');
        loadBibliotheque();
        setTimeout(() => { if (!_isMobile) document.getElementById('search-conversations-input')?.focus(); }, 120);
    }
});

// Recherche dans la bibliothèque
let _biblioSearchTimer = null;
document.getElementById('biblio-search').addEventListener('input', (e) => {
    clearTimeout(_biblioSearchTimer);
    _biblioSearchTimer = setTimeout(() => loadBibliotheque(e.target.value.trim()), 350);
});

async function archiveThread(threadId) {
    const btn = document.getElementById('biblio-archive-btn');
    if (btn) btn.disabled = true;

    // Afficher le loader bretzel grand format
    const overlay   = document.getElementById('archive-loader-overlay');
    const container = document.getElementById('archive-bretzel-container');
    const svg       = _buildBretzelSVG(80, 55);
    container.innerHTML = '';
    container.appendChild(svg);
    overlay.classList.remove('hidden');
    const _fakeLoader = {};
    // Attendre une frame + 50ms pour que le SVG soit dans le DOM avant l'animation
    await new Promise(r => setTimeout(r, 50));
    _startBretzelAnim(svg, _fakeLoader);

    const _minDisplay = new Promise(r => setTimeout(r, 600));

    try {
        const r = await fetch('/api/bibliotheque', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ thread_id: threadId }),
        });
        if (!r.ok) throw new Error('Erreur serveur');
        const data = await r.json();
        console.log(`[BIBLIO] Archivé : ${data.titre}`);
    } catch (e) {
        console.error('[BIBLIO] Erreur archivage :', e);
        alert('Erreur lors de l\'archivage. Vérifie la console.');
    } finally {
        await _minDisplay;
        if (_fakeLoader._cancelAnim) _fakeLoader._cancelAnim();
        overlay.classList.add('hidden');
        if (btn) btn.disabled = false;
    }
}

async function loadBibliotheque(query = '') {
    const list = document.getElementById('biblio-list');
    if (!list) return;

    list.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;">Chargement…</div>';

    try {
        const url = query
            ? `/api/bibliotheque/search?q=${encodeURIComponent(query)}`
            : '/api/bibliotheque';
        const entries = await fetch(url).then(r => r.json());

        list.innerHTML = '';
        if (!entries.length) {
            return;
        }
        entries.forEach(entry => list.appendChild(renderBiblioEntry(entry)));
    } catch (e) {
        list.innerHTML = '<div style="padding:12px;color:#cf6f6f;text-align:center;">Erreur de chargement.</div>';
    }
}

function renderBiblioEntry(entry) {
    const div = document.createElement('div');
    div.className = 'biblio-entry';
    div.style.cssText = `
        border:1px solid var(--border);border-radius:8px;
        margin-bottom:10px;overflow:hidden;background:var(--bg-input);
    `;

    const dateStr = entry.date_conversation
        ? new Date(entry.date_conversation).toLocaleDateString('fr-FR')
        : new Date(entry.date_creation).toLocaleDateString('fr-FR');

    const tagsHtml = entry.tags
        ? entry.tags.split(',').map(t => t.trim()).filter(Boolean)
            .map(t => `<span style="background:#1a2a1a;color:#6fcf97;padding:2px 7px;border-radius:10px;font-size:0.75rem;">${t}</span>`)
            .join(' ')
        : '';

    const catsHtml = entry.categories
        ? entry.categories.split(',').map(c => c.trim()).filter(Boolean).join(' ')
        : '';

    // ── Contenu développé : os_riche si disponible, sinon resume_texte ──
    let resumeContent = '';
    if (entry.os_riche) {
        try {
            const os = JSON.parse(entry.os_riche);
            const parts = [];
            if (os.fil_conducteur) {
                parts.push(`<div style="font-weight:600;color:var(--text-primary);margin-bottom:6px;">🧵 ${escapeHtml(os.fil_conducteur)}</div>`);
            }
            if (os.climat) {
                parts.push(`<div style="font-style:italic;color:var(--text-muted);font-size:0.8rem;margin-bottom:10px;">${escapeHtml(os.climat)}</div>`);
            }
            if (Array.isArray(os.noeuds) && os.noeuds.length) {
                parts.push(os.noeuds.map(n => `<div style="margin-bottom:6px;padding-left:10px;border-left:2px solid var(--border);">${escapeHtml(n)}</div>`).join(''));
            }
            if (Array.isArray(os.positions) && os.positions.length) {
                parts.push(`<div style="margin-top:8px;font-weight:600;">Positions</div>` +
                    os.positions.map(p => `<div style="padding-left:10px;">→ ${escapeHtml(p)}</div>`).join(''));
            }
            if (Array.isArray(os.questions_ouvertes) && os.questions_ouvertes.length) {
                parts.push(`<div style="margin-top:8px;font-weight:600;">Questions ouvertes</div>` +
                    os.questions_ouvertes.map(q => `<div style="padding-left:10px;">? ${escapeHtml(q)}</div>`).join(''));
            }
            if (Array.isArray(os.formulations_cles) && os.formulations_cles.length) {
                parts.push(`<div style="margin-top:8px;font-weight:600;">Formulations clés</div>` +
                    os.formulations_cles.map(f => `<div style="padding-left:10px;font-style:italic;">"${escapeHtml(f)}"</div>`).join(''));
            }
            if (Array.isArray(os.ramifications) && os.ramifications.length) {
                parts.push(`<div style="margin-top:8px;font-weight:600;">Pistes non explorées</div>` +
                    os.ramifications.map(r => `<div style="padding-left:10px;color:var(--text-muted);">↪ ${escapeHtml(r)}</div>`).join(''));
            }
            resumeContent = parts.join('');
        } catch(e) {
            resumeContent = `<div style="white-space:pre-wrap;">${entry.resume_texte || 'Aucun résumé.'}</div>`;
        }
    } else {
        resumeContent = `<div style="white-space:pre-wrap;">${entry.resume_texte || 'Aucun résumé.'}</div>`;
    }

    div.innerHTML = `
        <div class="biblio-header" style="padding:10px 14px;cursor:pointer;display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
            <div style="flex:1;">
                <div class="biblio-titre" style="font-weight:600;font-size:0.95rem;margin-bottom:4px;">${catsHtml ? catsHtml + ' ' : ''}${entry.titre}</div>
                <div style="color:var(--text-muted);font-size:0.78rem;margin-bottom:6px;">📅 ${dateStr}</div>
                <div class="biblio-tags" style="display:flex;flex-wrap:wrap;gap:4px;">${tagsHtml}</div>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0;align-items:center;">
                <button class="biblio-reprendre-btn" title="Reprendre dans un nouveau fil" style="background:none;border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:0.78rem;padding:3px 8px;color:var(--text-muted);white-space:nowrap;">▶ Reprendre</button>
                <button class="biblio-edit-btn" title="Éditer" style="background:none;border:none;cursor:pointer;font-size:1rem;opacity:0.7;">✏️</button>
                <button class="biblio-delete-btn" title="Supprimer" style="background:none;border:none;cursor:pointer;font-size:1rem;opacity:0.7;">🗑️</button>
            </div>
        </div>
        <div class="biblio-resume hidden" style="padding:0 14px 14px;color:var(--text-muted);font-size:0.85rem;line-height:1.6;border-top:1px solid var(--border);">${resumeContent}</div>
    `;

    // Toggle résumé
    div.querySelector('.biblio-header').addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        div.querySelector('.biblio-resume').classList.toggle('hidden');
    });

    // Supprimer entrée
    div.querySelector('.biblio-delete-btn').addEventListener('click', async () => {
        const ok = await confirmModal(`Supprimer "${entry.titre}" de la bibliothèque ?`);
        if (!ok) return;
        await fetch(`/api/bibliotheque/${entry.id}`, { method: 'DELETE' });
        div.remove();
    });

    // Éditer titre + tags
    div.querySelector('.biblio-edit-btn').addEventListener('click', async (e) => {
        e.stopPropagation();
        const newTitre = await promptModal('Titre', entry.titre);
        if (newTitre === null) return;
        const newTags = await promptModal('Tags (séparés par des virgules)', entry.tags);
        if (newTags === null) return;
        await fetch(`/api/bibliotheque/${entry.id}`, {
            method:  'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ titre: newTitre, tags: newTags }),
        });
        entry.titre = newTitre;
        entry.tags  = newTags;
        div.querySelector('.biblio-titre').textContent = newTitre;
        // Rafraîchir les tags
        const tagsHtml2 = newTags.split(',').map(t => t.trim()).filter(Boolean)
            .map(t => `<span style="background:#1a2a1a;color:#6fcf97;padding:2px 7px;border-radius:10px;font-size:0.75rem;">${t}</span>`)
            .join(' ');
        div.querySelector('.biblio-tags').innerHTML = tagsHtml2;
    });

    // Reprendre dans un nouveau fil
    div.querySelector('.biblio-reprendre-btn').addEventListener('click', async (e) => {
        e.stopPropagation();
        const btn = e.currentTarget;
        btn.textContent = '⏳';
        btn.disabled = true;
        try {
            const res = await fetch(`/api/bibliotheque/${entry.id}/reprendre`, { method: 'POST' });
            if (!res.ok) throw new Error(`Erreur serveur : ${res.status}`);
            const { thread_id } = await res.json();
            // Fermer la modale recherches
            document.getElementById('search-conversations-modal').classList.add('hidden');
            // Naviguer vers le nouveau fil
            await loadThreads();
            await selectThread(thread_id);
        } catch (err) {
            console.error('[BIBLIO] Erreur reprise archive :', err);
            alert('❌ Erreur lors de la reprise : ' + err.message);
            btn.textContent = '▶ Reprendre';
            btn.disabled = false;
        }
    });

    return div;
}

// ══════════════════════════════════════════
// BIBLIOTHÈQUE DE PROMPTS
// ══════════════════════════════════════════

// Icônes et libellés affichés pour chaque type d'élément de la Promptothèque.
const PROMPT_TYPE_INFO = {
    prompt:      { icone: '📝', libelle: 'Prompt' },
    gabarit:     { icone: '📄', libelle: 'Gabarit de document' },
    script:      { icone: '🐍', libelle: 'Script Python' },
    tache_agent: { icone: '🤖', libelle: 'Tâche agent' },
};

async function loadPromptLibrary() {
    const list = document.getElementById('prompt-library-list');
    const filtre = document.getElementById('prompt-type-filter')?.value || '';
    list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Chargement…</p>';
    try {
        const url = filtre ? `/api/prompts?type=${encodeURIComponent(filtre)}` : '/api/prompts';
        const res = await fetch(url);
        if (!res.ok) throw new Error(`Erreur serveur : ${res.status}`);
        const { prompts } = await res.json();
        const ids = Object.keys(prompts || {});
        if (ids.length === 0) {
            list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Aucun élément enregistré pour le moment.</p>';
            return;
        }
        ids.sort((a, b) => (prompts[a].label || '').localeCompare(prompts[b].label || ''));
        list.innerHTML = '';
        ids.forEach(id => list.appendChild(renderPromptEntry(id, prompts[id])));
    } catch (err) {
        console.error('[PROMPTS] Erreur chargement :', err);
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">❌ Erreur de chargement.</p>';
    }
}

document.getElementById('prompt-type-filter').addEventListener('change', () => loadPromptLibrary());

function renderPromptEntry(id, entry) {
    const div = document.createElement('div');
    div.className = 'biblio-entry';
    div.style.padding = '10px 14px';
    div.style.display = 'flex';
    div.style.justifyContent = 'space-between';
    div.style.alignItems = 'flex-start';
    div.style.gap = '8px';

    const info = document.createElement('div');
    info.style.flex = '1';
    const typeInfo = PROMPT_TYPE_INFO[entry.type] || PROMPT_TYPE_INFO.prompt;
    const titre = document.createElement('div');
    titre.style.fontWeight = '600';
    titre.style.fontSize = '0.95rem';
    titre.style.marginBottom = '4px';
    titre.textContent = `${typeInfo.icone} ${entry.label || '(sans titre)'} — ${typeInfo.libelle}`;
    const extrait = document.createElement('div');
    extrait.style.color = 'var(--text-muted)';
    extrait.style.fontSize = '0.82rem';
    extrait.style.whiteSpace = 'pre-wrap';
    const texte = entry.text || '';
    extrait.textContent = texte.length > 160 ? texte.slice(0, 160) + '…' : texte;
    info.appendChild(titre);
    info.appendChild(extrait);

    const actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.flexDirection = 'column';
    actions.style.gap = '4px';

    const useBtn = document.createElement('button');
    useBtn.title = 'Utiliser ce prompt';
    useBtn.setAttribute('aria-label', `Utiliser le prompt ${entry.label || ''}`);
    useBtn.style.background = 'none';
    useBtn.style.border = '1px solid var(--border)';
    useBtn.style.borderRadius = '6px';
    useBtn.style.cursor = 'pointer';
    useBtn.style.fontSize = '0.78rem';
    useBtn.style.padding = '3px 8px';
    useBtn.style.color = 'var(--text-muted)';
    useBtn.textContent = '▶ Utiliser';
    useBtn.addEventListener('click', () => usePromptFromLibrary(entry.text || ''));

    const delBtn = document.createElement('button');
    delBtn.title = 'Supprimer';
    delBtn.setAttribute('aria-label', `Supprimer le prompt ${entry.label || ''}`);
    delBtn.style.background = 'none';
    delBtn.style.border = 'none';
    delBtn.style.cursor = 'pointer';
    delBtn.style.fontSize = '1rem';
    delBtn.style.opacity = '0.7';
    delBtn.textContent = '🗑️';
    delBtn.addEventListener('click', async () => {
        if (!confirm(`Supprimer le prompt « ${entry.label || ''} » ?`)) return;
        try {
            const res = await fetch(`/api/prompts/${id}`, { method: 'DELETE' });
            if (!res.ok) throw new Error(`Erreur serveur : ${res.status}`);
            div.remove();
        } catch (err) {
            console.error('[PROMPTS] Erreur suppression :', err);
            alert('❌ Erreur lors de la suppression : ' + err.message);
        }
    });

    actions.appendChild(useBtn);
    actions.appendChild(delBtn);
    div.appendChild(info);
    div.appendChild(actions);
    return div;
}

// Remplace les {{variable}} d'un prompt par des valeurs demandées à l'utilisateur,
// insère le résultat dans la zone de saisie, et ferme la bibliothèque.
function usePromptFromLibrary(text) {
    const noms = [];
    const vus = new Set();
    text.replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (_, nom) => {
        if (!vus.has(nom)) { vus.add(nom); noms.push(nom); }
        return '';
    });

    let resultat = text;
    for (const nom of noms) {
        const valeur = window.prompt(`Valeur pour « ${nom} » :`, '');
        if (valeur === null) return; // annulé
        const motif = new RegExp(`\\{\\{\\s*${nom.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\}\\}`, 'g');
        resultat = resultat.replace(motif, valeur);
    }

    const input = document.getElementById('user-input');
    input.value = resultat;
    input.dispatchEvent(new Event('input'));
    document.getElementById('prompt-library-modal').classList.add('hidden');
    if (!_isMobile) input.focus();
}

document.getElementById('prompt-save-current-btn').addEventListener('click', async () => {
    const input = document.getElementById('user-input');
    const texte = (input.value || '').trim();
    const type = document.getElementById('prompt-save-type')?.value || 'prompt';
    if (!texte) {
        alert('La zone de saisie est vide : écrivez le contenu à enregistrer.');
        return;
    }
    const typeInfo = PROMPT_TYPE_INFO[type] || PROMPT_TYPE_INFO.prompt;
    const label = window.prompt(`Nom de ce ${typeInfo.libelle.toLowerCase()} :`, '');
    if (label === null || !label.trim()) return;
    try {
        const res = await fetch('/api/prompts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label: label.trim(), text: texte, type })
        });
        if (!res.ok) throw new Error(`Erreur serveur : ${res.status}`);
        await loadPromptLibrary();
    } catch (err) {
        console.error('[PROMPTS] Erreur enregistrement :', err);
        alert('❌ Erreur lors de l\'enregistrement : ' + err.message);
    }
});

// ══════════════════════════════════════════
// RECHERCHE DANS LES CONVERSATIONS (par sens)
// ══════════════════════════════════════════

const ROLE_LABELS = { user: 'Vous', assistant: 'NIMM' };

async function runConversationSearch(query) {
    const list = document.getElementById('search-conversations-results');
    query = (query || '').trim();
    if (!query) {
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Tapez quelques mots pour chercher dans vos conversations.</p>';
        return;
    }
    list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Recherche…</p>';
    try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&k=8`);
        if (!res.ok) throw new Error(`Erreur serveur : ${res.status}`);
        const { resultats } = await res.json();
        if (!resultats || resultats.length === 0) {
            list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Aucun résultat.</p>';
            return;
        }
        list.innerHTML = '';
        resultats.forEach(r => list.appendChild(renderSearchResult(r)));
    } catch (err) {
        console.error('[RECHERCHE] Erreur recherche :', err);
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">❌ Erreur lors de la recherche.</p>';
    }
}

function renderSearchResult(r) {
    const div = document.createElement('button');
    div.className = 'biblio-entry';
    div.style.display = 'block';
    div.style.width = '100%';
    div.style.textAlign = 'left';
    div.style.padding = '10px 14px';
    div.style.background = 'none';
    div.style.border = '1px solid var(--border)';
    div.style.borderRadius = '8px';
    div.style.marginBottom = '8px';
    div.style.cursor = 'pointer';
    div.style.color = 'var(--text)';

    const titre = document.createElement('div');
    titre.style.fontWeight = '600';
    titre.style.fontSize = '0.9rem';
    titre.style.marginBottom = '4px';
    const role = ROLE_LABELS[r.role] || r.role || '';
    titre.textContent = `${r.thread_name || '(fil sans nom)'} — ${role}`;

    const extrait = document.createElement('div');
    extrait.style.color = 'var(--text-muted)';
    extrait.style.fontSize = '0.82rem';
    extrait.style.whiteSpace = 'pre-wrap';
    extrait.textContent = r.content || '';

    div.appendChild(titre);
    div.appendChild(extrait);

    div.addEventListener('click', async () => {
        document.getElementById('search-conversations-modal').classList.add('hidden');
        await selectThread(r.thread_id);
    });

    return div;
}

let _searchConversationsTimer = null;
document.getElementById('search-conversations-input').addEventListener('input', (e) => {
    clearTimeout(_searchConversationsTimer);
    const valeur = e.target.value;
    _searchConversationsTimer = setTimeout(() => runConversationSearch(valeur), 400);
});

// ── Recherche textuelle exacte, section "Recherches" ──
let _searchTextTimer = null;

document.getElementById('search-text-input')?.addEventListener('input', (e) => {
    clearTimeout(_searchTextTimer);
    const val = e.target.value;
    _searchTextTimer = setTimeout(() => runTextSearch(val), 350);
});

async function runTextSearch(query) {
    const list = document.getElementById('search-text-results');
    query = (query || '').trim();
    if (!query) {
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Tapez un mot pour chercher dans le texte exact de vos messages.</p>';
        return;
    }
    list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Recherche…</p>';
    try {
        const res = await fetch(`/api/search/text?q=${encodeURIComponent(query)}&k=20`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const { resultats } = await res.json();
        if (!resultats || !resultats.length) {
            list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Aucun résultat.</p>';
            return;
        }
        list.innerHTML = '';
        resultats.forEach(r => list.appendChild(_renderTextResult(r, query)));
    } catch (err) {
        console.error('[RECHERCHE TEXTE] Erreur :', err);
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">❌ Erreur lors de la recherche.</p>';
    }
}

function _renderTextResult(r, query) {
    const div = document.createElement('button');
    div.className = 'biblio-entry';
    div.style.cssText = 'display:block;width:100%;text-align:left;padding:10px 14px;background:none;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;cursor:pointer;color:var(--text);';

    const titre = document.createElement('div');
    titre.style.cssText = 'font-weight:600;font-size:0.9rem;margin-bottom:4px;';
    const role = r.role === 'user' ? 'Vous' : 'NIMM';
    titre.textContent = `${r.thread_name || '(fil sans nom)'} — ${role}`;

    // Extrait avec le mot recherché mis en évidence (texte brut, accessible)
    const content = r.content || '';
    const idx = content.toLowerCase().indexOf(query.toLowerCase());
    let extrait = content;
    if (idx !== -1) {
        const debut = Math.max(0, idx - 60);
        const fin   = Math.min(content.length, idx + query.length + 60);
        extrait = (debut > 0 ? '…' : '') + content.slice(debut, fin) + (fin < content.length ? '…' : '');
    } else {
        extrait = content.slice(0, 140) + (content.length > 140 ? '…' : '');
    }

    const texte = document.createElement('div');
    texte.style.cssText = 'font-size:0.82rem;color:var(--text-muted);white-space:pre-wrap;';
    texte.textContent = extrait;

    div.appendChild(titre);
    div.appendChild(texte);

    div.addEventListener('click', async () => {
        document.getElementById('search-conversations-modal').classList.add('hidden');
        await selectThread(r.thread_id);
    });

    return div;
}

// ── Recherche mémoire (triplets), section "Recherches" ──
let _memorySearchGlobalCache = null;

async function runMemorySearchGlobal(query) {
    const list = document.getElementById('memory-search-global-results');
    query = (query || '').trim();
    if (!query) {
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Tapez quelques mots pour chercher dans votre mémoire.</p>';
        return;
    }
    list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Recherche…</p>';
    try {
        if (!_memorySearchGlobalCache) {
            _memorySearchGlobalCache = await fetch('/api/memory/triplets').then(r => r.json());
        }
        const q = query.toLowerCase();
        const resultats = _memorySearchGlobalCache.filter(m =>
            [m.sujet, m.predicat, m.valeur, m.categorie].some(v => v?.toLowerCase().includes(q))
        );
        if (!resultats.length) {
            list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Aucun résultat.</p>';
            return;
        }
        list.innerHTML = '';
        resultats.slice(0, 30).forEach(m => list.appendChild(renderMemorySearchGlobalResult(m)));
    } catch (err) {
        console.error('[RECHERCHE MÉMOIRE] Erreur :', err);
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">❌ Erreur lors de la recherche.</p>';
    }
}

function renderMemorySearchGlobalResult(m) {
    const div = document.createElement('div');
    div.style.cssText = 'padding:8px 10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;font-size:0.85rem;';
    const cat = m.categorie ? `<span style="color:var(--text-muted);">[${escapeHtml(m.categorie)}]</span> ` : '';
    div.innerHTML = `${cat}<strong>${escapeHtml(m.sujet || '')}</strong> — ${escapeHtml(m.predicat || '')} : ${escapeHtml(m.valeur || '')}`;
    return div;
}

let _memorySearchGlobalTimer = null;
document.getElementById('memory-search-global').addEventListener('input', (e) => {
    clearTimeout(_memorySearchGlobalTimer);
    const valeur = e.target.value;
    _memorySearchGlobalTimer = setTimeout(() => runMemorySearchGlobal(valeur), 400);
});


// Modale suppression enrichie — retourne 'archive', 'delete', ou null
function deleteThreadModal(threadName) {
    return new Promise((resolve) => {
        const modal   = document.getElementById('delete-thread-modal');
        const archive = document.getElementById('delete-archive-btn');
        const confirm = document.getElementById('delete-confirm-btn');
        const cancel  = document.getElementById('delete-cancel-btn');
        const closes  = modal.querySelectorAll('.close-modal');

        const _delPrevFocus = document.activeElement;
        modal.classList.remove('hidden');
        setTimeout(() => { document.getElementById('delete-cancel-btn')?.focus(); }, 50);

        const cleanup = (result) => {
            modal.classList.add('hidden');
            setTimeout(() => { _delPrevFocus?.focus(); }, 0);
            archive.replaceWith(archive.cloneNode(true));
            confirm.replaceWith(confirm.cloneNode(true));
            cancel.replaceWith(cancel.cloneNode(true));
            resolve(result);
        };

        document.getElementById('delete-archive-btn').addEventListener('click', () => cleanup('archive'), { once: true });
        document.getElementById('delete-confirm-btn').addEventListener('click', () => cleanup('delete'),  { once: true });
        document.getElementById('delete-cancel-btn').addEventListener('click',  () => cleanup(null),     { once: true });
        closes.forEach(b => b.addEventListener('click', () => cleanup(null), { once: true }));
    });
}

async function loadMemory() {
    const list = document.getElementById('memory-list');
    list.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;">Chargement...</div>';

    // Reset du filtre à chaque ouverture — Permanents par défaut
    _memFilter = 'PERMANENT';

    // Barre de filtres — créée une seule fois
    if (!document.getElementById('memory-filters')) {
        const filterBar = document.createElement('div');
        filterBar.id        = 'memory-filters';
        filterBar.className = 'memory-filters';
        filterBar.innerHTML = `
            <button class="mem-filter-btn active" data-filter="PERMANENT" aria-pressed="true"><span aria-hidden="true">⭐ </span>Permanents</button>
            <button class="mem-filter-btn" data-filter="identite" aria-pressed="false"><span aria-hidden="true">🧍 </span>Qui</button>
            <button class="mem-filter-btn" data-filter="all" aria-pressed="false">Tout</button>`;
        filterBar.querySelectorAll('.mem-filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                filterBar.querySelectorAll('.mem-filter-btn').forEach(b => {
                    b.classList.remove('active');
                    b.setAttribute('aria-pressed', 'false');
                });
                btn.classList.add('active');
                btn.setAttribute('aria-pressed', 'true');
                _memFilter = btn.dataset.filter;
                renderMemory(_allMemory);
            });
        });
        list.parentNode.insertBefore(filterBar, list);
    }

    // Synchroniser l'état visuel des boutons avec _memFilter
    const filterBar = document.getElementById('memory-filters');
    if (filterBar) {
        filterBar.querySelectorAll('.mem-filter-btn').forEach(btn => {
            const isActive = btn.dataset.filter === _memFilter;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
    }

    // Bouton audit memoire
    const auditBtn = document.getElementById('btn-audit-memory');
    if (auditBtn && !auditBtn._bound) {
        auditBtn.addEventListener('click', async function() {
            // Fermer la modale et afficher le loader dans le chat
            document.getElementById('memory-modal').classList.add('hidden');
            showLoader();
            auditBtn.disabled = true;
            try {
                const res  = await fetch('/api/memory/audit', { method: 'POST' });
                const data = await res.json();
                removeLoader();

                if (data.count === -1) {
                    appendAssistantMessage('⚠️ Impossible de lancer l\'audit — aucun fournisseur configuré.', 'neutre', false);
                } else if (data.count === 0) {
                    appendAssistantMessage('✅ Mémoire cohérente — rien à clarifier.', 'neutre', false);
                } else if (currentThreadId) {
                    await fetch(`/api/threads/${currentThreadId}/messages`, {
                        method:  'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body:    JSON.stringify({ role: 'assistant', content: data.message })
                    });
                    appendAssistantMessage(data.message, 'neutre', false);
                }
                document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
            } catch(e) {
                removeLoader();
                appendAssistantMessage('⚠️ Erreur lors de l\'audit mémoire.', 'neutre', false);
            } finally {
                auditBtn.disabled = false;
            }
        });
        auditBtn._bound = true;
    }

    // Onglets mémoire — setup une seule fois
    const memTabs = document.getElementById('memory-tabs');
    if (memTabs && !memTabs._tabBound) {
        memTabs.querySelectorAll('.mem-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                memTabs.querySelectorAll('.mem-tab-btn').forEach(b => {
                    b.classList.remove('active');
                    b.setAttribute('aria-selected', 'false');
                });
                btn.classList.add('active');
                btn.setAttribute('aria-selected', 'true');
                ['triplets','index','carnet','anecdotes'].forEach(t => {
                    const s = document.getElementById('mem-section-' + t);
                    if (s) s.classList.toggle('hidden', t !== btn.dataset.tab);
                });
                if (btn.dataset.tab === 'index')          loadMemoryIndex();
                else if (btn.dataset.tab === 'carnet')    loadMemoryCarnet();
                else if (btn.dataset.tab === 'anecdotes') loadMemoryAnecdotes();
            });
        });
        memTabs._tabBound = true;
    }
    // Reset sur Triplets à chaque ouverture
    if (memTabs) {
        memTabs.querySelectorAll('.mem-tab-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.tab === 'triplets');
            b.setAttribute('aria-selected', b.dataset.tab === 'triplets' ? 'true' : 'false');
        });
        ['triplets','index','carnet','anecdotes'].forEach(t => {
            const s = document.getElementById('mem-section-' + t);
            if (s) s.classList.toggle('hidden', t !== 'triplets');
        });
    }

    // Recherche
    const search = document.getElementById('memory-search');
    if (search && !search._bound) {
        search.addEventListener('input', () => renderMemory(_allMemory));
        search._bound = true;
    }

    try {
        const r    = await fetch('/api/memory/triplets');
        _allMemory = await r.json();
        renderMemory(_allMemory);
    } catch(e) {
        list.innerHTML = '<div style="color:var(--text-muted);padding:12px;">Erreur de chargement.</div>';
    }
}

let _allMemory = [];

async function loadMemoryIndex() {
    const el = document.getElementById('memory-index-content');
    el.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Chargement...</div>';
    try {
        const data = await (await fetch('/api/memory/index-theme')).json();
        const themes = Object.entries(data);
        if (!themes.length) { el.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Index vide.</div>'; return; }
        el.innerHTML = themes.map(([theme, entries]) =>
            '<div style="margin-bottom:14px;">' +
            '<div style="font-size:0.78rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">' + theme + '</div>' +
            '<div style="display:flex;flex-wrap:wrap;gap:6px;">' +
            entries.map(e => '<span style="padding:2px 10px;border-radius:10px;border:1px solid var(--border);font-size:0.82rem;color:var(--text);">' + e + '</span>').join('') +
            '</div></div>'
        ).join('');
    } catch(e) { el.innerHTML = '<div style="color:var(--text-muted);padding:12px;">Erreur de chargement.</div>'; }
}

async function loadMemoryCarnet() {
    const el = document.getElementById('memory-carnet-content');
    el.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Chargement...</div>';
    if (!currentThreadId) { el.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Aucun fil sélectionné.</div>'; return; }
    try {
        const notes = await (await fetch('/api/threads/' + currentThreadId + '/carnet')).json();
        if (!notes.length) { el.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Carnet vide pour ce fil.</div>'; return; }
        el.innerHTML = notes.map(n =>
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border);gap:10px;">' +
            '<div style="font-size:0.84rem;color:var(--text);flex:1;white-space:pre-wrap;">' + n.content + '</div>' +
            '<button onclick="deleteCarnetNote(' + n.note_number + ')" aria-label="Supprimer cette note" style="flex-shrink:0;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:1rem;">🗑️</button>' +
            '</div>'
        ).join('');
    } catch(e) { el.innerHTML = '<div style="color:var(--text-muted);padding:12px;">Erreur de chargement.</div>'; }
}

async function loadMemoryAnecdotes() {
    const el = document.getElementById('memory-anecdotes-content');
    el.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Chargement...</div>';
    try {
        const items = await (await fetch('/api/anecdotes')).json();
        if (!items.length) { el.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Aucune anecdote.</div>'; return; }
        el.innerHTML = items.map(a =>
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border);gap:10px;">' +
            '<div style="flex:1;">' +
            '<div style="font-size:0.85rem;font-weight:500;color:var(--text);">' + a.titre + '</div>' +
            (a.contenu ? '<div style="font-size:0.8rem;color:var(--text-muted);margin-top:3px;">' + a.contenu + '</div>' : '') +
            (a.tags ? '<div style="font-size:0.75rem;color:var(--accent);margin-top:4px;">' + a.tags + '</div>' : '') +
            '</div>' +
            '<button onclick="deleteAnecdote(' + a.id + ')" aria-label="Supprimer cette anecdote" style="flex-shrink:0;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:1rem;">🗑️</button>' +
            '</div>'
        ).join('');
    } catch(e) { el.innerHTML = '<div style="color:var(--text-muted);padding:12px;">Erreur de chargement.</div>'; }
}

async function deleteCarnetNote(noteNumber) {
    if (!currentThreadId) return;
    await fetch('/api/threads/' + currentThreadId + '/carnet/' + noteNumber, { method: 'DELETE' });
    loadMemoryCarnet();
}

async function deleteAnecdote(id) {
    await fetch('/api/anecdotes/' + id, { method: 'DELETE' });
    loadMemoryAnecdotes();
}
let _memFilter  = 'all';

const PROFONDEUR_ICONS = { 1:'💖', 2:'📖', 3:'🏡', 4:'🌍', 5:'📌' };
const TYPE_LABEL = {
    'TRAIT':     'Trait',
    'RELATION':  'Relation',
    'EVENEMENT': 'Événement',
};

function renderMemory(memories) {
    const list  = document.getElementById('memory-list');
    const empty = document.getElementById('memory-empty');
    const query = (document.getElementById('memory-search')?.value || '').toLowerCase();

    // Filtrage texte + type
    let filtered = query
        ? memories.filter(m =>
            [m.sujet, m.predicat, m.valeur, m.categorie]
                .some(v => v?.toLowerCase().includes(query)))
        : memories;

    if (_memFilter === 'PERMANENT') {
        filtered = filtered.filter(m => m.type_temporal === 'permanent');
    } else if (_memFilter === 'identite' || _memFilter === 'activite') {
        filtered = filtered.filter(m => (m.memoire_type || 'identite') === _memFilter);
    } else if (_memFilter !== 'all') {
        filtered = filtered.filter(m => (m.type_mem || 'TRAIT') === _memFilter);
    }

    list.innerHTML = '';

    if (!filtered.length) {
        return;
    }

    const CATEGORIE_LABELS = {
        'famille':    '👨‍👩‍👧 Famille',
        'loisirs':    '🎮 Loisirs',
        'profession': '💼 Travail',
        'quotidien':  '🏡 Vie quotidienne',
        'sante':      '🏥 Santé',
        'croyances':  '🕯️ Croyances',
        'amities':    '🤝 Amitiés',
        'autre':      '📌 Divers',
    };
    const CATEGORIE_ORDER = ['famille', 'profession', 'loisirs', 'quotidien', 'sante', 'croyances', 'amities', 'autre'];

    function sortByProfondeur(items) {
        return items.slice().sort((a, b) => (a.profondeur || 5) - (b.profondeur || 5));
    }

    function buildRow(sujet, m) {
        const typeKey  = (m.type_mem || 'TRAIT');
        const typeClass = typeKey.toLowerCase();
        const typeLabel = TYPE_LABEL[typeKey] || typeKey;
        const profIcon  = PROFONDEUR_ICONS[m.profondeur] || '📌';
        const isPermanent = m.type_temporal === 'permanent';
        const poidsBar  = isPermanent ? '⭐' : (m.poids >= 2.0 ? '▓▓▓' : m.poids >= 1.0 ? '▓▓░' : '▓░░');
        const poidsText = isPermanent ? 'permanent' : (m.poids >= 2.0 ? 'fort' : m.poids >= 1.0 ? 'moyen' : 'faible');
        const rowLabel  = `${escapeHtml(sujet)} — ${escapeHtml(m.predicat || '')} — ${escapeHtml(m.valeur || '')}, ${poidsText}`;
        const row = document.createElement('div');
        row.className   = 'memory-row';
        row.dataset.key = m.key;
        row.dataset.locked = m.locked ? 'true' : 'false';
        row.setAttribute('aria-label', rowLabel);
        row.innerHTML = `
            <span class="mem-prof" aria-hidden="true" title="Profondeur ${m.profondeur || 5}">${profIcon}</span>
            <span class="mem-type mem-type--${typeClass}" aria-hidden="true">${typeLabel}</span>
            <span class="mem-poids" aria-hidden="true" title="Poids: ${(m.poids||1).toFixed(2)}">${poidsBar}</span>
            <span class="memory-predicat">${escapeHtml(m.predicat || '')}</span>
            <span class="memory-valeur">${escapeHtml(m.valeur || '')}</span>
            <div class="memory-row-actions">
                <button aria-label="${m.locked ? 'Déverrouiller' : 'Verrouiller'} ${escapeHtml(m.predicat || '')} de ${escapeHtml(sujet)}" title="${m.locked ? 'Déverrouiller' : 'Verrouiller'}" onclick="toggleLockMemory('${m.key}')">${m.locked ? '🔒' : '🔓'}</button>
                <button aria-label="Modifier ${escapeHtml(m.predicat || '')} de ${escapeHtml(sujet)}" onclick="editMemory('${m.key}', '${escapeAttr(m.valeur)}')">✏️</button>
                <button aria-label="Supprimer ${escapeHtml(m.predicat || '')} de ${escapeHtml(sujet)}" onclick="deleteMemory('${m.key}')">🗑️</button>
            </div>`;
        return row;
    }

    function buildPersonCard(sujet, items) {
        const card = document.createElement('div');
        card.className = 'memory-card';
        card.innerHTML = `<div class="memory-card-header"><span aria-hidden="true">👤 </span>${escapeHtml(sujet)}</div>`;

        // Identite — affichee directement en tete de fiche, sans etiquette de sous-categorie
        const identite = sortByProfondeur(items.filter(m => (m.memoire_type || '') === 'identite'));
        identite.forEach(m => card.appendChild(buildRow(sujet, m)));

        // Tout le reste (activite incluse — elle a deja sa propre categorie) → sous-sections
        const reste = items.filter(m => (m.memoire_type || '') !== 'identite');
        const parCateg = {};
        reste.forEach(m => {
            const cat = m.categorie || 'autre';
            if (!parCateg[cat]) parCateg[cat] = [];
            parCateg[cat].push(m);
        });

        const catsPresentes = Object.keys(parCateg).sort((a, b) => {
            const ia = CATEGORIE_ORDER.indexOf(a);
            const ib = CATEGORIE_ORDER.indexOf(b);
            return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
        });

        catsPresentes.forEach(cat => {
            const label = CATEGORIE_LABELS[cat] || `📌 ${cat}`;
            const [icon, ...rest] = label.split(' ');
            const titre = rest.join(' ') || label;
            const sub = document.createElement('div');
            sub.className = 'memory-subsection-title';
            sub.innerHTML = `<span aria-hidden="true">${icon}</span> ${escapeHtml(titre)}`;
            card.appendChild(sub);
            sortByProfondeur(parCateg[cat]).forEach(m => card.appendChild(buildRow(sujet, m)));
        });

        return card;
    }

    // Regroupement par personne — une fiche par sujet, triee alphabetiquement
    const parSujet = {};
    filtered.forEach(m => {
        const sujet = m.sujet || '?';
        if (!parSujet[sujet]) parSujet[sujet] = [];
        parSujet[sujet].push(m);
    });

    const sujetsTries     = Object.keys(parSujet).sort((a, b) => a.localeCompare(b, 'fr'));
    const sujetsRelies    = sujetsTries.filter(s => parSujet[s].some(m => m.relie));
    const sujetsOrphelins = sujetsTries.filter(s => !parSujet[s].some(m => m.relie));

    sujetsRelies.forEach(sujet => list.appendChild(buildPersonCard(sujet, parSujet[sujet])));

    if (sujetsOrphelins.length) {
        const sep = document.createElement('div');
        sep.className = 'memory-section-title memory-section-title--evoques';
        sep.innerHTML = '🌐 Évoqués sans lien';
        list.appendChild(sep);
        sujetsOrphelins.forEach(sujet => list.appendChild(buildPersonCard(sujet, parSujet[sujet])));
    }
}

async function toggleLockMemory(key) {
    const row = document.querySelector(`.memory-row[data-key="${key}"]`);
    const locked = row?.dataset.locked === 'true';
    const res = await fetch(`/api/memory/${key}/${locked ? 'unlock' : 'lock'}`, { method: 'POST' });
    if (res.ok) loadMemory();
}

async function editMemory(key, currentVal) {
    const val = await memoryEditModal(currentVal);
    if (!val?.trim()) return;
    await fetch(`/api/memory/${key}`, {
        method:  'PUT',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ valeur: val.trim() })
    });
    loadMemory();
}

function memoryEditModal(currentVal = '') {
    return new Promise(resolve => {
        const modal    = document.getElementById('memory-edit-modal');
        const input    = document.getElementById('memory-edit-input');
        const okBtn    = document.getElementById('memory-edit-ok');
        const cancelBtn = document.getElementById('memory-edit-cancel');
        input.value = currentVal;
        modal.classList.remove('hidden');
        setTimeout(() => { input.focus(); input.select(); }, 80);
        const cleanup = () => modal.classList.add('hidden');
        okBtn.addEventListener('click', () => { cleanup(); resolve(input.value); }, { once: true });
        cancelBtn.addEventListener('click', () => { cleanup(); resolve(null); }, { once: true });
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') { cleanup(); resolve(input.value); }
            if (e.key === 'Escape') { cleanup(); resolve(null); }
        }, { once: true });
    });
}

async function deleteMemory(key) {
    const ok = await confirmModal('Supprimer ce souvenir ?');
    if (!ok) return;
    const modalBox = document.querySelector('#memory-modal .modal-box');
    const scrollTop = modalBox ? modalBox.scrollTop : 0;
    await fetch(`/api/memory/${key}`, { method: 'DELETE' });
    _allMemory = _allMemory.filter(m => m.key !== key);
    renderMemory(_allMemory);
    if (modalBox) modalBox.scrollTop = scrollTop;
}

// ══════════════════════════════════════════
// MODALE CONFIRMATION
// ══════════════════════════════════════════

function confirmModal(message) {
    return new Promise(resolve => {
        const modal   = document.getElementById('confirm-modal');
        const msgEl   = document.getElementById('confirm-message');
        const okBtn   = document.getElementById('confirm-ok');
        const cancelBtn = document.getElementById('confirm-cancel');

        msgEl.textContent = message;
        modal.classList.remove('hidden');
        setTimeout(() => { document.getElementById('confirm-cancel')?.focus(); }, 50);

        const cleanup = (result) => {
            modal.classList.add('hidden');
            setTimeout(() => { _pmPrevFocus?.focus(); }, 0);
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
            resolve(result);
        };

        const onOk     = () => cleanup(true);
        const onCancel = () => cleanup(false);

        okBtn.addEventListener('click', onOk,     { once: true });
        cancelBtn.addEventListener('click', onCancel, { once: true });
    });
}

function promptModal(title, defaultValue = '') {
    return new Promise(resolve => {
        const modal    = document.getElementById('prompt-modal');
        const titleEl  = document.getElementById('prompt-title');
        const input    = document.getElementById('prompt-input');
        const okBtn    = document.getElementById('prompt-ok');
        const cancelBtn = document.getElementById('prompt-cancel');
        titleEl.textContent = title;
        input.value = defaultValue;
        const _pmPrevFocus = document.activeElement;
        modal.classList.remove('hidden');
        setTimeout(() => { input.focus(); input.select(); }, 50);
        const cleanup = (result) => {
            modal.classList.add('hidden');
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
            input.removeEventListener('keydown', onKey);
            resolve(result);
        };
        const onOk     = () => cleanup(input.value.trim() || null);
        const onCancel = () => cleanup(null);
        const onKey    = (e) => {
            if (e.key === 'Enter')  onOk();
            if (e.key === 'Escape') onCancel();
        };
        okBtn.addEventListener('click', onOk,     { once: true });
        cancelBtn.addEventListener('click', onCancel, { once: true });
        input.addEventListener('keydown', onKey);
    });
}

// ══════════════════════════════════════════
// FERMETURE MODALES
// ══════════════════════════════════════════

// Utilitaire : ouvrir une modal en sauvegardant le focus
function _openModal(overlayOrModal) {
    const overlay = overlayOrModal.classList.contains('modal-overlay')
        ? overlayOrModal : overlayOrModal.closest('.modal-overlay') || overlayOrModal;
    overlay.__prevFocus = document.activeElement;
    overlay.classList.remove('hidden');
}
function _closeModal(overlayOrModal) {
    const overlay = overlayOrModal.classList.contains('modal-overlay')
        ? overlayOrModal : overlayOrModal.closest('.modal-overlay') || overlayOrModal;
    overlay.classList.add('hidden');
    setTimeout(() => { overlay.__prevFocus?.focus(); }, 0);
}
// MutationObserver : sauvegarder le focus dés qu'une modal-overlay devient visible
(function() {
    const _modalObs = new MutationObserver(mutations => {
        mutations.forEach(m => {
            if (m.type !== 'attributes' || m.attributeName !== 'class') return;
            const el = m.target;
            if (!el.classList.contains('modal-overlay')) return;
            const wasHidden = m.oldValue && m.oldValue.includes('hidden');
            const isVisible = !el.classList.contains('hidden');
            if (wasHidden && isVisible && !el.__prevFocus) {
                el.__prevFocus = document.activeElement;
            }
            if (!isVisible) { el.__prevFocus = null; }
        });
    });
    document.querySelectorAll('.modal-overlay').forEach(el => {
        _modalObs.observe(el, { attributes: true, attributeOldValue: true });
    });
})();

document.querySelectorAll('.close-modal').forEach(btn => {
    btn.addEventListener('click', () => _closeModal(btn.closest('.modal-overlay')));
});

// Clic en dehors de la modal
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
        if (e.target === overlay) _closeModal(overlay);
    });
});

// ══════════════════════════════════════════
// UTILITAIRES
// ══════════════════════════════════════════

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
}

function escapeAttr(str) {
    return (str || '').replace(/&/g,'&').replace(/"/g,'"').replace(/'/g,'&#39;');
}

// ══════════════════════════════════════════
// STT — Reconnaissance vocale v2 (MediaRecorder côté client)
// États : idle | loading | listening | processing
// UX : PC = clic pour démarrer / clic pour arrêter
//      Mobile = maintenir pour parler / relâcher pour transcrire
// ══════════════════════════════════════════

let _sttState    = 'idle';
let _mediaRec    = null;
let _audioChunks = [];
let _micStream   = null;
const _isMobile  = navigator.maxTouchPoints > 0 && window.innerWidth <= 640;

var _sttTurboActive = false;

function _setSttState(state) {
    _sttState = state;
    if (window._onSttStateChange) window._onSttStateChange();
    micBtn.className        = '';
    micBtn.disabled         = false;
    micBtn.style.borderColor = '';

    switch (state) {
        case 'idle':
            micBtn.innerHTML = SVG_MIC;
            micBtn.title     = 'Parler';
            break;
        case 'loading':
            micBtn.innerHTML = '<span class="stt-dots"><span></span><span></span><span></span></span>';
            micBtn.title     = 'Chargement Whisper…';
            micBtn.classList.add('mic-loading');
            break;
        case 'listening':
            micBtn.innerHTML = '<span class="stt-waves"><span></span><span></span><span></span></span>';
            micBtn.title     = _isMobile ? 'Relâcher pour transcrire' : 'Cliquer pour arrêter';
            micBtn.classList.add('mic-listening');
            break;
        case 'processing':
            micBtn.innerHTML = SVG_LOADING;
            micBtn.title     = 'Transcription…';
            micBtn.disabled  = true;
            break;
    }
    // Réappliquer la classe turbo si le mode est actif
    if (_sttTurboActive) micBtn.classList.add('turbo');
}

function _positionMenu(btn, menu, anchorRight = false) {
    const rect       = btn.getBoundingClientRect();
    const menuH      = 110; // ~3 items
    // La barre de saisie (#input-area) est fixe en bas d'écran et peut
    // recouvrir une partie de la fenêtre : la limite basse réelle utilisable
    // est son bord haut, pas le bas de la fenêtre.
    const inputArea  = document.getElementById('input-area');
    const limiteBasse = inputArea ? inputArea.getBoundingClientRect().top : window.innerHeight;
    const spaceBelow = limiteBasse - rect.bottom - 8;
    const spaceAbove = rect.top - 8;
    menu.style.position = 'fixed';
    // messages utilisateur (à droite) : ancre le coin droit du menu sur le
    // coin droit du bouton, ouvre vers la gauche — messages NIMM (à gauche) :
    // comportement d'origine, ancre à gauche, ouvre vers la droite.
    const menuW = 140;
    const rawLeft = anchorRight ? (rect.right - menuW) : rect.left;
    // Clamp pour ne jamais déborder ni à droite ni à gauche de l'écran
    const left = Math.min(rawLeft, window.innerWidth - menuW - 8);
    menu.style.left = Math.max(0, left) + 'px';
    // Ouvre vers le bas si assez de place, sinon vers le haut
    if (spaceBelow >= menuH) {
        menu.style.top    = rect.bottom + 2 + 'px';
        menu.style.bottom = 'auto';
    } else {
        menu.style.bottom = window.innerHeight - rect.top + 2 + 'px';
        menu.style.top    = 'auto';
    }
}

function _copyToClipboard(text) {
    // Copie riche : text/html (sémantique markdown conservée — titres, listes,
    // liens…) + text/plain en repli. Permet de coller la mise en forme dans
    // Word, un mail, etc., tout en gardant le texte brut ailleurs.
    if (navigator.clipboard && window.ClipboardItem && window.marked) {
        try {
            const html = _safeHTML(marked.parse(_linkifyBareUrls(text)));
            return navigator.clipboard.write([new ClipboardItem({
                'text/html':  new Blob([html], { type: 'text/html' }),
                'text/plain': new Blob([text], { type: 'text/plain' }),
            })]).catch(() => navigator.clipboard.writeText(text))
               .catch(() => _copyFallback(text));
        } catch(e) { /* repli texte simple ci-dessous */ }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).catch(() => _copyFallback(text));
    }
    return _copyFallback(text);
}

function _copyFallback(text) {
    return new Promise((resolve) => {
        const ta = document.createElement('textarea');
        ta.value = text;
        // Dans le viewport (requis par mobile) mais invisible
        ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:none;outline:none;background:transparent;opacity:0.01;';
        ta.setAttribute('readonly', '');  // evite l ouverture du clavier mobile
        document.body.appendChild(ta);
        ta.focus();
        ta.setSelectionRange(0, text.length);  // plus fiable que select() sur mobile
        try { document.execCommand('copy'); } catch(e) {}
        document.body.removeChild(ta);
        resolve();
    });
}

async function _waitSttReady() {
    for (let i = 0; i < 40; i++) {   // max 20s
        try {
            const r = await fetch('/api/stt/status').then(r => r.json());
            if (r.ready) return true;
        } catch(e) {}
        await new Promise(resolve => setTimeout(resolve, 500));
    }
    return false;
}

// ── Watchdog anti-blocage : évite qu'un clic reste "mort" pour toujours ──
// si une phase asynchrone (attente Whisper, requête réseau) ne se termine jamais.
let _sttWatchdogTimer = null;

function _armSttWatchdog() {
    if (_sttWatchdogTimer) clearTimeout(_sttWatchdogTimer);
    _sttWatchdogTimer = setTimeout(() => {
        if (_sttState !== 'idle') {
            console.warn('[STT] Watchdog : état bloqué sur "' + _sttState + '" — réinitialisation forcée.');
            _notify('🎙️ Ça a coincé, réessaie.', 'error');
            _micStream?.getTracks().forEach(t => t.stop());
            _micStream = null;
            _setSttState('idle');
        }
    }, 25000);
}

function _disarmSttWatchdog() {
    if (_sttWatchdogTimer) { clearTimeout(_sttWatchdogTimer); _sttWatchdogTimer = null; }
}

async function _startRecording() {
    if (_sttState !== 'idle') return;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        _setSttState('idle');
        _notify('🎙️ Micro indisponible (HTTPS requis).', 'error');
        console.warn('[STT] HTTPS requis pour le micro (Chrome/mobile)');
        return;
    }

    _armSttWatchdog();
    _setSttState('loading');

    try {
        // IMPORTANT : getUserMedia doit rester la toute première operation async apres le clic.
        // Firefox invalide le "geste utilisateur" des qu'un autre await a lieu avant lui,
        // et refuse alors le micro silencieusement (NotAllowedError) meme si la permission est accordee.
        _micStream   = await navigator.mediaDevices.getUserMedia({ audio: true });
        _audioChunks = [];

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : MediaRecorder.isTypeSupported('audio/webm')
                ? 'audio/webm'
                : MediaRecorder.isTypeSupported('audio/mp4')
                    ? 'audio/mp4'
                    : '';

        _mediaRec = mimeType
            ? new MediaRecorder(_micStream, { mimeType })
            : new MediaRecorder(_micStream);

        _mediaRec.ondataavailable = e => {
            if (e.data && e.data.size > 0) _audioChunks.push(e.data);
        };

        _mediaRec.start();   // pas de timeslice — plus fiable sur mobile
        _disarmSttWatchdog(); // écoute = contrôlée par l'utilisateur, pas de watchdog
        _setSttState('listening');

    } catch(e) {
        console.error('[STT] Erreur accès micro :', e);
        _disarmSttWatchdog();
        _setSttState('idle');
        const _reason = e.name === 'NotAllowedError' ? 'Permission micro refusée'
            : e.name === 'NotSupportedError' ? 'HTTPS requis (Tailscale)'
            : e.name === 'NotFoundError' ? 'Aucun micro détecté'
            : (e.message || e.name);
        _notify('🎙️ ' + _reason, 'error');
        console.warn('[STT] Erreur accès micro :', _reason);
    }
}

async function _stopRecording() {
    if (_sttState !== 'listening' || !_mediaRec) return;

    _armSttWatchdog();
    _setSttState('processing');

    await new Promise(resolve => {
        _mediaRec.onstop = resolve;
        _mediaRec.stop();
    });

    _micStream?.getTracks().forEach(t => t.stop());
    _micStream = null;

    if (!_audioChunks.length) { _disarmSttWatchdog(); _setSttState('idle'); return; }

    try {
        const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
        const mimeType = _mediaRec.mimeType || (isSafari ? 'audio/mp4' : 'audio/webm');
        const ext      = mimeType.includes('mp4') ? 'mp4' : 'webm';
        const blob     = new Blob(_audioChunks, { type: mimeType });
        const formData = new FormData();
        formData.append('file', blob, `audio.${ext}`);
        if (currentThreadId) formData.append('thread_id', currentThreadId);
        if (_sttTurboActive) formData.append('turbo', 'true');

        const r      = await fetch('/api/stt/transcribe', { method: 'POST', body: formData });
        const result = await r.json();
        _disarmSttWatchdog();

        if (result.status === 'ok' && result.text) {
            userInput.value = (userInput.value + ' ' + result.text).trim();
            userInput.style.height = '44px';
            userInput.style.height = Math.min(userInput.scrollHeight, 240) + 'px';
            micBtn.innerHTML = SVG_CHECK;
            // Afficher le bouton ↩️ après une dictée
            const nlBtn = document.getElementById('newline-btn');
            if (nlBtn) nlBtn.classList.remove('hidden');
            const preview = document.getElementById('mic-panel-preview');
            if (preview) {
                preview.textContent = userInput.value.trim();
                preview.classList.add('has-text');
            }
            const status = document.getElementById('mic-panel-status');
            if (status) status.textContent = '✅ Transcrit — appuie pour relancer';
            setTimeout(() => _setSttState('idle'), 1500);
        } else {
            const status = document.getElementById('mic-panel-status');
            if (status) status.textContent = result.status === 'erreur'
                ? '⚠️ Erreur : ' + (result.error || 'inconnue')
                : '⚠️ Rien capté — réessaie';
            _notify('🎙️ ' + (result.status === 'erreur' ? ('Erreur : ' + (result.error || 'inconnue')) : 'Rien capté — réessaie'), 'warn');
            console.warn('[STT] Résultat vide ou erreur :', result);
            setTimeout(() => _setSttState('idle'), 2500);
        }
    } catch(e) {
        console.error('[STT] Erreur transcription :', e);
        _disarmSttWatchdog();
        _setSttState('idle');
        _notify('🎙️ Erreur réseau pendant la transcription.', 'error');
    }
}

// ── Bouton ↩️ saut de ligne — visible seulement après dictée vocale ──
document.getElementById('newline-btn')?.addEventListener('click', () => {
    const cursor = userInput.selectionStart || userInput.value.length;
    userInput.value = userInput.value.slice(0, cursor) + '\n' + userInput.value.slice(cursor);
    userInput.selectionStart = userInput.selectionEnd = cursor + 1;
    userInput.dispatchEvent(new Event('input'));
});

// ── Binding UX — desktop : direct ; mobile : ouvre le panneau dédié (retour visuel + gros bouton) ──
micBtn.addEventListener('click', () => {
    if (_isMobile) { openMicPanel(); return; }
    if (_sttState === 'listening') _stopRecording();
    else _startRecording();
});

// ══════════════════════════════════════════
// MOBILE — Panneau micro
// ══════════════════════════════════════════

function openMicPanel() {
    const panel   = document.getElementById('mic-panel');
    const preview = document.getElementById('mic-panel-preview');
    userInput.blur(); // empêche le clavier mobile de s'ouvrir
    if (preview) {
        const txt = userInput.value.trim();
        preview.textContent = txt;
        preview.classList.toggle('has-text', txt.length > 0);
    }
    _updateMicPanelState();
    panel.classList.remove('hidden');
    panel.offsetHeight;
    panel.classList.add('open');
}

function closeMicPanel() {
    const panel = document.getElementById('mic-panel');
    if (_sttState === 'listening') _stopRecording();
    panel.classList.remove('open');
    setTimeout(() => {
        if (!panel.classList.contains('open')) panel.classList.add('hidden');
    }, 280);
}

function _updateMicPanelState() {
    const panelBtn = document.getElementById('mic-panel-btn');
    const status   = document.getElementById('mic-panel-status');
    if (!panelBtn || !status) return;
    switch (_sttState) {
        case 'idle':
            panelBtn.innerHTML = SVG_MIC;
            panelBtn.classList.remove('recording');
            status.textContent = 'Appuie pour parler';
            break;
        case 'loading':
            panelBtn.innerHTML = SVG_LOADING;
            panelBtn.classList.remove('recording');
            status.textContent = 'Chargement Whisper…';
            break;
        case 'listening':
            panelBtn.innerHTML = SVG_STOP;
            panelBtn.classList.add('recording');
            status.textContent = 'En écoute — appuie pour arrêter';
            break;
        case 'processing':
            panelBtn.innerHTML = SVG_LOADING;
            panelBtn.classList.remove('recording');
            status.textContent = 'Transcription en cours…';
            break;
    }
}

// Boutons du panneau
document.getElementById('mic-panel-btn').addEventListener('click', () => {
    if (_sttState === 'listening') _stopRecording();
    else if (_sttState === 'idle') _startRecording();
});

document.getElementById('mic-panel-close').addEventListener('click', () => closeMicPanel());
document.getElementById('mic-panel-backdrop')?.addEventListener('click', () => closeMicPanel());

document.getElementById('mic-panel-clear').addEventListener('click', () => {
    // Efface le dernier caractère (backspace)
    if (userInput.value.length > 0) {
        userInput.value = userInput.value.slice(0, -1);
        userInput.style.height = '44px';
        userInput.style.height = Math.min(userInput.scrollHeight, 240) + 'px';
    }
    const preview = document.getElementById('mic-panel-preview');
    if (preview) {
        preview.textContent = userInput.value.trim();
        if (!userInput.value.trim()) preview.classList.remove('has-text');
    }
});

document.getElementById('mic-panel-enter').addEventListener('click', () => {
    closeMicPanel();
    setTimeout(() => sendMessage(), 50);
});

// Sync état panneau quand _setSttState est appelé
const _origSetSttState = _setSttState.bind({});
// patch : on surcharge après coup
const _setSttStateOrig = _setSttState;
window._onSttStateChange = () => { if (_isMobile) _updateMicPanelState(); };

// ══════════════════════════════════════════
// UPLOAD — Fichier / Image / PDF
// ══════════════════════════════════════════
let _pendingFile = null; // { text, name, b64?, mime_type? }
let _pendingVibeDoc = null; // { file_id, name } — document Vibe (API Files Mistral)
let _vibeSentDocs = []; // file_ids envoyes dans le fil courant (suppression RGPD au changement de fil)
function _purgeVibeDocs() {
    var ids = _vibeSentDocs.slice();
    if (_pendingVibeDoc && _pendingVibeDoc.file_id) {
        ids.push(_pendingVibeDoc.file_id);
        var _c = document.getElementById('file-chip');
        if (_c) _c.style.display = 'none';
    }
    _vibeSentDocs = [];
    _pendingVibeDoc = null;
    ids.forEach(function(fid) {
        if (fid) fetch('/api/vibe/file/' + encodeURIComponent(fid), { method: 'DELETE' }).catch(function(){});
    });
}

function setupUpload() {
    const btn    = document.getElementById('upload-btn');
    const input  = document.getElementById('file-input');
    const chip   = document.getElementById('file-chip');
    const preview = document.getElementById('file-chip-preview');
    const chipRm = document.getElementById('file-chip-remove');
    const menu   = document.getElementById('plus-menu');
    if (!btn || !input) return;

    // ── Construit la vignette dans #file-chip-preview ──
    function _buildChip(file) {
        preview.innerHTML = '';
        const isImage = file.type.startsWith('image/');
        const ext = file.name.split('.').pop().toUpperCase().slice(0, 5);

        const iconMap = { PDF:'📄', DOC:'📝', DOCX:'📝', TXT:'📃', CSV:'📊',
                          XLS:'📊', XLSX:'📊', PPT:'📑', PPTX:'📑',
                          PY:'🐍', JS:'🟨', JSON:'🔧', ZIP:'🗜️', RAR:'🗜️' };

        // Conteneur vignette (position:relative pour le ✕)
        const wrap = document.createElement('div');
        wrap.style.cssText = 'position:relative; display:inline-flex; flex-direction:column; align-items:center; gap:4px;';

        const thumb = document.createElement('div');
        thumb.className = 'chip-thumb';

        if (isImage) {
            const localUrl = URL.createObjectURL(file);
            const img = document.createElement('img');
            img.src = localUrl;
            img.alt = file.name;
            img.onload = () => URL.revokeObjectURL(localUrl);
            thumb.appendChild(img);
        } else {
            const icon = document.createElement('div');
            icon.className = 'chip-icon';
            icon.textContent = iconMap[ext] || '📎';
            const extBadge = document.createElement('div');
            extBadge.className = 'chip-ext';
            extBadge.textContent = ext;
            thumb.appendChild(icon);
            thumb.appendChild(extBadge);
        }

        // ✕ injecté dans le wrap, ancré en haut à droite du thumb
        const rmBtn = document.createElement('button');
        rmBtn.textContent = '✕';
        rmBtn.title = 'Retirer le fichier joint';
        rmBtn.setAttribute('aria-label', 'Retirer le fichier joint');
        rmBtn.style.cssText = 'position:absolute; top:-6px; right:-6px; width:18px; height:18px; border-radius:50%; background:#2a2420; border:1px solid #3a3530; color:#e8e8e8; cursor:pointer; font-size:0.65rem; display:flex; align-items:center; justify-content:center; z-index:10; line-height:1;';
        rmBtn.addEventListener('click', () => {
            _pendingFile       = null;
            chip.style.display = 'none';
            preview.innerHTML  = '';
        });

        const fname = document.createElement('div');
        fname.className = 'chip-filename';
        fname.textContent = file.name;

        wrap.appendChild(thumb);
        wrap.appendChild(rmBtn);
        wrap.appendChild(fname);
        preview.appendChild(wrap);

        chip.setAttribute('aria-label', `Fichier joint : ${file.name}. Bouton disponible pour retirer.`);
        chip.style.display = 'flex';
        document.getElementById('user-input').focus();
    }

    // ── Traitement upload (commun bouton + drop) ──
    const AUDIO_EXTS = ['mp3','wav','ogg','m4a','flac','webm','aac','oga','opus'];
    async function _processFile(file) {
        if (!file) return;
        btn.innerHTML = SVG_LOADING;
        btn.disabled = true;
        _buildChip(file);

        const _ext = (file.name.split('.').pop() || '').toLowerCase();
        const _isAudio = AUDIO_EXTS.includes(_ext);

        try {
            const fd = new FormData();
            fd.append('file', file);
            let _endpoint = '/api/upload';
            if (_isAudio) {
                fd.append('prompt', 'Transcris et analyse ce fichier audio. Fournis la transcription complete et un resume bref du contenu.');
                _endpoint = '/api/mistral/audio_analyze';
            }
            const r    = await fetch(_endpoint, { method: 'POST', body: fd });
            const data = await r.json();
            if (data.text) {
                const _label = _isAudio ? ('[Analyse audio Voxtral - ' + file.name + ']\n') : '';
                _pendingFile = { text: _label + data.text, name: file.name, b64: data.b64 || null, mime_type: data.mime_type || null };
            } else {
                _pendingFile       = null;
                chip.style.display = 'none';
            }
        } catch(e) {
            if (_isAudio) {
                _pendingFile = { text: '[Fichier audio : ' + file.name + ' - analyse Voxtral indisponible]', name: file.name, b64: null, mime_type: null };
            } else {
                console.error('[NIMM] Erreur upload :', e);
                _pendingFile       = null;
                chip.style.display = 'none';
            }
        } finally {
            btn.textContent = '+';
            btn.disabled    = false;
        }
    }

    // "+" ouvre/ferme le mini-menu
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.classList.toggle('hidden');
    });

    // Clic en dehors → ferme le menu
    document.addEventListener('click', () => menu.classList.add('hidden'));

    // Option 1 : Joindre un fichier
    document.getElementById('plus-attach')?.addEventListener('click', () => {
        menu.classList.add('hidden');
        input.click();
    });

    // Option 2 : Créer une image → injecte le préfixe 🖼️ dans la saisie
    document.getElementById('plus-imagegen')?.addEventListener('click', () => {
        menu.classList.add('hidden');
        const inp = document.getElementById('user-input');
        if (!inp.value.startsWith('🖼️ ')) {
            inp.value = '🖼️ ' + inp.value;
        }
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
    });


    // Option 3 : Document Vibe (OCR Mistral)
    var _vibeDocBtn   = document.getElementById('plus-vibe-doc');
    var _vibeDocInput = document.getElementById('vibe-doc-input');
    if (_vibeDocBtn) {
        _vibeDocBtn.addEventListener('click', function() {
            menu.classList.add('hidden');
            if (_vibeDocInput) _vibeDocInput.click();
        });
    }
    if (_vibeDocInput) {
        _vibeDocInput.addEventListener('change', async function() {
            var file = _vibeDocInput.files[0];
            _vibeDocInput.value = '';
            if (!file) return;
            btn.innerHTML = SVG_LOADING;
            btn.disabled = true;
            _buildChip(file);
            _srAnnounce('Envoi du document en cours…');
            try {
                var fd = new FormData();
                fd.append('file', file);
                var r = await fetch('/api/vibe/upload-doc', { method: 'POST', body: fd });
                if (!r.ok) throw new Error(await r.text());
                var d = await r.json();
                if (d.file_id) {
                    _pendingFile = null;
                    _pendingVibeDoc = { file_id: d.file_id, name: file.name };
                    _srAnnounce('Document joint : ' + file.name);
                } else {
                    _pendingVibeDoc = null;
                    chip.style.display = 'none';
                    _srAnnounce('Erreur : document non joint.');
                }
            } catch(e) {
                console.error('[NIMM] Erreur upload doc Vibe :', e);
                _pendingVibeDoc = null;
                chip.style.display = 'none';
                _srAnnounce("Erreur lors de l'envoi du document.");
            } finally {
                btn.textContent = '+';
                btn.disabled = false;
            }
        });
    }

    // Sélection via input file
    input.addEventListener('change', async () => {
        const file = input.files[0];
        input.value = '';
        await _processFile(file);
    });

    // Retirer le fichier
    chipRm?.addEventListener('click', () => {
        if (_pendingVibeDoc && _pendingVibeDoc.file_id) {
            fetch('/api/vibe/file/' + encodeURIComponent(_pendingVibeDoc.file_id), { method: 'DELETE' }).catch(()=>{});
        }
        _pendingFile       = null;
        _pendingVibeDoc    = null;
        chip.style.display = 'none';
        preview.innerHTML  = '';
    });

    // ── Drag-and-drop ──
    const overlay = document.getElementById('drop-overlay');
    let _dragCounter = 0;

    document.addEventListener('dragenter', (e) => {
        if (!e.dataTransfer?.types?.includes('Files')) return;
        e.preventDefault();
        _dragCounter++;
        if (overlay) overlay.classList.add('active');
    });

    document.addEventListener('dragleave', (e) => {
        e.preventDefault();
        _dragCounter--;
        if (_dragCounter <= 0) {
            _dragCounter = 0;
            if (overlay) overlay.classList.remove('active');
        }
    });

    document.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
    });

    document.addEventListener('drop', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        _dragCounter = 0;
        if (overlay) overlay.classList.remove('active');
        const file = e.dataTransfer?.files?.[0];
        if (file) await _processFile(file);
    });

}

// ══════════════════════════════════════════
// MOBILE — ADAPTATION HAUTEUR CLAVIER
// ══════════════════════════════════════════

// Redimensionnement JS désactivé (2026-07-26) : le CSS (100dvh) combiné à
// l'attribut viewport "interactive-widget=resizes-content" gère maintenant
// nativement l'adaptation au clavier, sans les bugs de rendu (écran/texte
// invisible sur iPhone, zone noire sur Android) causés par ce script.
// Conservé en commentaire au cas où un ancien navigateur en aurait besoin :
//
// if (window.visualViewport) {
//     const appEl = document.getElementById('app');
//     let _vvTimer = null;
//     function _applyViewportHeight() {
//         if (!isMobile()) return;
//         appEl.style.height = window.visualViewport.height + 'px';
//         void appEl.offsetHeight;
//         const inputEl = document.getElementById('user-input');
//         if (document.activeElement === inputEl) {
//             messagesDiv.scrollTop = messagesDiv.scrollHeight;
//         }
//     }
//     window.visualViewport.addEventListener('resize', () => {
//         if (_vvTimer) clearTimeout(_vvTimer);
//         _vvTimer = setTimeout(_applyViewportHeight, 120);
//     });
//     window.visualViewport.addEventListener('scroll', () => {
//         if (_vvTimer) clearTimeout(_vvTimer);
//         _vvTimer = setTimeout(_applyViewportHeight, 120);
//     });
// }

// ══════════════════════════════════════════
// ONGLETS PARAMÈTRES
// ══════════════════════════════════════════

function setupSettingsTabs() {
    document.querySelectorAll('.settings-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll('.settings-tab').forEach(b => {
                b.classList.toggle('active', b.dataset.tab === tab);
                b.setAttribute('aria-selected', String(b.dataset.tab === tab));
            });
            document.querySelectorAll('.settings-tab-content').forEach(c => {
                c.classList.toggle('hidden', c.id !== `settings-tab-${tab}`);
            });
            if (tab === 'couts')  loadCosts();
            if (tab === 'users')  _loadUsersTab();
        });
    });
}


// ══════════════════════════════════════════
// SUIVI DES COÛTS
// ══════════════════════════════════════════

async function loadCosts() {
    const grid    = document.getElementById('costs-grid');
    const loading = document.getElementById('costs-loading');
    if (!grid) return;
    if (loading) loading.style.display = 'block';
    grid.innerHTML = '';
    try {
        const r = await fetch('/api/costs');
        const d = await r.json();
        if (loading) loading.style.display = 'none';
        if (!d.wallets || !d.wallets.length) {
            grid.innerHTML = '<p style="color:var(--text-muted);padding:12px;">Aucun fournisseur configuré.</p>';
            return;
        }
        _ensureCostTableStyle();
        grid.innerHTML = _renderCostTable(d.wallets);
        _setupCostActions();

        // Crédit restant en temps réel — chargement non bloquant, en plus
        fetch('/api/costs/credits').then(r => r.json()).then(cd => {
            const credits = cd.credits || {};
            for (const [provider, info] of Object.entries(credits)) {
                const cell = grid.querySelector(`td.cost-credit[data-provider="${provider}"]`);
                if (!cell || !info.available) continue;
                cell.innerHTML = `<strong>${info.balance} ${info.currency}</strong>`;
                cell.setAttribute('aria-label', `Crédit API restant : ${info.balance} ${info.currency}`);
            }
        }).catch(() => {});
    } catch(e) {
        if (loading) loading.textContent = 'Erreur de chargement.';
    }
}

const _COST_ICONS = {
    anthropic: '🔴', deepseek: '🟢', gemini: '🟡', openai: '🔴',
    openrouter: '🟠', mistral: '🔵', ollama: '🟢', brave: '🔵', tavily: '🟣',
    groq: '⚡', cerebras: '⚡'
};

// Injecte une seule fois le style du tableau des coûts (évite de toucher styles.css).
function _ensureCostTableStyle() {
    if (document.getElementById('cost-table-style')) return;
    const st = document.createElement('style');
    st.id = 'cost-table-style';
    st.textContent = `
        .cost-table { width:100%; border-collapse:collapse; font-size:0.85rem; }
        .cost-table caption { text-align:left; color:var(--text-muted); font-size:0.8rem; padding:0 0 8px; }
        .cost-table th, .cost-table td { border:1px solid var(--border); padding:6px 8px; text-align:left; vertical-align:top; }
        .cost-table thead th { background:var(--bg-secondary); }
        .cost-table tbody th[scope="row"] { font-weight:600; white-space:nowrap; }
        .cost-table td { white-space:nowrap; }
        .cost-table .cost-num { text-align:right; font-variant-numeric:tabular-nums; }
        .cost-table .cost-btn { font-size:0.75rem; padding:2px 6px; margin:1px; border:1px solid var(--border); border-radius:5px; background:var(--bg-input); color:var(--text); cursor:pointer; }`;
    document.head.appendChild(st);
}

// Coût estimé € = (tokens_in × tarif_in + tokens_out × tarif_out) / 1M.
function _walletEstCost(w) {
    return ((w.tokens_in_total || 0) * (w.rate_in || 0)
          + (w.tokens_out_total || 0) * (w.rate_out || 0)) / 1_000_000;
}

function _renderCostTable(wallets) {
    const rows = wallets.map(w => {
        const icon   = _COST_ICONS[w.provider] || '⚪';
        const estStr = _formatCostEur(_walletEstCost(w)) || '0 €';
        const solde  = w.wallet_type === 'tirelire'
            ? `${(w.solde_restant || 0).toFixed(2).replace('.', ',')} € / ${(w.solde_depart || 0).toFixed(2).replace('.', ',')} €`
            : '—';
        const toks   = `${_fmtNum(w.tokens_in_total)} / ${_fmtNum(w.tokens_out_total)}`;
        const reqs   = w.wallet_type === 'compteur_requetes' ? _fmtNum(w.requests_total) : '—';
        const rates  = `${(w.rate_in || 0)} / ${(w.rate_out || 0)}`;
        const depuis = _fmtDate(w.last_reset);

        let actions = '';
        if (w.wallet_type === 'tirelire') {
            actions =
                `<button class="cost-btn" data-action="solde" data-provider="${w.provider}" data-solde="${w.solde_depart}" aria-label="Modifier le solde de ${w.display_name}">✏️ Solde</button> ` +
                `<button class="cost-btn" data-action="rates" data-provider="${w.provider}" data-rate-in="${w.rate_in}" data-rate-out="${w.rate_out}" aria-label="Modifier les tarifs de ${w.display_name}">✏️ Tarifs</button> ` +
                `<button class="cost-btn cost-btn-reset" data-action="reset" data-provider="${w.provider}" aria-label="Réinitialiser les compteurs de ${w.display_name}">🔄 Reset</button>`;
        } else if (w.wallet_type === 'compteur_tokens') {
            actions =
                `<button class="cost-btn" data-action="rates" data-provider="${w.provider}" data-rate-in="${w.rate_in}" data-rate-out="${w.rate_out}" aria-label="Modifier les tarifs de ${w.display_name}">✏️ Tarifs</button> ` +
                `<button class="cost-btn cost-btn-reset" data-action="reset" data-provider="${w.provider}" aria-label="Réinitialiser les compteurs de ${w.display_name}">🔄 Reset</button>`;
        } else {
            actions =
                `<button class="cost-btn cost-btn-reset" data-action="reset" data-provider="${w.provider}" aria-label="Réinitialiser les compteurs de ${w.display_name}">🔄 Reset</button>`;
        }

        return `
            <tr data-provider="${w.provider}">
                <th scope="row">${icon} ${w.display_name}</th>
                <td class="cost-num">${estStr}</td>
                <td class="cost-num">${solde}</td>
                <td class="cost-credit cost-num" data-provider="${w.provider}">—</td>
                <td class="cost-num">${toks}</td>
                <td class="cost-num">${reqs}</td>
                <td class="cost-num">${rates}</td>
                <td>${depuis}</td>
                <td>${actions}</td>
            </tr>`;
    }).join('');

    return `
        <table class="cost-table">
            <caption>Dépenses estimées par fournisseur. Tokens et tarifs au format « entrée / sortie » ; tarifs en dollars par million de tokens.</caption>
            <thead>
                <tr>
                    <th scope="col">Fournisseur</th>
                    <th scope="col">Coût estimé</th>
                    <th scope="col">Solde</th>
                    <th scope="col">Crédit API</th>
                    <th scope="col">Tokens (entrée / sortie)</th>
                    <th scope="col">Requêtes</th>
                    <th scope="col">Tarifs $/1M (entrée / sortie)</th>
                    <th scope="col">Depuis</th>
                    <th scope="col">Actions</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function _fmtNum(n) {
    if (!n) return '0';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'k';
    return n.toString();
}

function _fmtDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit', year: '2-digit'});
    } catch { return '—'; }
}

function ratesModal(title, rIn = 0, rOut = 0) {
    return new Promise(resolve => {
        const modal     = document.getElementById('cost-rates-modal');
        const titleEl   = document.getElementById('cost-rates-title');
        const inEl      = document.getElementById('cost-rates-in');
        const outEl     = document.getElementById('cost-rates-out');
        const okBtn     = document.getElementById('cost-rates-ok');
        const cancelBtn = document.getElementById('cost-rates-cancel');

        titleEl.textContent = title;
        inEl.value  = rIn;
        outEl.value = rOut;
        inEl.style.borderColor  = '';
        outEl.style.borderColor = '';
        modal.classList.remove('hidden');
        setTimeout(() => { inEl.focus(); inEl.select(); }, 50);

        const cleanup = (result) => {
            modal.classList.add('hidden');
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
            resolve(result);
        };
        const onOk = () => {
            const numIn  = parseFloat(String(inEl.value).replace(',', '.'));
            const numOut = parseFloat(String(outEl.value).replace(',', '.'));
            if (isNaN(numIn) || isNaN(numOut) || numIn < 0 || numOut < 0) {
                inEl.style.borderColor  = '#e05555';
                outEl.style.borderColor = '#e05555';
                return;
            }
            cleanup({rate_in: numIn, rate_out: numOut});
        };
        const onCancel = () => cleanup(null);
        okBtn.addEventListener('click', onOk,      { once: true });
        cancelBtn.addEventListener('click', onCancel, { once: true });
    });
}

function _setupCostActions() {
    document.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const action   = btn.dataset.action;
            const provider = btn.dataset.provider;

            if (action === 'reset') {
                const ok = await confirmModal(`Remettre à zéro les compteurs de ${provider} ?`);
                if (!ok) return;
                await fetch(`/api/costs/reset/${provider}`, {method: 'POST'});
                loadCosts();

            } else if (action === 'solde') {
                const val = await promptModal(`Solde de départ — ${provider} (€)`, btn.dataset.solde || '0');
                if (val === null) return;
                const num = parseFloat(val.replace(',', '.'));
                if (isNaN(num) || num < 0) return;
                await fetch(`/api/costs/wallet/${provider}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({solde_depart: num})
                });
                loadCosts();

            } else if (action === 'rates') {
                const result = await ratesModal(
                    `Tarifs — ${provider}`,
                    btn.dataset.rateIn  || '0',
                    btn.dataset.rateOut || '0'
                );
                if (!result) return;
                await fetch(`/api/costs/rates/${provider}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(result)
                });
                loadCosts();
            }
        });
    });
}


// ══════════════════════════════════════════
// MISE À JOUR
// ══════════════════════════════════════════

document.getElementById('btn-update').addEventListener('click', async () => {
    const btn    = document.getElementById('btn-update');
    const status = document.getElementById('update-status');
    btn.disabled = true;
    btn.textContent = 'Téléchargement…';
    status.textContent = '';
    try {
        const r = await fetch('/api/update', { method: 'POST' });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            status.textContent = '❌ Erreur : ' + (err.detail || r.status);
            btn.disabled = false;
            btn.textContent = 'Vérifier et installer les mises à jour';
            return;
        }
        status.textContent = '✅ Mise à jour appliquée ! Rechargement dans 3 secondes…';
        setTimeout(() => location.reload(), 3000);
    } catch (e) {
        status.textContent = '❌ Impossible de joindre le serveur.';
        btn.disabled = false;
        btn.textContent = 'Vérifier et installer les mises à jour';
    }
});


// ══════════════════════════════════════════
// LANCEMENT
// ══════════════════════════════════════════

document.addEventListener('click', () => {
    document.querySelectorAll('.thread-dropdown.open').forEach(d => d.classList.remove('open'));
});

// ══════════════════════════════════════════

document.addEventListener('click', () => {
    document.querySelectorAll('.thread-dropdown.open').forEach(d => d.classList.remove('open'));
});

// ══════════════════════════════════════════
// ENRICHISSEMENT WEB (ingestion → zone de référence)
// ══════════════════════════════════════════
(function () {
    var mode = 'url'; // 'url' | 'text' | 'file'

    function setMode(m) {
        mode = m;
        var ids = { url: 'enrich-mode-url', text: 'enrich-mode-text', file: 'enrich-mode-file' };
        Object.keys(ids).forEach(function (k) {
            var b = document.getElementById(ids[k]);
            if (b) b.setAttribute('aria-checked', k === m ? 'true' : 'false');
        });
        var titleRow = document.getElementById('enrich-title-row');
        var fileRow = document.getElementById('enrich-file-row');
        var input = document.getElementById('enrich-input');
        if (titleRow) titleRow.classList.toggle('hidden', m !== 'text');
        if (fileRow) fileRow.classList.toggle('hidden', m !== 'file');
        if (input) {
            input.classList.toggle('hidden', m === 'file');
            input.placeholder = m === 'url'
                ? 'https://exemple.org/article\nhttps://autre.org/page'
                : "Colle ici le texte de l'article…";
        }
    }

    function esc(s) {
        return (s || '').replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    async function loadEnrich() {
        var list = document.getElementById('enrich-list');
        if (!list) return;
        list.textContent = 'Chargement…';
        try {
            var refs = await fetch('/api/enrich/list').then(function (r) { return r.json(); });
            if (!refs.length) { list.textContent = 'Aucun contenu pour le moment.'; return; }
            list.innerHTML = '';
            refs.forEach(function (r) {
                var item = document.createElement('div');
                item.style.cssText = 'display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);';
                var src = (r.source && r.source !== 'recherche')
                    ? (r.source.indexOf('http') === 0 ? 'URL' : r.source)
                    : 'recherche';
                var meta = esc(src) + (r.expiration ? ' · expire le ' + esc((r.expiration || '').slice(0, 10)) : ' · permanent');
                var info = document.createElement('div');
                info.innerHTML = '<div style="font-weight:500;">' + esc(r.titre || '(sans titre)') + '</div>' +
                                 '<div style="font-size:0.8rem;color:var(--text-muted);">' + meta + '</div>';
                var del = document.createElement('button');
                del.textContent = '🗑️';
                del.setAttribute('aria-label', 'Supprimer ' + (r.titre || 'ce contenu'));
                del.style.cssText = 'background:transparent;border:none;color:var(--text-muted);cursor:pointer;font-size:1rem;';
                del.addEventListener('click', async function () {
                    await fetch('/api/enrich/' + r.id, { method: 'DELETE' });
                    loadEnrich();
                });
                item.appendChild(info);
                item.appendChild(del);
                list.appendChild(item);
            });
        } catch (e) {
            list.textContent = 'Erreur de chargement.';
        }
    }

    async function submitEnrich() {
        var input = document.getElementById('enrich-input');
        var status = document.getElementById('enrich-status');
        status.textContent = 'Ingestion en cours…';
        try {
            if (mode === 'file') {
                var fileEl = document.getElementById('enrich-file');
                var f = fileEl && fileEl.files && fileEl.files[0];
                if (!f) { status.textContent = 'Aucun fichier sélectionné.'; return; }
                var fd = new FormData();
                fd.append('file', f, f.name);
                var forceOcr = document.getElementById('enrich-force-ocr');
                fd.append('force_ocr', (forceOcr && forceOcr.checked) ? 'true' : 'false');
                var resF = await fetch('/api/enrich/file', { method: 'POST', body: fd })
                    .then(function (r) { return r.json(); });
                status.textContent = resF.ok
                    ? ('Fichier ajouté : ' + (resF.titre || f.name) + (resF.passages ? ' (' + resF.passages + ' passages)' : ''))
                    : ('Échec : ' + (resF.erreur || ''));
                fileEl.value = '';
            } else if (mode === 'url') {
                var raw = (input.value || '').trim();
                if (!raw) { status.textContent = 'Rien à ingérer.'; return; }
                var urls = raw.split('\n').map(function (u) { return u.trim(); }).filter(Boolean);
                var ok = 0, fail = 0, last = '';
                for (var i = 0; i < urls.length; i++) {
                    var res = await fetch('/api/enrich/url', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url: urls[i] })
                    }).then(function (r) { return r.json(); });
                    if (res.ok) { ok++; } else { fail++; last = res.erreur || ''; }
                }
                status.textContent = ok + ' page(s) ajoutée(s)' + (fail ? ', ' + fail + ' échec(s). ' + last : '.');
                input.value = '';
            } else {
                var raw2 = (input.value || '').trim();
                if (!raw2) { status.textContent = 'Rien à ingérer.'; return; }
                var titre = (document.getElementById('enrich-title').value || '').trim();
                var res2 = await fetch('/api/enrich/text', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ titre: titre, texte: raw2 })
                }).then(function (r) { return r.json(); });
                status.textContent = res2.ok
                    ? ('Texte ajouté' + (res2.passages ? ' (' + res2.passages + ' passages)' : '') + '.')
                    : ('Échec : ' + (res2.erreur || ''));
                input.value = '';
            }
            loadEnrich();
        } catch (e) {
            status.textContent = 'Erreur réseau.';
        }
    }

    var enrichModal = document.getElementById('enrich-modal');
    var enrichTrigger = null;
    if (enrichModal) {
        // Restaure le focus sur le déclencheur à la fermeture — quel que soit le chemin
        // (bouton ✕, clic sur le fond, Échap), tous basculant la classe 'hidden'.
        new MutationObserver(function () {
            if (enrichModal.classList.contains('hidden') && enrichTrigger) {
                var t = enrichTrigger; enrichTrigger = null;
                setTimeout(function () { try { t.focus(); } catch (e) {} }, 0);
            }
        }).observe(enrichModal, { attributes: true, attributeFilter: ['class'] });
    }
    document.getElementById('toggle-enrich')?.addEventListener('click', function () {
        enrichTrigger = this;            // pour rendre le focus à la fermeture
        setMode('url');                  // état neutre à chaque ouverture
        var st = document.getElementById('enrich-status'); if (st) st.textContent = '';
        enrichModal.classList.remove('hidden');
        loadEnrich();
        setTimeout(function () { document.getElementById('enrich-input')?.focus(); }, 50);
    });
    // Fermeture (bouton ✕ .close-modal, clic sur le fond, Échap) : assurée par le
    // câblage générique des modales de l'application — pas de doublon ici.
    document.getElementById('enrich-mode-url')?.addEventListener('click', function () { setMode('url'); });
    document.getElementById('enrich-mode-text')?.addEventListener('click', function () { setMode('text'); });
    document.getElementById('enrich-mode-file')?.addEventListener('click', function () { setMode('file'); });
    document.getElementById('enrich-submit')?.addEventListener('click', submitEnrich);
})();

// ══════════════════════════════════════════
// AGENT COANIMM
// ══════════════════════════════════════════

// { kind: 'script'|'explore'|'generated', scriptId?, label, consigne?, needs_explore? }
const COANIMM_MAX_REPAIR = 2;  // tentatives d'auto-reparation apres echec d'execution
let _coanimmPendingAction = null;
let _coanimmCurrentConsigne = ''; // conservée pour le flux Plan→Execute et la boucle agentique
let _coanimmOverrideProvider  = null; // provider temporaire (crapauduc)
let _coanimmCancelled = false;   // l'utilisateur a demandé l'arrêt du script

// ── Helpers UI ──

// Annonce accessible pour lecteurs d'écran
function _coanimmSetBusy(busy) {
    const btn = document.getElementById('coanimm-generate-btn');
    if (btn) {
        btn.disabled = busy;
        if (busy) btn.setAttribute('aria-busy', 'true');
        else btn.removeAttribute('aria-busy');
    }
    if (!busy) document.getElementById('coanimm-stop-btn')?.classList.add('hidden');

    // Loader VISUEL uniquement (aria-hidden) : le lecteur d'ecran ne le repete jamais ;
    // l'info lui parvient une seule fois via _coanimmAnnounce (deja en place).
    var existing = document.getElementById('coanimm-loader');
    if (busy) {
        if (!existing && btn && btn.parentNode) {
            var loader = document.createElement('div');
            loader.id = 'coanimm-loader';
            loader.className = 'loader-bretzel';
            loader.setAttribute('aria-hidden', 'true');
            loader.style.marginTop = '8px';
            try {
                var svg = _buildBretzelSVG(30, 20);
                loader.appendChild(svg);
                btn.parentNode.insertBefore(loader, btn.nextSibling);
                requestAnimationFrame(function () { _startBretzelAnim(svg, loader); });
            } catch (e) {
                loader.textContent = '\u23F3';
                btn.parentNode.insertBefore(loader, btn.nextSibling);
            }
        }
    } else if (existing) {
        if (existing._cancelAnim) existing._cancelAnim();
        existing.remove();
    }
}

function _coanimmAnnounce(msg) {
    const el = document.getElementById('coanimm-status-announce');
    if (!el) return;
    el.textContent = '';
    setTimeout(() => { el.textContent = msg; }, 200);
}

// Détecte un blocage du confinement (écriture hors dossiers autorisés) dans la sortie
// du script — même si le script s'est terminé sans code d'erreur. Renvoie le chemin ou null.
function _coanimmDetectBlockedPath(data) {
    if (!data) return null;
    const txt = [data.stdout, data.stderr, data.message].filter(Boolean).join("\n");
    const m = txt.match(/hors des dossiers autoris\w*\s*:\s*([\s\S]+?)\.\s*Ajoute ce dossier/i);
    return m ? m[1].trim() : null;
}

// Affiche une alerte accessible (role=alert) proposant d'autoriser le dossier bloqué.
function _coanimmShowBlockedPath(path) {
    const box = document.getElementById('coanimm-blocked-path');
    const msg = document.getElementById('coanimm-blocked-path-msg');
    const addBtn = document.getElementById('coanimm-blocked-path-add');
    const fb = document.getElementById('coanimm-blocked-path-fb');
    if (!box || !path) return false;
    if (msg) msg.textContent = "CoaNIMM a bloqué une action dans un dossier non autorisé en écriture : "
        + path + ". Pour permettre cette tâche, autorise ce dossier puis relance la tâche.";
    if (fb) fb.textContent = '';
    if (addBtn) addBtn.dataset.path = path;
    box.removeAttribute('hidden');
    return true;
}

document.getElementById('coanimm-blocked-path-add')?.addEventListener('click', async function () {
    const path = this.dataset.path || '';
    const fb = document.getElementById('coanimm-blocked-path-fb');
    if (!path) return;
    try {
        const r = await fetch('/api/coanimm/paths', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        const d = await r.json();
        if (d.status === 'error') {
            if (fb) fb.textContent = '🔴 ' + (d.message || 'erreur');
            _coanimmAnnounce(d.message || "Erreur lors de l'ajout du dossier.");
            return;
        }
        if (fb) fb.textContent = "Dossier autorisé. Tu peux relancer la tâche.";
        _coanimmAnnounce("Dossier autorisé en écriture. Relance la tâche pour qu'elle s'exécute.");
        if (typeof _renderCoanimmPaths === 'function') _renderCoanimmPaths(d.paths || []);
        document.getElementById('coanimm-blocked-path')?.setAttribute('hidden', '');
    } catch (e) {
        if (fb) fb.textContent = '🔴 Erreur réseau.';
        _coanimmAnnounce("Erreur réseau lors de l'ajout du dossier.");
    }
});

function _coanimmHideAll() {
    document.getElementById('coanimm-plan').classList.add('hidden');
    document.getElementById('coanimm-code-preview').classList.add('hidden');
    document.getElementById('coanimm-permission').classList.add('hidden');
    document.getElementById('coanimm-result').classList.add('hidden');
    document.getElementById('coanimm-result-code-box')?.classList.add('hidden');
    document.getElementById('coanimm-explore-result')?.classList.add('hidden');
}

function _coanimmShowPermission(label) {
    document.getElementById('coanimm-plan').classList.add('hidden');
    const permBox = document.getElementById('coanimm-permission');
    document.getElementById('coanimm-permission-text').textContent =
        `CoaNIMM demande l'autorisation d'effectuer : ${label}.`;
    permBox.classList.remove('hidden');
    setTimeout(() => { document.getElementById('coanimm-allow-once')?.focus(); }, 50);
}

// Copie le contenu d'un fichier HTML produit dans le presse-papier, en conservant
// la mise en forme (text/html) + un repli texte simple — pour coller dans une messagerie.
async function _coanimmCopyHtmlFile(url) {
    try {
        const resp = await fetch(url);
        const html = await resp.text();
        const tmp = document.createElement('div');
        tmp.innerHTML = html;
        const plain = (tmp.textContent || tmp.innerText || '').trim();
        if (navigator.clipboard && window.ClipboardItem) {
            await navigator.clipboard.write([new ClipboardItem({
                'text/html': new Blob([html], { type: 'text/html' }),
                'text/plain': new Blob([plain], { type: 'text/plain' }),
            })]);
            _coanimmAnnounce('Contenu copié avec sa mise en forme. Collez-le dans votre messagerie.');
        } else if (navigator.clipboard) {
            await navigator.clipboard.writeText(plain);
            _coanimmAnnounce('Contenu copié en texte simple (mise en forme non disponible dans ce navigateur).');
        } else {
            _coanimmAnnounce("La copie automatique n'est pas disponible dans ce navigateur.");
        }
    } catch (e) {
        _coanimmAnnounce('Échec de la copie : ' + (e && e.message ? e.message : 'erreur'));
    }
}

// Affiche les liens de fichiers produits par le script
function _coanimmShowFiles(filesList) {
    const filesDiv = document.getElementById('coanimm-result-files');
    if (!filesDiv) return;
    filesDiv.innerHTML = '';
    if (!filesList || !filesList.length) { filesDiv.setAttribute('hidden', ''); return; }
    const title = document.createElement('p');
    title.style.cssText = 'font-size:0.82rem;font-weight:600;margin:8px 0 4px;';
    title.textContent = 'Fichiers produits :';
    filesDiv.appendChild(title);
    filesList.forEach(f => {
        const a = document.createElement('a');
        a.href = f.url;
        a.textContent = f.filename + ' (' + (f.size > 1024
            ? Math.round(f.size / 1024) + ' Ko' : f.size + ' o') + ')';
        a.style.cssText = 'display:block;margin:2px 0;font-size:0.85rem;color:var(--accent,#6ea8fe);';
        a.setAttribute('download', f.filename);
        filesDiv.appendChild(a);
        if (/\.html?$/i.test(f.filename)) {
            const cp = document.createElement('button');
            cp.type = 'button';
            cp.textContent = 'Copier (mise en forme)';
            cp.setAttribute('aria-label', 'Copier le contenu de ' + f.filename + ' avec sa mise en forme, pour le coller dans votre messagerie');
            cp.style.cssText = 'display:block;margin:0 0 4px;font-size:0.8rem;padding:2px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
            cp.addEventListener('click', () => _coanimmCopyHtmlFile(f.url));
            filesDiv.appendChild(cp);
        }
    });
    filesDiv.removeAttribute('hidden');
    _coanimmAnnounce(filesList.length + ' fichier(s) produit(s) disponible(s) en téléchargement.');
}

// Propose d’enregistrer le script dans la Promptothèque après exécution réussie
function _coanimmMaybeShowSavePanel(code, success) {
    const savePanel   = document.getElementById('coanimm-save-panel');
    const saveLabelEl = document.getElementById('coanimm-save-label');
    const saveFeedback = document.getElementById('coanimm-save-feedback');
    if (!savePanel || !success) return;
    savePanel.removeAttribute('hidden');
    if (saveFeedback) saveFeedback.textContent = '';
    if (saveLabelEl) {
        saveLabelEl.value = '';
        saveLabelEl.placeholder = 'Suggestion en cours…';
        saveLabelEl.disabled = true;
        fetch('/api/coanimm/suggest_name', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ consigne: _coanimmCurrentConsigne || '', thread_id: currentThreadId || null }),
        }).then(r => r.json()).then(d => {
            saveLabelEl.disabled = false;
            saveLabelEl.value = d.name || '';
            saveLabelEl.placeholder = 'Nom du script…';
            if (d.name) saveLabelEl.select();
        }).catch(() => { saveLabelEl.disabled = false; saveLabelEl.placeholder = 'Nom du script…'; });
    }
}

function _coanimmShowResult(data, label) {
    document.getElementById('coanimm-permission').classList.add('hidden');
    const resultBox = document.getElementById('coanimm-result');
    resultBox.classList.remove('hidden');
    const statusEl = document.getElementById('coanimm-result-status');
    const stdoutEl = document.getElementById('coanimm-result-stdout');
    const stderrEl = document.getElementById('coanimm-result-stderr');
    const codeBox  = document.getElementById('coanimm-result-code-box');
    const codeEl   = document.getElementById('coanimm-result-code');

    // Label stderr = élément précédent le textarea dans le DOM
    const stderrLabel = stderrEl ? stderrEl.previousElementSibling : null;
    if (data.status === 'ok') {
        const _corrige = data.code_corrige ? " CoaNIMM a corrigé le script pour cette exécution ; le script enregistré n'a pas été modifié." : '';
        statusEl.textContent = `Terminé (code retour ${data.returncode}).` + _corrige;
        _coanimmAnnounce('Terminé.' + _corrige);
        stdoutEl.value = data.stdout || '';
    } else {
        statusEl.textContent = `Erreur : ${data.message || 'erreur inconnue.'}`;
        _coanimmAnnounce(`Erreur : ${data.message || 'erreur inconnue.'}`);
        stdoutEl.value = data.stdout || '';
    }
    // Masquer la section Erreurs si stderr est vide
    const stderrContent = data.stderr || '';
    stderrEl.value = stderrContent;
    // N'afficher les erreurs que si l'exécution a échoué (returncode != 0 ou status error)
    const execFailed = data.status !== 'ok' || (data.returncode !== undefined && data.returncode !== 0);
    const showStderr = execFailed && stderrContent.trim().length > 0;
    stderrEl.style.display      = showStderr ? '' : 'none';
    if (stderrLabel) stderrLabel.style.display = showStderr ? '' : 'none';
    // Fichiers produits : liens de téléchargement accessibles
    const filesDiv = document.getElementById('coanimm-result-files');
    if (filesDiv) {
        filesDiv.innerHTML = '';
        if (data.files_list && data.files_list.length > 0) {
            const title = document.createElement('p');
            title.style.cssText = 'font-size:0.82rem;font-weight:600;margin:8px 0 4px;';
            title.textContent = 'Fichiers produits :';
            filesDiv.appendChild(title);
            data.files_list.forEach(f => {
                const a = document.createElement('a');
                a.href = f.url;
                a.textContent = f.filename + ' (' + (f.size > 1024
                    ? Math.round(f.size/1024) + ' Ko' : f.size + ' o') + ')';
                a.style.cssText = 'display:block;margin:2px 0;font-size:0.85rem;color:var(--accent,#6ea8fe);';
                a.setAttribute('download', f.filename);
                filesDiv.appendChild(a);
                if (/\.html?$/i.test(f.filename)) {
                    const cp = document.createElement('button');
                    cp.type = 'button';
                    cp.textContent = 'Copier (mise en forme)';
                    cp.setAttribute('aria-label', 'Copier le contenu de ' + f.filename + ' avec sa mise en forme, pour le coller dans votre messagerie');
                    cp.style.cssText = 'display:block;margin:0 0 4px;font-size:0.8rem;padding:2px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
                    cp.addEventListener('click', () => _coanimmCopyHtmlFile(f.url));
                    filesDiv.appendChild(cp);
                }
            });
            filesDiv.removeAttribute('hidden');
        } else {
            filesDiv.setAttribute('hidden', '');
        }
    }
    if (typeof data.code === 'string') {
        codeEl.value = data.code;
        codeBox.classList.remove('hidden');
    } else {
        codeEl.value = '';
        codeBox.classList.add('hidden');
    }
    // Panneau sauvegarde : proposé après exécution réussie
    const savePanel    = document.getElementById('coanimm-save-panel');
    const saveLabelEl  = document.getElementById('coanimm-save-label');
    const saveFeedback = document.getElementById('coanimm-save-feedback');
    if (savePanel) {
        if (data.status === 'ok') {
            savePanel.removeAttribute('hidden');
            if (saveFeedback) saveFeedback.textContent = '';
            // Suggérer un nom via le LLM
            if (saveLabelEl) {
                saveLabelEl.value = '';
                saveLabelEl.placeholder = 'Suggestion en cours…';
                saveLabelEl.disabled = true;
                fetch('/api/coanimm/suggest_name', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        consigne: _coanimmCurrentConsigne || '',
                        thread_id: currentThreadId || null,
                    }),
                }).then(r => r.json()).then(d => {
                    saveLabelEl.disabled = false;
                    saveLabelEl.placeholder = 'Ex. : Trier les fichiers par date';
                    if (d.name) {
                        saveLabelEl.value = d.name;
                        // Sélectionner le texte pour faciliter la modification
                        saveLabelEl.select();
                    }
                }).catch(() => {
                    saveLabelEl.disabled = false;
                    saveLabelEl.placeholder = 'Ex. : Trier les fichiers par date';
                });
            }
        } else {
            savePanel.setAttribute('hidden', '');
        }
    }
    // Détection d'un blocage de confinement (écriture hors dossiers autorisés), accessible.
    document.getElementById('coanimm-blocked-path')?.setAttribute('hidden', '');
    const _blockedPath = _coanimmDetectBlockedPath(data);
    if (_blockedPath) _coanimmShowBlockedPath(_blockedPath);
    const _hasError = (data.status !== 'ok')
        || (data.returncode !== undefined && data.returncode !== 0) || !!_blockedPath;

    // Focus accessible : sur l'alerte/erreur si échec, sinon sur la sortie standard.
    setTimeout(() => {
        let target = null;
        if (_blockedPath) target = document.getElementById('coanimm-blocked-path-add');
        else if (_hasError) target = document.getElementById('coanimm-result-status');
        if (!target) target = document.getElementById('coanimm-result-stdout');
        if (target) target.focus();
    }, 100);
}

// ── Ouverture modale ──

document.getElementById('toggle-coanimm')?.addEventListener('click', function() {
    document.getElementById('coanimm-modal').classList.remove('hidden');
    loadCoanimm();
    loadCoanimmPaths();
    loadCoanimmHistory();
    loadCoanimmCapabilities();
    loadCoanimmWorkflows();
    loadCoanimmSchedules();
    _coanimmSchedPopulateWfPicker();
    loadCoanimmSkills();
    loadCoanimmTools();
    loadCoanimmSecurityLog();
    loadCoanimmBondPicker();
});

// ══════════════════════════════════════════
// SÉLECTEUR DE BOND COANIMM
// ══════════════════════════════════════════
let _coanimmSelectedBond = null; // { id, label, description }

async function loadCoanimmBondPicker() {
    try {
        const r = await fetch('/api/prompts?type=skill');
        const data = await r.json();
        const bonds = Object.entries(data.prompts || {})
            .map(([id, sk]) => ({
                id,
                label: (sk.label || id),
                description: (sk.meta || {}).description || '',
                mots_cles: (sk.meta || {}).mots_cles || [],
            }))
            .sort((a, b) => a.label.localeCompare(b.label, 'fr'));
        _renderCoanimmBondPicker(bonds);
        document.getElementById('coanimm-bond-search')?.addEventListener('input', () => {
            const q = (document.getElementById('coanimm-bond-search')?.value || '').toLowerCase();
            const filtered = bonds.filter(b =>
                b.label.toLowerCase().includes(q) ||
                b.description.toLowerCase().includes(q) ||
                (b.mots_cles || []).some(k => k.toLowerCase().includes(q))
            );
            _renderCoanimmBondList(filtered);
        });
    } catch (e) { console.error('[COANIMM] Erreur chargement bonds :', e); }
}

function _renderCoanimmBondPicker(bonds) {
    _renderCoanimmBondList(bonds);
    _updateCoanimmBondSelectedTag();
}

function _renderCoanimmBondList(bonds) {
    const ul = document.getElementById('coanimm-bond-list');
    if (!ul) return;
    ul.innerHTML = '';
    if (!bonds.length) {
        const li = document.createElement('li');
        li.style.cssText = 'padding:6px 10px;color:var(--text-muted);font-size:0.82rem;';
        li.textContent = 'Aucun bond trouvé.';
        ul.appendChild(li);
        return;
    }
    bonds.forEach(b => {
        const li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', _coanimmSelectedBond?.id === b.id ? 'true' : 'false');
        li.dataset.bondId = b.id;
        const isSelected = _coanimmSelectedBond?.id === b.id;
        li.style.cssText = `padding:7px 10px;cursor:pointer;font-size:0.82rem;border-bottom:1px solid var(--border);
            ${isSelected ? 'background:var(--accent,#6ea8fe);color:#fff;' : ''}`;
        li.innerHTML = `<strong>${b.label}</strong>${b.description ? '<br><span style="font-size:0.78rem;opacity:0.8;">' + b.description + '</span>' : ''}`;
        li.addEventListener('click', () => {
            if (_coanimmSelectedBond?.id === b.id) {
                _coanimmSelectedBond = null;
            } else {
                _coanimmSelectedBond = b;
            }
            // Rafraîchir la liste (pour màj aria-selected + couleur)
            const q = (document.getElementById('coanimm-bond-search')?.value || '').toLowerCase();
            // Re-render avec les items actuels
            const allItems = Array.from(ul.querySelectorAll('li[data-bond-id]')).map(el => ({
                id: el.dataset.bondId,
                label: el.querySelector('strong')?.textContent || el.dataset.bondId,
                description: el.querySelector('span')?.textContent || '',
                mots_cles: []
            }));
            _renderCoanimmBondList(allItems);
            _updateCoanimmBondSelectedTag();
        });
        li.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); li.click(); } });
        li.setAttribute('tabindex', '0');
        ul.appendChild(li);
    });
}

function _updateCoanimmBondSelectedTag() {
    const div = document.getElementById('coanimm-bond-selected');
    if (!div) return;
    if (!_coanimmSelectedBond) {
        div.innerHTML = '<span style="color:var(--text-muted);">Aucun bond sélectionné — détection automatique.</span>';
        return;
    }
    div.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px;background:var(--accent,#6ea8fe);color:#fff;padding:4px 10px;border-radius:20px;font-size:0.82rem;">
        🐸 ${_coanimmSelectedBond.label}
        <button onclick="_coanimmClearBond()" style="background:none;border:none;color:#fff;cursor:pointer;font-size:1rem;line-height:1;padding:0;" aria-label="Effacer le bond sélectionné">✕</button>
    </span>`;
}

function _coanimmClearBond() {
    _coanimmSelectedBond = null;
    const q = (document.getElementById('coanimm-bond-search')?.value || '').toLowerCase();
    // Déclencher un re-render propre en re-chargeant
    loadCoanimmBondPicker();
}


async function loadCoanimmPaths() {
    try {
        const r = await fetch('/api/coanimm/paths');
        const d = await r.json();
        _renderCoanimmPaths(d.paths || []);
    } catch (e) { console.error('[COANIMM] Erreur chargement dossiers :', e); }
}
function _renderCoanimmPaths(paths) {
    const ul = document.getElementById('coanimm-paths-list');
    if (!ul) return;
    ul.innerHTML = '';
    if (!paths.length) {
        const li = document.createElement('li');
        li.style.color = 'var(--text-muted)';
        li.textContent = 'Aucun dossier autorisé (espace de travail uniquement).';
        ul.appendChild(li);
        return;
    }
    paths.forEach(p => {
        const li = document.createElement('li');
        li.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:8px;padding:3px 0;';
        const span = document.createElement('span');
        span.textContent = p;
        span.style.cssText = 'word-break:break-all;';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = 'Retirer';
        btn.setAttribute('aria-label', 'Retirer le dossier ' + p);
        btn.style.cssText = 'font-size:0.78rem;padding:2px 8px;border:1px solid var(--border);border-radius:5px;background:var(--bg-input);color:var(--text);cursor:pointer;flex:0 0 auto;';
        btn.addEventListener('click', () => _removeCoanimmPath(p));
        li.appendChild(span); li.appendChild(btn);
        ul.appendChild(li);
    });
}
async function _addCoanimmPath() {
    const input = document.getElementById('coanimm-path-input');
    const fb = document.getElementById('coanimm-path-feedback');
    const p = (input && input.value || '').trim();
    if (!p) return;
    try {
        const r = await fetch('/api/coanimm/paths', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: p }),
        });
        const d = await r.json();
        if (d.status === 'error') {
            if (fb) fb.textContent = '🔴 ' + d.message;
            _coanimmAnnounce(d.message);
            return;
        }
        if (input) input.value = '';
        if (fb) fb.textContent = 'Dossier ajouté.';
        _coanimmAnnounce('Dossier ajouté aux dossiers autorisés.');
        _renderCoanimmPaths(d.paths || []);
    } catch (e) {
        if (fb) fb.textContent = '🔴 Erreur réseau.';
    }
}
async function _removeCoanimmPath(path) {
    try {
        const r = await fetch('/api/coanimm/paths', {
            method: 'DELETE', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        const d = await r.json();
        _renderCoanimmPaths(d.paths || []);
        _coanimmAnnounce('Dossier retiré.');
    } catch (e) { console.error('[COANIMM] Erreur retrait dossier :', e); }
}
document.getElementById('coanimm-path-add-btn')?.addEventListener('click', _addCoanimmPath);

// ── Historique des tâches CoaNIMM (global, indépendant du fil) ──
function _renderCoanimmHistory(list) {
    const ul = document.getElementById('coanimm-history-list');
    if (!ul) return;
    ul.innerHTML = '';
    if (!list || !list.length) {
        const li = document.createElement('li');
        li.textContent = "Aucune tâche enregistrée pour le moment.";
        li.style.cssText = 'color:var(--text-muted);padding:4px 0;';
        ul.appendChild(li);
        return;
    }
    list.forEach(item => {
        const li = document.createElement('li');
        li.style.cssText = 'display:flex;align-items:flex-start;gap:6px;padding:4px 0;border-bottom:1px solid var(--border);';
        const date = (item.ts || '').replace('T', ' ').slice(0, 16);
        const statusTxt = item.status === 'ok' ? 'réussi' : 'échec';
        const cons = (item.consigne || '').slice(0, 140);
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'coanimm-hist-pick';
        cb.style.marginTop = '3px';
        cb._consigne = item.consigne || '';
        cb.setAttribute('aria-label', 'Inclure dans un ricochet : ' + cons);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = date + ' — ' + statusTxt + ' : ' + cons;
        btn.setAttribute('aria-label', 'Reprendre cette tâche du ' + date + ', ' + statusTxt + ' : ' + cons);
        btn.style.cssText = 'background:none;border:none;color:var(--text);text-align:left;cursor:pointer;font-size:0.82rem;padding:2px 0;flex:1;';
        btn.addEventListener('click', () => {
            const input = document.getElementById('coanimm-consigne');
            if (input) { input.value = item.consigne || ''; input.focus(); }
            _coanimmAnnounce("Consigne reprise dans le champ. Vous pouvez la relancer.");
        });
        li.appendChild(cb);
        li.appendChild(btn);
        if (item.kind === 'workflow' && item.workflow_id) {
            const rerun = document.createElement('button');
            rerun.type = 'button';
            rerun.textContent = '↻ Relancer';
            const entree = (item.parametre || '').trim();
            rerun.setAttribute('aria-label', 'Relancer ce ricochet' + (entree ? ' avec la même entrée : ' + entree.slice(0, 80) : ''));
            rerun.style.cssText = 'font-size:0.78rem;padding:2px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;white-space:nowrap;';
            rerun.addEventListener('click', () => {
                const inp = document.getElementById('coanimm-wf-input');
                if (inp) inp.value = entree;
                const wfLabel = (item.consigne || '').replace(/^\[Ricochet\]\s*/, '').split(' — entrée :')[0];
                _runCoanimmWorkflow(item.workflow_id, wfLabel || 'ricochet');
            });
            li.appendChild(rerun);
        }
        ul.appendChild(li);
    });
}
async function loadCoanimmHistory() {
    try {
        const r = await fetch('/api/coanimm/history');
        const d = await r.json();
        _renderCoanimmHistory(d.history || []);
    } catch (e) { /* silencieux */ }
}
function _recordCoanimmHistory(status, returncode, filesCount) {
    const consigne = (_coanimmCurrentConsigne || '').trim();
    if (!consigne) return;
    const out = (document.getElementById('coanimm-result-stdout')?.value || '').trim();
    const summary = out.split('\n').filter(Boolean).slice(-3).join(' ').slice(0, 300);
    fetch('/api/coanimm/history', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ consigne, status, returncode, files_count: filesCount || 0, summary }),
    }).then(r => r.json()).then(d => { if (d && d.history) _renderCoanimmHistory(d.history); }).catch(() => {});
}
async function _clearCoanimmHistory() {
    try {
        const r = await fetch('/api/coanimm/history', { method: 'DELETE' });
        const d = await r.json();
        _renderCoanimmHistory(d.history || []);
        _coanimmAnnounce("Historique vidé.");
    } catch (e) { /* silencieux */ }
}
document.getElementById('coanimm-history-clear-btn')?.addEventListener('click', _clearCoanimmHistory);

async function _coanimmComposeWorkflowFromHistory() {
    const status = document.getElementById('coanimm-history-wf-status');
    const picks = Array.from(document.querySelectorAll('.coanimm-hist-pick')).filter(c => c.checked);
    if (!picks.length) {
        if (status) status.textContent = 'Cochez au moins une tâche à inclure.';
        _coanimmAnnounce('Cochez au moins une tâche à inclure.');
        return;
    }
    const consignes = picks.map(c => c._consigne || '').filter(Boolean);
    try {
        const r = await fetch('/api/coanimm/workflow_from_history', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ consignes }),
        });
        const d = await r.json();
        const matches = (d && d.matches) || [];
        const matched = matches.filter(m => m.matched);
        const unmatched = matches.filter(m => !m.matched);
        if (!matched.length) {
            const msg = "Aucune tâche cochée ne correspond à un bond validé. Crée d'abord les bonds (case « mémoriser la méthode » après une tâche réussie).";
            if (status) status.textContent = msg;
            _coanimmAnnounce(msg);
            return;
        }
        _coanimmWfSteps = matched.map(m => ({ skill_id: m.skill_id, label: m.label }));
        if (typeof _renderCoanimmWfSteps === 'function') _renderCoanimmWfSteps();
        const det = document.getElementById('coanimm-workflows-details');
        if (det) det.open = true;
        const cdet = document.getElementById('coanimm-wf-compose-details');
        if (cdet) cdet.open = true;
        let msg = matched.length + ' étape(s) ajoutée(s) au compositeur de workflow.';
        if (unmatched.length) msg += ' ' + unmatched.length + ' tâche(s) sans bond correspondant, ignorée(s).';
        msg += ' Donne un nom au ricochet puis enregistre-le.';
        if (status) status.textContent = msg;
        _coanimmAnnounce(msg);
        const nm = document.getElementById('coanimm-wf-name');
        if (nm) setTimeout(() => nm.focus(), 80);
    } catch (e) {
        if (status) status.textContent = 'Erreur lors de la composition du ricochet.';
        console.error('[COANIMM-WF] from history:', e);
    }
}
document.getElementById('coanimm-history-to-wf-btn')?.addEventListener('click', _coanimmComposeWorkflowFromHistory);

document.getElementById('coanimm-workspace-purge-btn')?.addEventListener('click', async () => {
    if (!confirm('Vider l\'espace de travail CoaNIMM ? Tous les fichiers produits seront supprimés définitivement.')) return;
    const status = document.getElementById('coanimm-workspace-status');
    try {
        const r = await fetch('/api/coanimm/workspace', { method: 'DELETE' });
        const d = await r.json();
        if (d.status === 'ok') {
            const n = d.removed || 0;
            const msg = n ? ('Espace de travail vidé : ' + n + ' élément(s) supprimé(s).') : 'Espace de travail déjà vide.';
            if (status) status.textContent = msg;
            _coanimmAnnounce(msg);
        } else if (status) { status.textContent = 'Erreur lors de la purge.'; }
    } catch (e) { if (status) status.textContent = 'Erreur réseau.'; }
});

// ── Outils de CoaNIMM (activables / désactivables) ──
async function loadCoanimmTools() {
    try {
        const r = await fetch('/api/coanimm/tools');
        const d = await r.json();
        _renderCoanimmTools(d.tools || []);
    } catch (e) { /* silencieux */ }
}
function _renderCoanimmTools(tools) {
    const ul = document.getElementById('coanimm-tools-list');
    if (!ul) return;
    ul.innerHTML = '';
    // Résumé global
    const total = tools.length;
    const actifs = tools.filter(t => t.enabled).length;
    const sum = document.createElement('li');
    sum.id = 'coanimm-tools-summary';
    sum.style.cssText = 'list-style:none;color:var(--text-muted);font-size:0.8rem;margin-bottom:6px;';
    sum.textContent = actifs + ' outil' + (actifs > 1 ? 's' : '') + ' actif' + (actifs > 1 ? 's' : '') + ' sur ' + total + '.';
    ul.appendChild(sum);
    // Regrouper par catégorie (ordre de première apparition)
    const cats = [];
    const byCat = {};
    tools.forEach(t => {
        const c = t.category || 'Autres';
        if (!byCat[c]) { byCat[c] = []; cats.push(c); }
        byCat[c].push(t);
    });
    cats.forEach(c => {
        const items = byCat[c];
        const nOn = items.filter(t => t.enabled).length;
        const det = document.createElement('details');
        det.dataset.cat = c;
        det.style.cssText = 'margin:4px 0;border:1px solid var(--border);border-radius:6px;padding:4px 8px;';
        const sm = document.createElement('summary');
        sm.style.cssText = 'cursor:pointer;font-size:0.83rem;';
        sm.textContent = c + ' (' + nOn + '/' + items.length + ' actifs)';
        det.appendChild(sm);
        const inner = document.createElement('ul');
        inner.style.cssText = 'list-style:none;padding:0;margin:6px 0 2px;';
        items.forEach(t => {
            const li = document.createElement('li');
            li.style.cssText = 'padding:3px 0;display:flex;align-items:flex-start;gap:6px;';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.id = 'coanimm-tool-' + t.tool;
            cb.checked = !!t.enabled;
            cb.style.cssText = 'width:auto;margin:2px 0 0;flex:none;';
            cb.addEventListener('change', () => _toggleCoanimmTool(t.tool, cb.checked));
            const lab = document.createElement('label');
            lab.setAttribute('for', cb.id);
            lab.style.cssText = 'font-size:0.82rem;margin:0;cursor:pointer;';
            lab.textContent = t.label;
            li.appendChild(cb); li.appendChild(lab);
            inner.appendChild(li);
        });
        det.appendChild(inner);
        ul.appendChild(det);
    });
}
function _coanimmUpdateToolCounts() {
    const ul = document.getElementById('coanimm-tools-list');
    if (!ul) return;
    let total = 0, on = 0;
    ul.querySelectorAll('details').forEach(det => {
        const cbs = det.querySelectorAll('input[type=checkbox]');
        let n = 0;
        cbs.forEach(cb => { total++; if (cb.checked) { on++; n++; } });
        const sm = det.querySelector('summary');
        if (sm) sm.textContent = (det.dataset.cat || 'Outils') + ' (' + n + '/' + cbs.length + ' actifs)';
    });
    const sumEl = document.getElementById('coanimm-tools-summary');
    if (sumEl) sumEl.textContent = on + ' outil' + (on > 1 ? 's' : '') + ' actif' + (on > 1 ? 's' : '') + ' sur ' + total + '.';
}
async function _toggleCoanimmTool(tool, enabled) {
    try {
        await fetch('/api/coanimm/tools', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool, enabled }),
        });
        _coanimmUpdateToolCounts();
        _coanimmAnnounce(enabled ? 'Outil activé.' : 'Outil désactivé.');
    } catch (e) { _coanimmAnnounce('Erreur lors de la mise à jour de l\'outil.'); }
}

// ── Journal de sécurité CoaNIMM ──
async function loadCoanimmSecurityLog() {
    try {
        const r = await fetch('/api/coanimm/security_log');
        const d = await r.json();
        _renderCoanimmSecurityLog(d.log || [], d.is_owner !== false);
    } catch (e) { /* silencieux */ }
}
function _renderCoanimmSecurityLog(log, isOwner) {
    const ul = document.getElementById('coanimm-seclog-list');
    if (!ul) return;
    ul.innerHTML = '';
    if (!log.length) {
        const li = document.createElement('li');
        li.textContent = 'Aucune exécution enregistrée.';
        li.style.cssText = 'color:var(--text-muted);padding:4px 0;';
        ul.appendChild(li);
    } else {
        log.forEach(e => {
            const li = document.createElement('li');
            li.style.cssText = 'padding:5px 0;border-bottom:1px solid var(--border);';
            const date = (e.ts || '').replace('T', ' ').slice(0, 16);
            const caps = (e.capabilities && e.capabilities.length) ? e.capabilities.join(', ') : 'aucune capacité sensible';
            let txt = date + ' — ' + (e.status || '') + ' — capacités : ' + caps;
            if (e.network) txt += ' — réseau';
            if (e.folders && e.folders.length) txt += ' — dossiers : ' + e.folders.join(', ');
            if (e.files && e.files.length) txt += ' — fichiers : ' + e.files.join(', ');
            if (e.reasons && e.reasons.length) txt += ' — ' + e.reasons.join(' ; ');
            li.textContent = txt;
            ul.appendChild(li);
        });
    }
    const clearBtn = document.getElementById('coanimm-seclog-clear-btn');
    if (clearBtn) clearBtn.style.display = isOwner ? '' : 'none';
}
document.getElementById('coanimm-seclog-details')?.addEventListener('toggle', (ev) => { if (ev.target.open) loadCoanimmSecurityLog(); });
document.getElementById('coanimm-seclog-clear-btn')?.addEventListener('click', async () => {
    if (!confirm('Effacer le journal de sécurité CoaNIMM ?')) return;
    const status = document.getElementById('coanimm-seclog-status');
    try {
        const r = await fetch('/api/coanimm/security_log', { method: 'DELETE' });
        if (r.status === 403) { if (status) status.textContent = 'Réservé au propriétaire (administrateur).'; _coanimmAnnounce('Réservé au propriétaire.'); return; }
        await loadCoanimmSecurityLog();
        if (status) status.textContent = 'Journal effacé.';
        _coanimmAnnounce('Journal de sécurité effacé.');
    } catch (e) { if (status) status.textContent = 'Erreur.'; }
});

// ── Bonds enregistrés : liste, édition, suppression ──
let _coanimmEditingSkillId = null;
async function loadCoanimmSkills() {
    try {
        const r = await fetch('/api/prompts?type=skill');
        const d = await r.json();
        _renderCoanimmSkills(d.prompts || {});
    } catch (e) { /* silencieux */ }
}
function _renderCoanimmSkills(prompts) {
    const ul = document.getElementById('coanimm-skills-list');
    if (!ul) return;
    ul.innerHTML = '';
    const ids = Object.keys(prompts || {});
    if (!ids.length) {
        const li = document.createElement('li');
        li.textContent = "Aucun bond enregistré pour le moment.";
        li.style.cssText = 'color:var(--text-muted);padding:4px 0;';
        ul.appendChild(li);
        return;
    }
    ids.forEach(id => {
        const sk = prompts[id];
        const meta = sk.meta || {};
        const li = document.createElement('li');
        li.style.cssText = 'padding:6px 0;border-bottom:1px solid var(--border);';
        const v = meta.version ? (' (v' + meta.version + ')') : '';
        const head = document.createElement('div');
        head.style.cssText = 'font-weight:600;';
        head.textContent = (sk.label || '(sans nom)') + v;
        li.appendChild(head);
        if (meta.description) {
            const desc = document.createElement('div');
            desc.style.cssText = 'color:var(--text-muted);font-size:0.8rem;margin:2px 0;';
            desc.textContent = meta.description;
            li.appendChild(desc);
        }
        const _rok = parseInt(meta.runs_ok || 0, 10), _rerr = parseInt(meta.runs_err || 0, 10);
        if (_rok + _rerr > 0) {
            const fiab = document.createElement('div');
            fiab.style.cssText = 'color:var(--text-muted);font-size:0.8rem;margin:2px 0;';
            fiab.textContent = 'Fiabilité : ' + _rok + ' réussite' + (_rok > 1 ? 's' : '') + ', ' + _rerr + ' échec' + (_rerr > 1 ? 's' : '') + '.';
            li.appendChild(fiab);
        }
        const actions = document.createElement('div');
        actions.style.cssText = 'display:flex;gap:8px;margin-top:4px;';
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.textContent = 'Modifier';
        edit.setAttribute('aria-label', 'Modifier le bond ' + (sk.label || ''));
        edit.style.cssText = 'font-size:0.8rem;padding:3px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
        edit.addEventListener('click', () => _coanimmEditSkill(id, sk));
        const del = document.createElement('button');
        del.type = 'button';
        del.textContent = 'Supprimer';
        del.setAttribute('aria-label', 'Supprimer le bond ' + (sk.label || ''));
        del.style.cssText = 'font-size:0.8rem;padding:3px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
        del.addEventListener('click', () => _coanimmDeleteSkill(id, sk.label || ''));
        const run = document.createElement('button');
        run.type = 'button';
        run.textContent = '▶ Exécuter';
        run.setAttribute('aria-label', 'Exécuter le bond ' + (sk.label || '') + ' dans CoaNIMM');
        run.style.cssText = 'font-size:0.8rem;padding:3px 10px;border:none;border-radius:6px;background:var(--accent,#2e7d32);color:#fff;cursor:pointer;font-weight:600;';
        run.addEventListener('click', () => _coanimmRunBondDialog(id, sk));
        actions.appendChild(edit); actions.appendChild(del); actions.appendChild(run);
        li.appendChild(actions);
        ul.appendChild(li);
    });
}
function _coanimmEditSkill(id, sk) {
    _coanimmEditingSkillId = id;
    const meta = sk.meta || {};
    const form = document.getElementById('coanimm-skill-edit');
    const name = document.getElementById('coanimm-skill-edit-name');
    const desc = document.getElementById('coanimm-skill-edit-desc');
    const kw = document.getElementById('coanimm-skill-edit-keywords');
    const method = document.getElementById('coanimm-skill-edit-method');
    if (name) name.value = sk.label || '';
    if (desc) desc.value = meta.description || '';
    if (kw) kw.value = (meta.mots_cles || []).join(', ');
    if (method) method.value = sk.text || '';
    if (form) form.classList.remove('hidden');
    const title = document.getElementById('coanimm-skill-edit-title');
    setTimeout(() => { if (title) title.focus(); }, 50);
}
async function _coanimmSaveSkillEdit() {
    if (!_coanimmEditingSkillId) return;
    const status = document.getElementById('coanimm-skills-status');
    const name = document.getElementById('coanimm-skill-edit-name');
    const desc = document.getElementById('coanimm-skill-edit-desc');
    const kw = document.getElementById('coanimm-skill-edit-keywords');
    const method = document.getElementById('coanimm-skill-edit-method');
    const body = {
        label: name ? name.value : null,
        description: desc ? desc.value : null,
        mots_cles: kw ? kw.value.split(',').map(x => x.trim()).filter(Boolean) : null,
        corps: method ? method.value : null,
    };
    try {
        const r = await fetch('/api/coanimm/skills/' + encodeURIComponent(_coanimmEditingSkillId) + '/update', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) { if (status) status.textContent = 'Erreur lors de la modification.'; _coanimmAnnounce('Erreur lors de la modification du bond.'); return; }
        document.getElementById('coanimm-skill-edit')?.classList.add('hidden');
        _coanimmEditingSkillId = null;
        await loadCoanimmSkills();
        if (typeof _coanimmWfPopulateSkillPicker === 'function') _coanimmWfPopulateSkillPicker();
        if (status) status.textContent = 'Bond modifié (nouvelle version enregistrée).';
        _coanimmAnnounce('Bond modifié, nouvelle version enregistrée.');
    } catch (e) { if (status) status.textContent = 'Erreur réseau.'; }
}
async function _coanimmDeleteSkill(id, label) {
    if (!confirm('Supprimer définitivement le bond « ' + label + ' » ?')) return;
    const status = document.getElementById('coanimm-skills-status');
    try {
        const r = await fetch('/api/coanimm/skills/' + encodeURIComponent(id), { method: 'DELETE' });
        if (!r.ok) { if (status) status.textContent = 'Erreur lors de la suppression.'; return; }
        await loadCoanimmSkills();
        if (typeof _coanimmWfPopulateSkillPicker === 'function') _coanimmWfPopulateSkillPicker();
        if (status) status.textContent = 'Bond supprimé.';
        _coanimmAnnounce('Bond supprimé.');
    } catch (e) { if (status) status.textContent = 'Erreur réseau.'; }
}
// ── Exécuter un bond depuis la liste ──
function _coanimmRunBondDialog(id, sk) {
    document.getElementById('coanimm-run-bond-dialog')?.remove();
    const meta = sk.meta || {};
    const overlay = document.createElement('div');
    overlay.id = 'coanimm-run-bond-dialog';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'crbd-title');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:2000;display:flex;align-items:center;justify-content:center;';
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--bg-panel,#fff);border-radius:10px;padding:20px;max-width:500px;width:92%;display:flex;flex-direction:column;gap:10px;border:1px solid var(--border);';
    const title = document.createElement('h3');
    title.id = 'crbd-title';
    title.style.cssText = 'margin:0;font-size:1rem;';
    title.textContent = '▶ Exécuter : ' + (sk.label || id);
    box.appendChild(title);
    if (meta.description) {
        const desc = document.createElement('p');
        desc.style.cssText = 'margin:0;font-size:0.82rem;color:var(--text-muted);';
        desc.textContent = meta.description;
        box.appendChild(desc);
    }
    const lbl = document.createElement('label');
    lbl.setAttribute('for', 'crbd-consigne');
    lbl.style.cssText = 'font-size:0.85rem;font-weight:600;';
    lbl.textContent = 'Vos instructions pour ce bond :';
    box.appendChild(lbl);
    const textarea = document.createElement('textarea');
    textarea.id = 'crbd-consigne';
    textarea.rows = 4;
    textarea.placeholder = 'Décrivez votre demande spécifique…';
    textarea.style.cssText = 'width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);font-size:0.9rem;resize:vertical;box-sizing:border-box;';
    box.appendChild(textarea);
    const hint = document.createElement('p');
    hint.style.cssText = 'margin:0;font-size:0.78rem;color:var(--text-muted);';
    hint.textContent = 'Ctrl+Entrée pour lancer · Échap pour annuler';
    box.appendChild(hint);
    const btns = document.createElement('div');
    btns.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:4px;';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = 'Annuler';
    cancel.style.cssText = 'padding:6px 16px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
    cancel.addEventListener('click', () => overlay.remove());
    const launch = document.createElement('button');
    launch.type = 'button';
    launch.textContent = '🐸 Lancer CoaNIMM';
    launch.style.cssText = 'padding:6px 16px;border:none;border-radius:6px;background:var(--accent,#2e7d32);color:#fff;cursor:pointer;font-weight:600;';
    launch.addEventListener('click', () => {
        const consigne = textarea.value.trim();
        if (!consigne) { textarea.focus(); return; }
        overlay.remove();
        _coanimmLaunchWithBond(id, sk, consigne);
    });
    textarea.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); launch.click(); }
        if (e.key === 'Escape') { e.preventDefault(); overlay.remove(); }
    });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    btns.appendChild(cancel); btns.appendChild(launch);
    box.appendChild(btns);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    setTimeout(() => textarea.focus(), 50);
}

function _coanimmLaunchWithBond(id, sk, consigne) {
    _coanimmSelectedBond = { id, label: sk.label || id, description: (sk.meta || {}).description || '' };
    _updateCoanimmBondSelectedTag();
    const modal = document.getElementById('coanimm-modal');
    if (modal && modal.classList.contains('hidden')) {
        document.getElementById('toggle-coanimm')?.click();
    }
    setTimeout(() => {
        const input = document.getElementById('coanimm-consigne');
        if (input) { input.value = consigne; input.focus(); }
        _coanimmAnnounce('Bond « ' + (sk.label || id) + ' » sélectionné. Consigne pré-remplie. Appuyez sur Ctrl+Entrée pour lancer.');
    }, 150);
}

document.getElementById('coanimm-skill-edit-save')?.addEventListener('click', _coanimmSaveSkillEdit);
document.getElementById('coanimm-skill-edit-cancel')?.addEventListener('click', () => {
    document.getElementById('coanimm-skill-edit')?.classList.add('hidden');
    _coanimmEditingSkillId = null;
    _coanimmAnnounce('Modification annulée.');
});

// ── Capacités autorisées (réseau / programme / e-mail) ──
let _coanimmIsOwner = true;
function _renderCoanimmCapabilities(data) {
    const ul = document.getElementById('coanimm-caps-list');
    if (!ul) return;
    ul.innerHTML = '';
    _coanimmIsOwner = (data.is_owner !== false);
    const granted = new Set(data.granted || []);
    (data.grantable || []).forEach(item => {
        const li = document.createElement('li');
        li.style.cssText = 'padding:4px 0;display:flex;align-items:flex-start;gap:6px;';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.id = 'coanimm-cap-' + item.capability;
        cb.checked = granted.has(item.capability);
        cb.disabled = !_coanimmIsOwner;
        cb.style.cssText = 'width:auto;margin:2px 0 0;flex:none;';
        cb.addEventListener('change', () => _toggleCoanimmCapability(item.capability, cb.checked));
        const lab = document.createElement('label');
        lab.setAttribute('for', cb.id);
        lab.style.cssText = 'font-size:0.82rem;margin:0;cursor:pointer;';
        lab.textContent = item.label;
        li.appendChild(cb); li.appendChild(lab);
        ul.appendChild(li);
    });
    if (!_coanimmIsOwner) {
        const note = document.createElement('li');
        note.style.cssText = 'padding:4px 0;font-size:0.8rem;color:var(--text-muted);';
        note.textContent = "Seul le propriétaire (profil administrateur) peut accorder durablement ces capacités. Tu peux les autoriser « pour cette fois » au moment de l'exécution.";
        ul.appendChild(note);
    }
}
async function loadCoanimmCapabilities() {
    try {
        const r = await fetch('/api/coanimm/capabilities');
        _renderCoanimmCapabilities(await r.json());
    } catch (e) { /* silencieux */ }
}
async function _toggleCoanimmCapability(cap, grant) {
    try {
        const r = await fetch('/api/coanimm/capabilities', {
            method: grant ? 'POST' : 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ capability: cap }),
        });
        if (r.status === 403) {
            _coanimmAnnounce("Réservé au propriétaire : seul le profil administrateur peut modifier les capacités durables.");
            loadCoanimmCapabilities();
            return;
        }
        if (!r.ok) { _coanimmAnnounce("Erreur lors de la mise à jour de la capacité."); return; }
        _coanimmAnnounce(grant ? "Capacité autorisée durablement pour les scripts." : "Capacité retirée.");
    } catch (e) { _coanimmAnnounce("Erreur lors de la mise à jour de la capacité."); }
}

// ── Ricochets CoaNIMM ──────────────────────────────────────────────────────────

let _coanimmWfSteps = []; // [{skill_id, label}]

// ── Annonce des ricochets planifiés qui se sont exécutés en arrière-plan ──
// La zone aria-live est hors du panneau CoaNIMM : l'annonce fonctionne même
// panneau fermé. Lecture unique côté serveur (les notifications sont consommées).
const _COANIMM_NOTIF_INTERVAL_MS = 90000;

async function _coanimmPollScheduleNotifications() {
    try {
        const r = await fetch('/api/coanimm/schedules/notifications', { method: 'POST' });
        const d = await r.json();
        (d.notifications || []).forEach(n => {
            const quand = (n.quand || '').replace('T', ' à ').slice(0, 16);
            const verdict = n.statut === 'ok' ? 'a réussi' : 'a échoué';
            _coanimmAnnounce(`Ricochet planifié « ${n.label} » ${verdict}`
                + (quand ? ` (${quand})` : '') + '.'
                + (n.statut !== 'ok' && n.message ? ' ' + n.message : ''));
        });
        if ((d.notifications || []).length) loadCoanimmSchedules().catch(() => {});
    } catch (e) { /* silencieux : pas de bruit si le serveur ne répond pas */ }
}
setInterval(_coanimmPollScheduleNotifications, _COANIMM_NOTIF_INTERVAL_MS);
setTimeout(_coanimmPollScheduleNotifications, 5000);

// ── Vérifier les faits d'une réponse (recherche web + sources) ──
// Le résultat s'insère REPLIÉ : une seule ligne de bilan, dépliable à la demande,
// et refermable. Objectif : ne pas alourdir le fil ni la lecture séquentielle.
function _verifBilanCourt(verdict, nbSources) {
    const t = (verdict || '').toLowerCase();
    let etat = 'résultat disponible';
    if (/aucune affirmation|rien à vérifier|trop court/.test(t)) etat = 'rien à vérifier';
    else if (/erron|incorrect|faux|inexact|douteu|contredit/.test(t)) etat = 'points à revoir';
    else if (/tout est correct|tout concorde|exact|confirmé/.test(t)) etat = 'rien à signaler';
    return `Vérification des faits : ${etat}` + (nbSources ? ` (${nbSources} source${nbSources > 1 ? 's' : ''})` : '');
}

async function _verifierReponse(texte, bulle) {
    if (!texte || texte.trim().length < 40) {
        _srAnnounce("Ce message est trop court pour être vérifié.");
        return;
    }
    _srAnnounce("Vérification en cours, recherche des sources…");
    bulle?.querySelector('.verif-bloc')?.remove();      // une seule vérification à la fois
    let bloc = null;
    if (bulle) {
        bloc = document.createElement('details');
        bloc.className = 'verif-bloc';
        bloc.style.cssText = 'margin-top:6px;font-size:0.84rem;';
        const som = document.createElement('summary');
        som.textContent = 'Vérification en cours…';
        som.style.cursor = 'pointer';
        bloc.appendChild(som);
        bulle.appendChild(bloc);
    }
    try {
        const r = await fetch('/api/verify', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: texte, thread_id: currentThreadId || null }),
        });
        const d = await r.json();
        const verdict = d.verdict || 'Aucun verdict.';
        const sources = d.sources || [];
        if (!bloc) { _srAnnounce(verdict); return; }

        bloc.innerHTML = '';
        const som = document.createElement('summary');
        som.textContent = _verifBilanCourt(verdict, sources.length);
        som.style.cursor = 'pointer';
        bloc.appendChild(som);

        const corps = document.createElement('div');
        corps.style.cssText = 'padding:6px 0 0 4px;border-left:2px solid var(--border);padding-left:8px;margin-top:4px;';
        const p = document.createElement('div');
        p.style.whiteSpace = 'pre-wrap';
        p.textContent = verdict;
        corps.appendChild(p);
        if (sources.length) {
            const ul = document.createElement('ul');
            ul.setAttribute('aria-label', 'Sources de la vérification');
            ul.style.cssText = 'margin:6px 0 0;padding-left:1.2em;';
            sources.forEach(s => {
                const li = document.createElement('li');
                const a = document.createElement('a');
                a.href = s.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
                a.textContent = s.title || s.url;
                li.appendChild(a);
                ul.appendChild(li);
            });
            corps.appendChild(ul);
        }
        const fermer = document.createElement('button');
        fermer.type = 'button';
        fermer.textContent = 'Retirer la vérification';
        fermer.style.cssText = 'margin-top:6px;font-size:0.78rem;padding:2px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
        fermer.addEventListener('click', () => { bloc.remove(); _srAnnounce('Vérification retirée.'); });
        corps.appendChild(fermer);
        bloc.appendChild(corps);

        // Annonce : le bilan court d'abord, le détail reste consultable au besoin.
        _srAnnounce(som.textContent + '. Dépliez la vérification pour le détail.');
    } catch (e) {
        if (bloc) {
            bloc.innerHTML = '';
            const som = document.createElement('summary');
            som.textContent = 'Vérification impossible (erreur réseau).';
            bloc.appendChild(som);
        }
        _srAnnounce('Vérification impossible.');
    }
}

// ── Raisonnement des modèles de pensée (deepseek-reasoner…) ──
// Il arrive dans un champ séparé et était jeté. On l'expose REPLIÉ : disponible
// pour qui veut comprendre, invisible pour qui veut juste la réponse.
let _streamRaisonnement = '';

function _ajouterRaisonnement(bulle, texte) {
    if (!bulle || !texte) return;
    bulle.querySelector('.raisonnement-bloc')?.remove();
    const bloc = document.createElement('details');
    bloc.className = 'raisonnement-bloc';
    bloc.style.cssText = 'margin-top:6px;font-size:0.84rem;';
    const som = document.createElement('summary');
    const mots = texte.split(/\s+/).length;
    som.textContent = `Raisonnement du modèle (environ ${Math.round(mots / 10) * 10} mots)`;
    som.style.cursor = 'pointer';
    bloc.appendChild(som);
    const corps = document.createElement('div');
    corps.style.cssText = 'white-space:pre-wrap;padding-left:8px;border-left:2px solid var(--border);margin-top:4px;color:var(--text-muted);';
    corps.textContent = texte;
    bloc.appendChild(corps);
    bulle.appendChild(bloc);
}

// ── Orientation dans une réponse longue ──
// Une réponse se découvre linéairement à la voix ou en braille : on ne sait pas où
// elle va ni combien il reste. On annonce donc sa structure AVANT de la lire, à
// partir des titres réellement rendus (qui sont aussi les points de navigation du
// lecteur d'écran). Purement local : aucun appel, aucun coût.
const _PLAN_SEUIL_MOTS = 120;   // en dessous, l'annonce serait du bruit

function _planDeLaReponse(bulle) {
    if (!bulle) return '';
    const texte = (bulle.textContent || '').trim();
    const mots = texte ? texte.split(/\s+/).length : 0;
    if (mots < _PLAN_SEUIL_MOTS) return '';

    const titres = Array.from(bulle.querySelectorAll('h1, h2, h3, h4'))
        .map(h => (h.textContent || '').trim())
        .filter(Boolean);
    if (titres.length >= 2) {
        const liste = titres.slice(0, 6).join(', ');
        const reste = titres.length > 6 ? `, et ${titres.length - 6} autres` : '';
        return `${titres.length} sections : ${liste}${reste}.`;
    }
    // Pas de titres : on situe au moins l'ampleur et la forme
    const puces = bulle.querySelectorAll('li').length;
    const blocsCode = bulle.querySelectorAll('pre').length;
    const parties = [`environ ${Math.round(mots / 10) * 10} mots`];
    if (puces >= 3) parties.push(`${puces} points`);
    if (blocsCode) parties.push(`${blocsCode} bloc${blocsCode > 1 ? 's' : ''} de code`);
    return parties.join(', ') + '.';
}

// ── Journal de fonctionnement ──
// Ces décisions n'existaient que dans la console : inaccessible en pratique.
async function loadDiagnostics() {
    const ul = document.getElementById('diagnostics-list');
    if (!ul) return;
    try {
        const r = await fetch('/api/diagnostics');
        const d = await r.json();
        const lignes = d.diagnostics || [];
        ul.innerHTML = '';
        if (!lignes.length) {
            const li = document.createElement('li');
            li.textContent = 'Rien à signaler pour le moment.';
            li.style.cssText = 'color:var(--text-muted);padding:4px 0;';
            ul.appendChild(li);
            return;
        }
        lignes.forEach(e => {
            const li = document.createElement('li');
            li.style.cssText = 'padding:4px 0;border-bottom:1px solid var(--border);';
            const quand = (e.ts || '').replace('T', ' à ').slice(0, 16);
            li.textContent = `${quand} — ${e.categorie} : ${e.message}`;
            ul.appendChild(li);
        });
    } catch (e) { /* silencieux */ }
}

// Le panneau ne se lit que si on l'ouvre : sans indication, une décision
// importante (panne de fournisseur, cache désactivé) passerait inaperçue.
// Le titre du panneau porte donc le nombre d'entrées non lues.
async function _majBadgeDiagnostics() {
    const som = document.querySelector('#diagnostics-details > summary');
    if (!som) return;
    try {
        const r = await fetch('/api/diagnostics');
        const d = await r.json();
        const lignes = d.diagnostics || [];
        let vu = '';
        try { vu = localStorage.getItem('diagnostics_vu') || ''; } catch (e) {}
        const nouveaux = lignes.filter(e => (e.ts || '') > vu).length;
        som.textContent = '🩺 Journal de fonctionnement'
            + (nouveaux ? ` — ${nouveaux} nouvelle${nouveaux > 1 ? 's' : ''} entrée${nouveaux > 1 ? 's' : ''}` : '');
    } catch (e) { /* silencieux */ }
}

document.getElementById('diagnostics-details')?.addEventListener('toggle', async function () {
    if (!this.open) return;
    await loadDiagnostics();
    try {
        const r = await fetch('/api/diagnostics');
        const d = await r.json();
        const plus_recent = (d.diagnostics || [])[0];
        if (plus_recent) localStorage.setItem('diagnostics_vu', plus_recent.ts || '');
    } catch (e) {}
    _majBadgeDiagnostics();
});
_majBadgeDiagnostics();
setInterval(_majBadgeDiagnostics, 120000);
document.getElementById('diagnostics-clear-btn')?.addEventListener('click', async () => {
    try {
        await fetch('/api/diagnostics', { method: 'DELETE' });
        await loadDiagnostics();
        _coanimmAnnounce('Journal de fonctionnement vidé.');
    } catch (e) { /* silencieux */ }
});

// ── Serveurs MCP distants ──
async function loadMcpServers() {
    try {
        const r = await fetch('/api/mcp/servers');
        const d = await r.json();
        _renderMcpServers(d.servers || [], d.is_owner !== false);
    } catch (e) { /* silencieux */ }
}

function _renderMcpServers(servers, isOwner) {
    const ul = document.getElementById('mcp-servers-list');
    if (!ul) return;
    ul.innerHTML = '';
    const form = document.getElementById('mcp-form');
    if (form) form.style.display = isOwner ? '' : 'none';
    if (!servers.length) {
        const li = document.createElement('li');
        li.textContent = 'Aucun serveur MCP configuré.';
        li.style.cssText = 'color:var(--text-muted);padding:4px 0;';
        ul.appendChild(li);
        return;
    }
    servers.forEach(s => {
        const li = document.createElement('li');
        li.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid var(--border);flex-wrap:wrap;';
        const span = document.createElement('span');
        span.style.cssText = 'flex:1;min-width:0;';
        span.textContent = (s.name || 'serveur') + ' — ' + (s.url || '')
            + (s.a_jeton ? ', jeton enregistré' : ', sans jeton')
            + (s.actif === false ? ' (désactivé)' : '');
        li.appendChild(span);
        if (isOwner) {
            const tog = document.createElement('button');
            tog.type = 'button';
            tog.textContent = s.actif === false ? 'Activer' : 'Désactiver';
            tog.setAttribute('aria-label', (s.actif === false ? 'Activer' : 'Désactiver') + ' le serveur MCP ' + (s.name || ''));
            tog.style.cssText = 'font-size:0.78rem;padding:2px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
            tog.addEventListener('click', async () => {
                try {
                    const r = await fetch('/api/mcp/servers/' + encodeURIComponent(s.id) + '/toggle', { method: 'POST' });
                    const d = await r.json();
                    if (d.servers) _renderMcpServers(d.servers, isOwner);
                    _coanimmAnnounce('Serveur MCP ' + (s.actif === false ? 'activé.' : 'désactivé.'));
                } catch (e) { /* silencieux */ }
            });
            const del = document.createElement('button');
            del.type = 'button';
            del.textContent = 'Supprimer';
            del.setAttribute('aria-label', 'Supprimer le serveur MCP ' + (s.name || ''));
            del.style.cssText = tog.style.cssText;
            del.addEventListener('click', async () => {
                try {
                    const r = await fetch('/api/mcp/servers/' + encodeURIComponent(s.id), { method: 'DELETE' });
                    const d = await r.json();
                    if (d.servers) _renderMcpServers(d.servers, isOwner);
                    _coanimmAnnounce('Serveur MCP supprimé.');
                } catch (e) { /* silencieux */ }
            });
            li.appendChild(tog);
            li.appendChild(del);
        }
        ul.appendChild(li);
    });
}

document.getElementById('mcp-add-btn')?.addEventListener('click', async () => {
    const name = (document.getElementById('mcp-name')?.value || '').trim();
    const url = (document.getElementById('mcp-url')?.value || '').trim();
    const jeton = document.getElementById('mcp-token')?.value || '';
    if (!url) { _coanimmAnnounce("Indique l'adresse du serveur MCP."); return; }
    try {
        const r = await fetch('/api/mcp/servers', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url, jeton: jeton || null }),
        });
        const d = await r.json();
        if (r.ok && d.servers) {
            _renderMcpServers(d.servers, true);
            const t = document.getElementById('mcp-token');
            if (t) t.value = '';           // ne jamais laisser le secret à l'écran
            _coanimmAnnounce('Serveur MCP ajouté.');
        } else {
            _coanimmAnnounce('Ajout refusé : ' + (d.detail || 'erreur.'));
        }
    } catch (e) { _coanimmAnnounce("Erreur réseau lors de l'ajout du serveur MCP."); }
});
document.getElementById('mcp-details')?.addEventListener('toggle', function () {
    if (this.open) loadMcpServers();
});

// ── Sauvegarde (dossier synchronisé cloud-agnostique) ──
function _renderBackupStatus(d) {
    const line = document.getElementById('backup-status-line');
    const folderInput = document.getElementById('backup-folder-path');
    const autoCb = document.getElementById('backup-auto-enabled');
    const dismissedCb = document.getElementById('backup-dismissed');
    if (folderInput) folderInput.value = d.folder_path || '';
    if (autoCb) autoCb.checked = !!d.auto_enabled;
    if (dismissedCb) dismissedCb.checked = !!d.dismissed;
    if (!line) return;
    if (!d.last_backup_at) {
        line.textContent = 'Aucune sauvegarde effectuée pour le moment.';
        return;
    }
    const date = new Date(d.last_backup_at).toLocaleString('fr-FR');
    line.textContent = (d.last_backup_ok ? '✅ ' : '⚠️ ') + 'Dernière sauvegarde : ' + date
        + (d.last_backup_message ? ' — ' + d.last_backup_message : '');
}

async function loadBackupStatus() {
    const line = document.getElementById('backup-status-line');
    const form = document.getElementById('backup-section');
    try {
        const r = await fetch('/api/backup/status');
        if (r.status === 403) {
            if (form) form.querySelectorAll('input, button').forEach(el => el.disabled = true);
            if (line) line.textContent = 'Réservé au propriétaire du profil.';
            return;
        }
        const d = await r.json();
        _renderBackupStatus(d);
    } catch (e) { if (line) line.textContent = 'Erreur lors de la lecture du statut.'; }
}

document.getElementById('backup-save-btn')?.addEventListener('click', async () => {
    const folder_path = (document.getElementById('backup-folder-path')?.value || '').trim();
    const auto_enabled = !!document.getElementById('backup-auto-enabled')?.checked;
    const dismissed = !!document.getElementById('backup-dismissed')?.checked;
    try {
        const r = await fetch('/api/backup/config', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path, auto_enabled, dismissed }),
        });
        const d = await r.json();
        if (r.ok) {
            _renderBackupStatus(d);
            _coanimmAnnounce('Réglages de sauvegarde enregistrés.');
            _checkBackupBanner();
        } else {
            _coanimmAnnounce('Enregistrement refusé : ' + (d.detail || 'erreur.'));
        }
    } catch (e) { _coanimmAnnounce('Erreur réseau lors de l’enregistrement.'); }
});

document.getElementById('backup-run-btn')?.addEventListener('click', async () => {
    const line = document.getElementById('backup-status-line');
    if (line) line.textContent = 'Sauvegarde en cours…';
    _coanimmAnnounce('Sauvegarde en cours.');
    try {
        const r = await fetch('/api/backup/run', { method: 'POST' });
        const d = await r.json();
        if (r.ok) {
            await loadBackupStatus();
            _coanimmAnnounce(d.message || 'Sauvegarde terminée.');
            _checkBackupBanner();
        } else {
            if (line) line.textContent = 'Échec : ' + (d.detail || 'erreur.');
            _coanimmAnnounce('Sauvegarde refusée : ' + (d.detail || 'erreur.'));
        }
    } catch (e) {
        if (line) line.textContent = 'Erreur réseau pendant la sauvegarde.';
        _coanimmAnnounce('Erreur réseau pendant la sauvegarde.');
    }
});

document.getElementById('backup-details')?.addEventListener('toggle', function () {
    if (this.open) loadBackupStatus();
});

async function _checkBackupBanner() {
    const banner = document.getElementById('backup-warning-banner');
    const text = document.getElementById('backup-warning-text');
    if (!banner) return;
    try {
        const r = await fetch('/api/backup/status');
        if (r.status === 403) { banner.classList.add('hidden'); return; } // pas propriétaire : rien à faire, pas d'inquiétude inutile
        const d = await r.json();
        if (d.dismissed) { banner.classList.add('hidden'); return; } // choix explicite de l'utilisateur : respecté
        if (!d.folder_path) {
            if (text) text.textContent = 'Sauvegarde non configurée';
            banner.classList.remove('hidden');
        } else if (d.last_backup_ok === false) {
            if (text) text.textContent = 'Dernière sauvegarde en échec';
            banner.classList.remove('hidden');
        } else {
            banner.classList.add('hidden');
        }
    } catch (e) { banner.classList.add('hidden'); }
}

document.getElementById('backup-banner-open-settings')?.addEventListener('click', () => {
    document.getElementById('settings-modal').classList.remove('hidden');
    document.querySelectorAll('.settings-tab').forEach(b => {
        const isParams = b.dataset.tab === 'params';
        b.classList.toggle('active', isParams);
        b.setAttribute('aria-selected', isParams ? 'true' : 'false');
    });
    document.querySelectorAll('.settings-tab-content').forEach(c => {
        c.classList.toggle('hidden', c.id !== 'settings-tab-params');
    });
    const details = document.getElementById('backup-details');
    if (details) details.open = true;
    loadBackupStatus();
});

// ── Ricochets planifiés ──
const _JOURS_SEMAINE = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];

async function loadCoanimmSchedules() {
    try {
        const r = await fetch('/api/coanimm/schedules');
        const d = await r.json();
        _renderCoanimmSchedules(d.schedules || [], d.is_owner !== false);
    } catch (e) { /* silencieux */ }
}

function _renderCoanimmSchedules(scheds, isOwner) {
    const ul = document.getElementById('coanimm-schedules-list');
    if (!ul) return;
    ul.innerHTML = '';
    const form = document.getElementById('coanimm-sched-form');
    if (form) form.style.display = isOwner ? '' : 'none';
    if (!scheds.length) {
        const li = document.createElement('li');
        li.textContent = 'Aucun ricochet planifié.';
        li.style.cssText = 'color:var(--text-muted);padding:4px 0;';
        ul.appendChild(li);
        return;
    }
    scheds.forEach(s => {
        const li = document.createElement('li');
        li.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid var(--border);flex-wrap:wrap;';
        const quand = (s.jour === null || s.jour === undefined || s.jour === '')
            ? 'tous les jours' : 'le ' + (_JOURS_SEMAINE[s.jour] || '?');
        const hh = String(s.heure).padStart(2, '0') + ':' + String(s.minute).padStart(2, '0');
        const entree = (s.parametre || '').trim();
        const statut = s.dernier_statut ? (' — dernier lancement : ' + (s.dernier_statut === 'ok' ? 'réussi' : s.dernier_statut)) : '';
        const span = document.createElement('span');
        span.style.cssText = 'flex:1;min-width:0;';
        span.textContent = (s.label || '(sans nom)') + ', ' + quand + ' à ' + hh
            + (entree ? ', entrée : ' + entree.slice(0, 60) : '') + statut
            + (s.actif === false ? ' (désactivé)' : '');
        li.appendChild(span);
        if (isOwner) {
            const tog = document.createElement('button');
            tog.type = 'button';
            tog.textContent = s.actif === false ? 'Activer' : 'Désactiver';
            tog.setAttribute('aria-label', (s.actif === false ? 'Activer' : 'Désactiver') + ' la planification de ' + (s.label || ''));
            tog.style.cssText = 'font-size:0.78rem;padding:2px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);cursor:pointer;';
            tog.addEventListener('click', async () => {
                try {
                    const r = await fetch('/api/coanimm/schedules/' + encodeURIComponent(s.id) + '/toggle', { method: 'POST' });
                    const d = await r.json();
                    if (d.schedules) _renderCoanimmSchedules(d.schedules, isOwner);
                    _coanimmAnnounce('Planification ' + (s.actif === false ? 'activée.' : 'désactivée.'));
                } catch (e) { /* silencieux */ }
            });
            const del = document.createElement('button');
            del.type = 'button';
            del.textContent = 'Supprimer';
            del.setAttribute('aria-label', 'Supprimer la planification de ' + (s.label || ''));
            del.style.cssText = tog.style.cssText;
            del.addEventListener('click', async () => {
                try {
                    const r = await fetch('/api/coanimm/schedules/' + encodeURIComponent(s.id), { method: 'DELETE' });
                    const d = await r.json();
                    if (d.schedules) _renderCoanimmSchedules(d.schedules, isOwner);
                    _coanimmAnnounce('Planification supprimée.');
                } catch (e) { /* silencieux */ }
            });
            li.appendChild(tog);
            li.appendChild(del);
        }
        ul.appendChild(li);
    });
}

async function _coanimmSchedPopulateWfPicker() {
    const sel = document.getElementById('coanimm-sched-wf');
    if (!sel) return;
    try {
        const r = await fetch('/api/coanimm/workflows');
        const d = await r.json();
        sel.innerHTML = '<option value="">— Choisir un ricochet —</option>';
        (d.workflows || []).forEach(wf => {
            const opt = document.createElement('option');
            opt.value = wf.id;
            opt.textContent = wf.label || wf.id;
            sel.appendChild(opt);
        });
    } catch (e) { /* silencieux */ }
}

document.getElementById('coanimm-sched-add-btn')?.addEventListener('click', async () => {
    const wfId = document.getElementById('coanimm-sched-wf')?.value || '';
    if (!wfId) { _coanimmAnnounce('Choisis d\'abord un ricochet à planifier.'); return; }
    const jourVal = document.getElementById('coanimm-sched-jour')?.value ?? '';
    const heureVal = document.getElementById('coanimm-sched-heure')?.value || '09:00';
    const [hh, mm] = heureVal.split(':').map(x => parseInt(x, 10));
    try {
        const r = await fetch('/api/coanimm/schedules', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                workflow_id: wfId,
                jour: jourVal === '' ? null : parseInt(jourVal, 10),
                heure: isNaN(hh) ? 9 : hh,
                minute: isNaN(mm) ? 0 : mm,
                parametre: (document.getElementById('coanimm-sched-entree')?.value || '').trim() || null,
            }),
        });
        const d = await r.json();
        if (r.ok && d.schedules) {
            _renderCoanimmSchedules(d.schedules, true);
            _coanimmAnnounce('Ricochet planifié.');
        } else {
            _coanimmAnnounce('Planification refusée : ' + (d.detail || 'erreur.'));
        }
    } catch (e) { _coanimmAnnounce('Erreur réseau lors de la planification.'); }
});

async function loadCoanimmWorkflows() {
    try {
        const r = await fetch('/api/coanimm/workflows');
        const d = await r.json();
        _renderCoanimmWorkflows(d.workflows || []);
        // Peupler le sélecteur de bonds pour la composition
        await _coanimmWfPopulateSkillPicker();
    } catch (e) { console.error('[COANIMM-WF] Erreur chargement workflows :', e); }
}

function _renderCoanimmWorkflows(workflows) {
    const list = document.getElementById('coanimm-workflows-list');
    if (!list) return;
    list.innerHTML = '';
    if (!workflows.length) {
        const li = document.createElement('li');
        li.style.cssText = 'color:var(--text-muted);font-size:0.8rem;margin-bottom:6px;';
        li.textContent = 'Aucun ricochet enregistré.';
        list.appendChild(li);
        return;
    }
    workflows.forEach(wf => {
        const li = document.createElement('li');
        li.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap;';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = wf.label || '(sans titre)';
        nameSpan.style.cssText = 'flex:1;min-width:0;';

        const _wok = parseInt(wf.meta?.runs_ok || 0, 10), _werr = parseInt(wf.meta?.runs_err || 0, 10);
        if (_wok + _werr > 0) {
            const fiabSpan = document.createElement('span');
            fiabSpan.textContent = ` (fiabilité : ${_wok} réussite${_wok > 1 ? 's' : ''}, ${_werr} échec${_werr > 1 ? 's' : ''})`;
            fiabSpan.style.cssText = 'font-size:0.75rem;color:var(--text-muted);';
            nameSpan.appendChild(fiabSpan);
        }
        const caps = (wf.meta?.capacites || []).join(', ');
        if (caps) {
            const capSpan = document.createElement('span');
            capSpan.textContent = `[${caps}]`;
            capSpan.style.cssText = 'font-size:0.75rem;color:var(--text-muted);';
            nameSpan.appendChild(document.createTextNode(' '));
            nameSpan.appendChild(capSpan);
        }

        const runBtn = document.createElement('button');
        runBtn.type = 'button';
        runBtn.textContent = '▶ Lancer';
        runBtn.style.cssText = 'padding:4px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);font-size:0.8rem;cursor:pointer;';
        runBtn.setAttribute('aria-label', `Lancer le workflow ${wf.label}`);
        runBtn.addEventListener('click', () => _runCoanimmWorkflow(wf.id, wf.label));

        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.textContent = '✕';
        delBtn.style.cssText = 'padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--text);font-size:0.8rem;cursor:pointer;';
        delBtn.setAttribute('aria-label', `Supprimer le workflow ${wf.label}`);
        delBtn.addEventListener('click', async () => {
            await fetch(`/api/coanimm/workflows/${wf.id}`, { method: 'DELETE' });
            loadCoanimmWorkflows();
        });

        li.appendChild(nameSpan);
        li.appendChild(runBtn);
        li.appendChild(delBtn);
        list.appendChild(li);
    });
}

async function _runCoanimmWorkflow(wfId, label) {
    const resultDiv = document.getElementById('coanimm-wf-result');
    if (!resultDiv) return;
    resultDiv.style.display = 'block';
    resultDiv.textContent = `Exécution du ricochet « ${label} »…`;
    const wfParam = (document.getElementById('coanimm-wf-input')?.value || '').trim();

    try {
        const r = await fetch(`/api/coanimm/workflows/${wfId}/run_stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id: currentThreadId || null, parametre: wfParam || null }),
        });
        if (!r.ok || !r.body) throw new Error('HTTP ' + r.status);
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        let finalData = null;
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const parts = buf.split('\n\n');
            buf = parts.pop();
            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith('data: ')) continue;
                const payload = line.slice(6);
                if (payload === '[DONE]') continue;
                let evt;
                try { evt = JSON.parse(payload); } catch (_e) { continue; }
                if (evt.type === 'step_start') {
                    resultDiv.textContent = `Étape ${evt.index} sur ${evt.total} : ${evt.label}…`;
                } else if (evt.type === 'step_adapt') {
                    resultDiv.textContent = `Étape ${evt.index} sur ${evt.total} : adaptation du script à l'entrée fournie…`;
                } else if (evt.type === 'step_repair') {
                    resultDiv.textContent = `Étape ${evt.index} sur ${evt.total} : échec, correction automatique…`;
                } else if (evt.type === 'step_critique') {
                    resultDiv.textContent = `Étape ${evt.index} sur ${evt.total} : résultat insuffisant${evt.motif ? ' (' + evt.motif + ')' : ''}, correction…`;
                } else if (evt.type === 'step_done' && evt.status === 'ok') {
                    resultDiv.textContent = `Étape ${evt.index} sur ${evt.total} terminée.`;
                } else if (evt.type === 'done') {
                    finalData = evt;
                    loadCoanimmHistory().catch(() => {});
                }
            }
        }
        const data = finalData || { status: 'error', message: 'Flux interrompu sans résultat final.' };
        let html = `<strong>${data.status === 'ok' ? '✓' : '✗'} ${_escHtml(data.message || '')}</strong>`;
        if (Array.isArray(data.steps) && data.steps.length) {
            html += '<ul style="margin:6px 0 0;padding-left:1.2em;">';
            data.steps.forEach(s => {
                const icon = s.status === 'ok' ? '✓' : '✗';
                html += `<li>${icon} <em>${_escHtml(s.label)}</em>`;
                if (s.error) html += ` — <span style="color:var(--error,#f87171)">${_escHtml(s.error)}</span>`;
                if (s.output) html += `<br><pre style="white-space:pre-wrap;font-size:0.78rem;margin:2px 0 0;">${_escHtml(s.output.slice(0,400))}</pre>`;
                html += '</li>';
            });
            html += '</ul>';
        }
        if (data.files_info) html += `<p style="margin:6px 0 0;font-size:0.82rem;">${_escHtml(data.files_info)}</p>`;
        resultDiv.innerHTML = html;
    } catch (e) {
        resultDiv.textContent = `Erreur réseau lors de l'exécution du ricochet.`;
    }
}

async function _coanimmWfPopulateSkillPicker() {
    const sel = document.getElementById('coanimm-wf-skill-pick');
    if (!sel) return;
    try {
        const r = await fetch('/api/prompts?type=skill');
        const d = await r.json();
        const skills = Object.entries(d.prompts || {});
        // Conserver la première option vide
        sel.innerHTML = '<option value="">— Ajouter un bond —</option>';
        skills.forEach(([id, sk]) => {
            if (!sk.meta?.valide_par_laurent) return; // bonds validés seulement
            const opt = document.createElement('option');
            opt.value = id;
            opt.textContent = sk.label || id;
            sel.appendChild(opt);
        });
    } catch (e) { /* silencieux */ }
}

function _coanimmWfAddStep() {
    const sel = document.getElementById('coanimm-wf-skill-pick');
    if (!sel || !sel.value) return;
    const label = sel.options[sel.selectedIndex]?.text || sel.value;
    _coanimmWfSteps.push({ skill_id: sel.value, label });
    _renderCoanimmWfSteps();
    sel.value = '';
}

function _renderCoanimmWfSteps() {
    const ul = document.getElementById('coanimm-wf-steps');
    if (!ul) return;
    ul.innerHTML = '';
    _coanimmWfSteps.forEach((step, idx) => {
        const li = document.createElement('li');
        li.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:5px;';

        const numSpan = document.createElement('span');
        numSpan.textContent = `${idx + 1}.`;
        numSpan.style.cssText = 'color:var(--text-muted);min-width:1.5em;';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = step.label;
        nameSpan.style.flex = '1';

        const upBtn = document.createElement('button');
        upBtn.type = 'button'; upBtn.textContent = '↑';
        upBtn.setAttribute('aria-label', `Monter l'étape ${step.label}`);
        upBtn.style.cssText = 'padding:2px 6px;border:1px solid var(--border);border-radius:4px;background:var(--bg-input);color:var(--text);cursor:pointer;font-size:0.8rem;';
        upBtn.disabled = idx === 0;
        upBtn.addEventListener('click', () => {
            [_coanimmWfSteps[idx-1], _coanimmWfSteps[idx]] = [_coanimmWfSteps[idx], _coanimmWfSteps[idx-1]];
            _renderCoanimmWfSteps();
        });

        const downBtn = document.createElement('button');
        downBtn.type = 'button'; downBtn.textContent = '↓';
        downBtn.setAttribute('aria-label', `Descendre l'étape ${step.label}`);
        downBtn.style.cssText = 'padding:2px 6px;border:1px solid var(--border);border-radius:4px;background:var(--bg-input);color:var(--text);cursor:pointer;font-size:0.8rem;';
        downBtn.disabled = idx === _coanimmWfSteps.length - 1;
        downBtn.addEventListener('click', () => {
            [_coanimmWfSteps[idx], _coanimmWfSteps[idx+1]] = [_coanimmWfSteps[idx+1], _coanimmWfSteps[idx]];
            _renderCoanimmWfSteps();
        });

        const delBtn = document.createElement('button');
        delBtn.type = 'button'; delBtn.textContent = '✕';
        delBtn.setAttribute('aria-label', `Retirer l'étape ${step.label}`);
        delBtn.style.cssText = 'padding:2px 6px;border:1px solid var(--border);border-radius:4px;background:var(--bg-input);color:var(--text);cursor:pointer;font-size:0.8rem;';
        delBtn.addEventListener('click', () => {
            _coanimmWfSteps.splice(idx, 1);
            _renderCoanimmWfSteps();
        });

        li.append(numSpan, nameSpan, upBtn, downBtn, delBtn);
        ul.appendChild(li);
    });
    if (!_coanimmWfSteps.length) {
        const li = document.createElement('li');
        li.style.cssText = 'color:var(--text-muted);font-size:0.8rem;';
        li.textContent = 'Aucune étape ajoutée.';
        ul.appendChild(li);
    }
}

async function _coanimmWfSave() {
    const nameInput = document.getElementById('coanimm-wf-name');
    const status = document.getElementById('coanimm-wf-save-status');
    const label = nameInput?.value?.trim();
    if (!label) { if (status) status.textContent = 'Donnez un nom au ricochet.'; return; }
    if (!_coanimmWfSteps.length) { if (status) status.textContent = 'Ajoutez au moins un bond.'; return; }
    if (status) status.textContent = 'Enregistrement…';
    try {
        const r = await fetch('/api/coanimm/workflows', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label, etapes: _coanimmWfSteps }),
        });
        const d = await r.json();
        if (d.status === 'created') {
            if (status) status.textContent = 'Ricochet enregistré !';
            _coanimmWfSteps = [];
            _renderCoanimmWfSteps();
            if (nameInput) nameInput.value = '';
            loadCoanimmWorkflows();
        } else {
            if (status) status.textContent = d.message || 'Erreur.';
        }
    } catch (e) {
        if (status) status.textContent = 'Erreur réseau.';
    }
}

function _escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}


document.getElementById('coanimm-path-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); _addCoanimmPath(); }
});
document.getElementById('coanimm-wf-add-step-btn')?.addEventListener('click', _coanimmWfAddStep);
document.getElementById('coanimm-wf-save-btn')?.addEventListener('click', _coanimmWfSave);


async function loadCoanimm() {
    const list = document.getElementById('coanimm-script-list');
    _coanimmHideAll();
    list.textContent = 'Chargement…';

    try {
        const r = await fetch('/api/prompts?type=script');
        const data = await r.json();
        const scripts = Object.entries(data.prompts || {});

        if (scripts.length === 0) {
            list.innerHTML = 'Pas encore de tâches enregistrées. Vous pouvez en créer depuis '
            + '<button type="button" onclick="document.getElementById(\'prompt-library-modal\').classList.remove(\'hidden\')" '
            + 'style="background:none;border:none;color:var(--accent,#6ea8fe);cursor:pointer;padding:0;font-size:inherit;text-decoration:underline;">'
            + 'la Promptothèque</button>.'
            return;
        }

        list.innerHTML = '';
        scripts.forEach(([id, entry]) => {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;';
            const span = document.createElement('span');
            span.textContent = entry.label || '(sans titre)';
            span.style.flex = '1';
            const btn = document.createElement('button');
            btn.textContent = '▶️ Exécuter';
            btn.style.cssText = 'background:var(--bg-input);border:1px solid var(--border);border-radius:6px;padding:6px 12px;color:var(--text);font-size:0.82rem;cursor:pointer;';
            btn.addEventListener('click', () => runCoanimmScript(id, entry.label || id, null));
            row.appendChild(span);
            row.appendChild(btn);
            list.appendChild(row);
        });
    } catch (e) {
        console.error('[COANIMM] Erreur chargement scripts :', e);
        list.textContent = 'Erreur lors du chargement des scripts.';
    }
}

// ── Scripts Promptothèque ──

async function runCoanimmScript(scriptId, label, confirmScope) {
    document.getElementById('coanimm-permission').classList.add('hidden');
    try {
        const r = await fetch('/api/coanimm/run_script', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ script_id: scriptId, thread_id: currentThreadId || null, confirm_scope: confirmScope }),
        });
        const data = await r.json();
        if (data.status === 'permission_required') {
            _coanimmPendingAction = { kind: 'script', scriptId, label };
            _coanimmShowPermission(`le script « ${label} »`);
            return;
        }
        _coanimmShowResult(data, label);
    } catch (e) {
        console.error('[COANIMM] Erreur exécution script :', e);
        _coanimmShowResult({ status: 'error', message: 'Erreur réseau.' }, label);
    }
}

// ── Flux Plan + Code (simultané) → OK → Permission → Exécution ──

async function runCoanimmPlan(consigne) {
    _coanimmCurrentConsigne = consigne;
    _coanimmHideAll();

    const planBox  = document.getElementById('coanimm-plan');
    const planText = document.getElementById('coanimm-plan-text');
    const okBtn    = document.getElementById('coanimm-plan-ok');
    const noBtn    = document.getElementById('coanimm-plan-no');

    planText.textContent = 'Analyse en cours…';
    planBox.classList.remove('hidden');
    okBtn.disabled = true;
    noBtn.disabled = true;

    try {
        const r = await fetch('/api/coanimm/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ consigne, thread_id: currentThreadId || null,
                                   override_provider: _coanimmOverrideProvider || null,
                                   selected_bond_id: _coanimmSelectedBond?.id || null }),
        });
        const data = await r.json();

        if (data.status === 'error') {
            planText.textContent = 'Erreur lors de la planification : ' + data.message;
            noBtn.disabled = false;
            return;
        }

        planText.textContent = data.plan || '(aucun plan retourn\xe9)';
        // OK réactivé par _coanimmStartCodeGen quand le code est prêt
        noBtn.disabled = false;
        okBtn.dataset.needsExplore = data.needs_explore ? '1' : '';

        if (data.needs_explore) {
            // Le code sera généré APRÈS l'exploration du disque, pour coller
            // exactement à ce qui est trouvé (plus de code pré-généré puis jeté).
            const _ce = document.getElementById('coanimm-code-edit');
            const _cp = document.getElementById('coanimm-code-preview');
            if (_ce) _ce.value = "# Le code sera généré après l'exploration du disque.";
            if (_cp) _cp.classList.remove('hidden');
            okBtn.disabled = false;
            setTimeout(() => okBtn.focus(), 50);
            return;
        }

        // G\xe9n\xe9rer le code en parall\xe8le — affich\xe9 repli\xe9 sous le plan
        _coanimmStartCodeGen(consigne, '');

    } catch (e) {
        console.error('[COANIMM] Erreur planification :', e);
        planText.textContent = 'Erreur r\xe9seau lors de la planification.';
        noBtn.disabled = false;
    }
}

// G\xe9n\xe8re le code en arri\xe8re-plan et l’affiche repli\xe9 sous le plan
async function _coanimmStartCodeGen(consigne, exploreStdout) {
    const codeEdit = document.getElementById('coanimm-code-edit');
    const preview  = document.getElementById('coanimm-code-preview');
    const codeArea = document.getElementById('coanimm-code-area');

    // Montrer le bloc code repli\xe9 avec message provisoire
    codeEdit.value = '# G\xe9n\xe9ration en cours…';
    codeArea.classList.add('hidden');
    document.getElementById('coanimm-code-toggle').textContent = 'Afficher le code';
    document.getElementById('coanimm-code-toggle').setAttribute('aria-expanded', 'false');
    preview.classList.remove('hidden');

    try {
        const r = await fetch('/api/coanimm/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                consigne,
                thread_id: currentThreadId || null,
                explore_stdout: exploreStdout || null,
                override_provider: _coanimmOverrideProvider || null,
                selected_bond_id: _coanimmSelectedBond?.id || null,
            }),
        });
        // Parse sécurisé : si le serveur renvoie du HTML (erreur 500), on affiche le début
        let data;
        try { data = await r.json(); }
        catch (_je) {
            const raw = await r.text().catch(() => '(réponse illisible)');
            throw new Error(`HTTP ${r.status} — réponse non-JSON : ${raw.slice(0, 300)}`);
        }
        codeEdit.value = (data.status === 'ok') ? (data.code || '') : ('# Erreur génération : ' + (data.message || 'inconnue') + (data.detail ? '\n\n' + data.detail : ''));
        if (data.status !== 'ok') {
            const _pt = document.getElementById('coanimm-plan-text');
            if (_pt) _pt.textContent += '\n\n🔴 Échec : ' + (data.message || 'erreur inconnue');
            _coanimmAnnounce('Échec de la génération : ' + (data.message || 'erreur inconnue'));
        }
        _coanimmShowRisks(data.risks || []);
    } catch (e) {
        const errMsg = e?.message || String(e);
        console.error('[COANIMM] Erreur génération code:', errMsg);
        codeEdit.value = '# Erreur lors de la génération : ' + errMsg;
        const _pt = document.getElementById('coanimm-plan-text');
        if (_pt) _pt.textContent += '\n\n🔴 Échec de la génération du code : ' + errMsg;
        _coanimmAnnounce('Échec de la génération du code. ' + errMsg);
    } finally {
        // Réactiver le bouton OK maintenant que le code est prêt (ou en erreur)
        const _okBtn = document.getElementById('coanimm-plan-ok');
        if (_okBtn) {
            const _codeVal = codeEdit.value || '';
            const _codeOk = _codeVal.trim() && !_codeVal.startsWith('# Erreur') && !_codeVal.startsWith('# Génération');
            _okBtn.disabled = !_codeOk;
            if (_codeOk) setTimeout(() => _okBtn.focus(), 50);
        }
    }
}

// ── Exploration lecture seule (si plan le requiert) ──

function _coanimmShowRisks(risks) {
    let box = document.getElementById('coanimm-risks-box');
    if (!box) {
        box = document.createElement('div');
        box.id = 'coanimm-risks-box';
        box.setAttribute('role', 'alert');
        box.style.cssText = 'margin-top:8px;font-size:0.82rem;';
        const preview = document.getElementById('coanimm-code-preview');
        if (preview) preview.appendChild(box);
    }
    box.innerHTML = '';
    if (!risks || risks.length === 0) return;
    const title = document.createElement('p');
    title.style.cssText = 'font-weight:600;margin:0 0 4px;';
    title.textContent = '⚠️ ATTENTION — ce script :';
    box.appendChild(title);
    risks.forEach(r => {
        const p = document.createElement('p');
        const isDanger = r.level === 'danger';
        p.style.cssText = 'margin:2px 0;padding:3px 8px;border-radius:4px;'
            + (isDanger
               ? 'background:rgba(220,50,50,0.12);border-left:3px solid #dc3232;'
               : 'background:rgba(200,140,0,0.12);border-left:3px solid #c88c00;');
        p.textContent = (isDanger ? '🔴 ' : '⚠️ ') + r.message;
        box.appendChild(p);
    });
}

async function runCoanimmExplore(consigne, confirmScope) {
    _coanimmCurrentConsigne = consigne;
    document.getElementById('coanimm-permission').classList.add('hidden');
    _coanimmSetBusy(true);
    const planText  = document.getElementById('coanimm-plan-text');
    const exploreBox = document.getElementById('coanimm-explore-result');
    const exploreOut = document.getElementById('coanimm-explore-stdout');

    planText.textContent = (planText.textContent || '') + '\n\n🐸 CoaNIMM explore votre disque…';
    _coanimmAnnounce('CoaNIMM explore votre disque, veuillez patienter.');
    // Montrer le résultat d'exploration avec un message de chargement
    exploreBox.classList.remove('hidden');
    exploreOut.value = 'Exploration en cours, veuillez patienter…';

    try {
        const r = await fetch('/api/coanimm/explore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ consigne, thread_id: currentThreadId || null, confirm_scope: confirmScope }),
        });
        const data = await r.json();

        if (data.status === 'permission_required') {
            _coanimmPendingAction = { kind: 'explore', consigne };
            _coanimmShowPermission('explorer le disque en lecture seule');
            return;
        }
        if (data.status === 'error') {
            exploreOut.value = 'Erreur : ' + data.message;
            exploreBox.classList.remove('hidden');
            return;
        }
        exploreOut.value = data.stdout || '(aucune sortie)';
        exploreBox.classList.remove('hidden');

        // R\xe9-g\xe9n\xe9rer le code avec le contexte d’exploration, puis ex\xe9cuter
        planText.textContent += '\n\n[G\xe9n\xe9ration du code avec contexte d’exploration…]';
        await _coanimmStartCodeGen(consigne, data.stdout || '');
        const code = document.getElementById('coanimm-code-edit')?.value || '';
        // Réutiliser le même scope pour éviter une 2e demande d'autorisation
        runCoanimmExecuteCode(code, confirmScope || 'once');

    } catch (e) {
        _coanimmSetBusy(false);
        console.error('[COANIMM] Erreur exploration :', e);
        exploreOut.value = 'Erreur r\xe9seau lors de l’exploration.';
        exploreBox.classList.remove('hidden');
    }
}

// ── Ex\xe9cution du code (avec permission) ──

// ── Aperçu avant exécution (optionnel, opt-in) ──
(function _coanimmWirePreviewToggle(){
    const t = document.getElementById('coanimm-preview-toggle');
    if (!t) return;
    try { t.checked = localStorage.getItem('coanimm_preview') === '1'; } catch (e) {}
    t.addEventListener('change', () => { try { localStorage.setItem('coanimm_preview', t.checked ? '1' : '0'); } catch (e) {} });
})();

// ── Réglages serveur simples : case à cocher ↔ route GET/POST {active} ──
function _wireToggleReglage(idCase, route, msgOn, msgOff) {
    const t = document.getElementById(idCase);
    if (!t) return;
    fetch(route).then(r => r.json()).then(d => { t.checked = d.active !== false; }).catch(() => {});
    t.addEventListener('change', async () => {
        try {
            await fetch(route, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active: t.checked }),
            });
            _coanimmAnnounce(t.checked ? msgOn : msgOff);
        } catch (e) { /* silencieux */ }
    });
}
_wireToggleReglage('coanimm-thinking-toggle', '/api/settings/coanimm-thinking',
    'Réflexion avant écriture activée.',
    'Réflexion avant écriture désactivée : scripts générés plus vite, corrections moins fines.');
_wireToggleReglage('anthropic-cache-toggle', '/api/settings/anthropic-cache',
    'Mise en cache des prompts activée.',
    'Mise en cache des prompts désactivée : les messages longs coûteront plus cher.');
// Ses modèles récents réfléchissent d'office : invisible, mais plusieurs secondes
// de silence avant que la synthèse vocale ne démarre, et un budget de réponse
// amputé (d'où les titres de fils vides). Coupée par défaut, mais réglable.
_wireToggleReglage('deepseek-reflexion-toggle', '/api/settings/deepseek-reflexion',
    'Réflexion DeepSeek gardée : réponses plus fines sur les questions complexes, mais plusieurs secondes avant le premier mot.',
    'Réflexion DeepSeek coupée : réponse immédiate.');

// ── Vérification du résultat (critique) : réglage serveur, actif par défaut ──
(function _coanimmWireCritiqueToggle(){
    const t = document.getElementById('coanimm-critique-toggle');
    if (!t) return;
    fetch('/api/settings/coanimm-critique').then(r => r.json())
        .then(d => { t.checked = d.active !== false; }).catch(() => {});
    t.addEventListener('change', async () => {
        try {
            await fetch('/api/settings/coanimm-critique', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active: t.checked }),
            });
            _coanimmAnnounce(t.checked
                ? 'Vérification du résultat activée.'
                : 'Vérification du résultat désactivée : plus d\'appel IA supplémentaire après les exécutions.');
        } catch (e) { /* silencieux */ }
    });
})();

function _coanimmShowPreview(code, confirmScope) {
    const panel = document.getElementById('coanimm-preview-panel');
    const body  = document.getElementById('coanimm-preview-body');
    const title = document.getElementById('coanimm-preview-title');
    if (!panel || !body) { runCoanimmExecuteCode(code, confirmScope, 0, false, null, true); return; }
    body.innerHTML = '<p style="margin:0;">Analyse en cours…</p>';
    panel.classList.remove('hidden');
    fetch('/api/coanimm/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, thread_id: currentThreadId || null }),
    }).then(r => r.json()).then(data => {
        const caps = data.capabilities || [];
        let html = '', speak = '';
        if (data.blocked && data.blocked.length) {
            html += '<p style="color:#c0392b;margin:0 0 6px;">Cette tâche sera refusée pour raison de sécurité : ' + _escHtml(data.blocked.join(' ; ')) + '.</p>';
            speak += 'Attention, cette tâche sera refusée pour raison de sécurité. ';
        }
        if (caps.length) {
            const labels = caps.map(c => c.label).join(', ');
            html += '<p style="margin:0 0 6px;">Cette tâche va : ' + _escHtml(labels) + '.</p>';
            speak += 'Cette tâche va : ' + labels + '. ';
        } else {
            html += '<p style="margin:0 0 6px;">Aucune action sensible détectée.</p>';
            speak += 'Aucune action sensible détectée. ';
        }
        if (data.allowed_paths && data.allowed_paths.length) {
            html += '<p style="margin:0 0 6px;">Écriture limitée aux dossiers autorisés : ' + _escHtml(data.allowed_paths.join(', ')) + '.</p>';
            speak += 'Écriture limitée aux dossiers autorisés : ' + data.allowed_paths.join(', ') + '. ';
        }
        if (data.needs_confirmation && data.needs_confirmation.length) {
            html += '<p style="margin:0;">Action sensible : une confirmation supplémentaire pourra être demandée après « Exécuter ».</p>';
            speak += 'Une confirmation supplémentaire pourra être demandée. ';
        }
        body.innerHTML = html;
        _coanimmAnnounce('Aperçu. ' + speak);
    }).catch(() => { body.innerHTML = '<p style="margin:0;">Aperçu indisponible. Vous pouvez exécuter ou annuler.</p>'; });
    const yes = document.getElementById('coanimm-preview-yes');
    const no  = document.getElementById('coanimm-preview-no');
    if (yes) { const fy = yes.cloneNode(true); yes.replaceWith(fy); fy.addEventListener('click', () => { panel.classList.add('hidden'); runCoanimmExecuteCode(code, confirmScope || 'once', 0, false, null, true); }); }
    if (no)  { const fn = no.cloneNode(true);  no.replaceWith(fn);  fn.addEventListener('click', () => { panel.classList.add('hidden'); _coanimmAnnounce('Exécution annulée.'); }); }
    setTimeout(() => { if (title) title.focus(); }, 60);
}

// ── Critique du résultat (boucle agentique) : après un run réussi, vérifie que le
// résultat répond à la consigne ; si insuffisant, corrige et relance (borné par
// COANIMM_MAX_REPAIR). Renvoie true si une relance a été lancée (l'appelant s'arrête).
async function _coanimmCritiqueAndRetry(code, stdoutText, filesList, repairAttempt, confirmScope) {
    if (!_coanimmCurrentConsigne || !_coanimmCurrentConsigne.trim()) return false; // exécution directe : pas de critique
    const statusEl = document.getElementById('coanimm-result-status');
    try {
        const r = await fetch('/api/coanimm/critique', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                consigne: _coanimmCurrentConsigne,
                code,
                stdout: (stdoutText || '').slice(-4000),
                returncode: 0,
                files: (filesList || []).map(f => (f.filename || '') + ' (' + (f.size || 0) + ' octets)'),
                thread_id: currentThreadId || null,
                override_provider: _coanimmOverrideProvider || null,
            }),
        });
        const d = await r.json();
        if (!d || d.verdict !== 'insuffisant') return false;
        const motif = d.motif || 'le résultat semble incomplet par rapport à la consigne';
        if (repairAttempt >= COANIMM_MAX_REPAIR) {
            _coanimmAnnounce('Vérification du résultat : ' + motif + '. Limite de corrections automatiques atteinte, résultat conservé tel quel.');
            return false;
        }
        if (statusEl) statusEl.textContent = '🐸 Résultat jugé insuffisant — correction (' + (repairAttempt + 1) + '/' + COANIMM_MAX_REPAIR + ')…';
        _coanimmAnnounce('Vérification du résultat : ' + motif + '. Correction automatique en cours, tentative ' + (repairAttempt + 1) + ' sur ' + COANIMM_MAX_REPAIR + '.');
        const rr = await fetch('/api/coanimm/repair', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code,
                error_output: "Le script s'est exécuté sans erreur (code retour 0) mais le résultat ne répond pas à la consigne : " + motif + (d.conseil ? ' Conseil : ' + d.conseil : ''),
                consigne: _coanimmCurrentConsigne,
                thread_id: currentThreadId || null,
                override_provider: _coanimmOverrideProvider || null,
            }),
        });
        const dr = await rr.json();
        if (dr.status === 'ok' && dr.code && dr.code.trim()) {
            const ce = document.getElementById('coanimm-result-code');
            if (ce) { ce.value = dr.code; document.getElementById('coanimm-result-code-box')?.classList.remove('hidden'); }
            await runCoanimmExecuteCode(dr.code, confirmScope || 'once', repairAttempt + 1);
            return true;
        }
    } catch (e) { console.error('[COANIMM] Critique du résultat ignorée :', e); }
    return false;
}

async function runCoanimmExecuteCode(code, confirmScope, repairAttempt = 0, allowRisky = false, onceCaps = null, skipPreview = false) {
    document.getElementById('coanimm-permission').classList.add('hidden');
    if (!skipPreview && repairAttempt === 0) {
        const pv = document.getElementById('coanimm-preview-toggle');
        if (pv && pv.checked) { _coanimmShowPreview(code, confirmScope); return; }
    }

    const resultBox = document.getElementById('coanimm-result');
    const statusEl  = document.getElementById('coanimm-result-status');
    const stdoutEl  = document.getElementById('coanimm-result-stdout');
    statusEl.textContent = '🐸 CoaNIMM exécute…';
    stdoutEl.value = '';
    document.getElementById('coanimm-result-stderr-block')?.classList.add('hidden');
    document.getElementById('coanimm-result-files')?.classList.add('hidden');
    document.getElementById('coanimm-save-panel')?.classList.add('hidden');
    resultBox.classList.remove('hidden');
    _coanimmAnnounce('CoaNIMM exécute le script, veuillez patienter.');
    _coanimmSetBusy(true);

    try {
        _coanimmCancelled = false;
        { const _sb = document.getElementById('coanimm-stop-btn'); if (_sb) _sb.classList.remove('hidden'); }
        const r = await fetch('/api/coanimm/run_code_stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, thread_id: currentThreadId || null, confirm_scope: confirmScope, allow_risky: allowRisky, once_caps: onceCaps }),
        });

        // Si permission requise : réponse JSON simple
        const ct = r.headers.get('content-type') || '';
        if (!ct.includes('event-stream')) {
            const data = await r.json();
            if (data.status === 'confirmation_required') {
                document.getElementById('coanimm-stop-btn')?.classList.add('hidden');
                _coanimmSetBusy(false);
                const panel = document.getElementById('coanimm-confirm-panel');
                const txt = document.getElementById('coanimm-confirm-text');
                if (txt) txt.textContent = '⚠️ ' + (data.message || 'Ce script demande une action sensible.');
                if (panel) panel.classList.remove('hidden');
                const rememberRow = document.getElementById('coanimm-confirm-remember-row');
                if (rememberRow) rememberRow.style.display = _coanimmIsOwner ? 'flex' : 'none';
                _coanimmAnnounce(data.message || 'Confirmation requise avant exécution.');
                const yes = document.getElementById('coanimm-confirm-yes');
                const no = document.getElementById('coanimm-confirm-no');
                const freshYes = yes.cloneNode(true); yes.replaceWith(freshYes);
                const freshNo = no.cloneNode(true); no.replaceWith(freshNo);
                freshYes.addEventListener('click', async () => {
                    panel.classList.add('hidden');
                    const caps = Array.isArray(data.missing_capabilities) ? data.missing_capabilities : [];
                    const remember = document.getElementById('coanimm-confirm-remember');
                    if (remember && remember.checked && _coanimmIsOwner && caps.length) {
                        // Mémoriser durablement chaque capacité avant de relancer.
                        try {
                            await Promise.all(caps.map(c => fetch('/api/coanimm/capabilities', {
                                method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ capability: c }),
                            })));
                            if (typeof loadCoanimmCapabilities === 'function') loadCoanimmCapabilities();
                            _coanimmAnnounce('Autorisation mémorisée. Exécution en cours.');
                        } catch (e) { /* on relance quand même */ }
                        remember.checked = false;
                        runCoanimmExecuteCode(code, confirmScope || 'once', 0, false, caps);
                    } else {
                        // « Pour cette fois » : on n'ouvre QUE les capacités requises, sans persister.
                        runCoanimmExecuteCode(code, confirmScope || 'once', 0, false, caps.length ? caps : null);
                    }
                });
                freshNo.addEventListener('click', () => {
                    panel.classList.add('hidden');
                    const st = document.getElementById('coanimm-result-status');
                    if (st) st.textContent = 'Exécution annulée.';
                    _coanimmAnnounce('Exécution annulée.');
                });
                setTimeout(() => { const t = document.getElementById('coanimm-confirm-text'); if (t) t.focus(); }, 60);
                return;
            }
            if (data.status === 'permission_required') {
                document.getElementById('coanimm-stop-btn')?.classList.add('hidden');
                _coanimmPendingAction = { kind: 'run_code', code };
                _coanimmShowPermission('exécuter le code Python');
                return;
            }
            statusEl.textContent = '🔴 Erreur : ' + (data.message || 'inconnue');
            _coanimmAnnounce('Erreur : ' + (data.message || 'inconnue'));
            return;
        }

        // Lire le flux SSE
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        let firstLine = true;

        statusEl.textContent = '🐸 CoaNIMM travaille… (sortie en direct)';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const parts = buf.split('\n');
            buf = parts.pop();
            for (const part of parts) {
                if (!part.startsWith('data: ')) continue;
                let evt;
                try { evt = JSON.parse(part.slice(6)); } catch { continue; }

                if (evt.type === 'line') {
                    stdoutEl.value += evt.text + '\n';
                    stdoutEl.scrollTop = stdoutEl.scrollHeight;
                    if (firstLine) {
                        _coanimmAnnounce('Première sortie : ' + evt.text.slice(0, 150));
                        firstLine = false;
                    }
                } else if (evt.type === 'done') {
                    const rc = evt.returncode;
                    if (evt.files_list && evt.files_list.length) _coanimmShowFiles(evt.files_list);
                    if (evt.interaction_needed) {
                        // Le script demande une réponse de l'utilisateur
                        const iq = evt.interaction_needed;
                        const panel = document.getElementById('coanimm-interact-panel');
                        const questionEl = document.getElementById('coanimm-interact-question');
                        const inputEl = document.getElementById('coanimm-interact-input');
                        questionEl.textContent = '🐸 ' + iq.question;
                        inputEl.value = '';
                        panel.removeAttribute('hidden');
                        panel.scrollIntoView({ behavior: 'smooth' });
                        inputEl.focus();
                        statusEl.textContent = '🐸 CoaNIMM attend votre réponse…';
                        _coanimmAnnounce('CoaNIMM pose une question : ' + iq.question);
                        _coanimmSetBusy(false);
                        // Handler submit (Entrée ou bouton)
                        const onSubmit = async () => {
                            const rep = inputEl.value.trim();
                            if (!rep) return;
                            panel.setAttribute('hidden', '');
                            _coanimmSetBusy(true);
                            statusEl.textContent = '🐸 Génération de la suite…';
                            _coanimmAnnounce('Génération de la suite en cours.');
                            try {
                                const r2 = await fetch('/api/coanimm/continue', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        thread_id: currentThreadId || null,
                                        consigne_originale: _coanimmCurrentConsigne,
                                        output_precedent: iq.output_so_far || '',
                                        question_posee: iq.question,
                                        reponse_utilisateur: rep,
                                    }),
                                });
                                const d2 = await r2.json();
                                if (d2.status !== 'ok') {
                                    statusEl.textContent = '🔴 Erreur : ' + (d2.message || 'inconnue');
                                    _coanimmAnnounce('Erreur : ' + (d2.message || 'inconnue'));
                                    _coanimmSetBusy(false);
                                    return;
                                }
                                const codeEl = document.getElementById('coanimm-result-code');
                                if (codeEl) {
                                    codeEl.value = d2.code;
                                    document.getElementById('coanimm-result-code-box')?.classList.remove('hidden');
                                }
                                stdoutEl.value = '';
                                await runCoanimmExecuteCode(d2.code, 'once');
                            } catch(e2) {
                                statusEl.textContent = '🔴 Erreur réseau.';
                                _coanimmAnnounce('Erreur réseau.');
                                _coanimmSetBusy(false);
                            }
                        };
                        // Remplacer le bouton pour retirer les anciens listeners
                        const btn = document.getElementById('coanimm-interact-submit');
                        const freshBtn = btn.cloneNode(true);
                        btn.replaceWith(freshBtn);
                        freshBtn.addEventListener('click', onSubmit);
                        document.getElementById('coanimm-interact-input').addEventListener('keydown', (e) => {
                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSubmit(); }
                        });
                    } else {
                        // Fin normale sans interaction
                        if (_coanimmCancelled) {
                            statusEl.textContent = '⏹ Script arrêté.';
                            _coanimmAnnounce('Script arrêté.');
                            document.getElementById('coanimm-stop-btn')?.classList.add('hidden');
                            _coanimmSetBusy(false);
                            return;
                        }
                        if (rc !== 0 && repairAttempt < COANIMM_MAX_REPAIR) {
                            const _errOut = stdoutEl.value;
                            statusEl.textContent = '🐸 Échec — CoaNIMM corrige et réessaie (' + (repairAttempt + 1) + '/' + COANIMM_MAX_REPAIR + ')…';
                            _coanimmAnnounce('Le script a échoué. Correction automatique, tentative ' + (repairAttempt + 1) + ' sur ' + COANIMM_MAX_REPAIR + '.');
                            try {
                                const _rr = await fetch('/api/coanimm/repair', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        code,
                                        error_output: _errOut,
                                        consigne: _coanimmCurrentConsigne || '',
                                        thread_id: currentThreadId || null,
                                        override_provider: _coanimmOverrideProvider || null,
                                    }),
                                });
                                const _dr = await _rr.json();
                                if (_dr.status === 'ok' && _dr.code && _dr.code.trim()) {
                                    const _ce = document.getElementById('coanimm-result-code');
                                    if (_ce) { _ce.value = _dr.code; document.getElementById('coanimm-result-code-box')?.classList.remove('hidden'); }
                                    stdoutEl.value = '';
                                    await runCoanimmExecuteCode(_dr.code, confirmScope || 'once', repairAttempt + 1);
                                    return;
                                }
                            } catch (_er) { console.error('[COANIMM] Erreur réparation :', _er); }
                        }
                        statusEl.textContent = rc === 0
                            ? '✅ Terminé (code ' + rc + ')'
                            : '⚠️ Terminé avec erreurs (code ' + rc + ')';
                        _recordCoanimmHistory(rc === 0 ? 'ok' : 'error', rc, (evt.files_list || []).length);
                        if (rc !== 0) {
                            const lines = stdoutEl.value.trim().split('\n').filter(Boolean);
                            const lastLines = lines.slice(-5).join(' ');
                            // Annonce assertive pour ne pas rater l'erreur
                            const ann = document.getElementById('coanimm-status-announce');
                            if (ann) { ann.setAttribute('aria-live','assertive'); ann.textContent = ''; }
                            setTimeout(() => {
                                if (ann) ann.textContent = evt.summary || ('Terminé avec erreurs. ' + lastLines.slice(0, 400));
                                stdoutEl.focus();
                            }, 100);
                            setTimeout(() => { if (ann) ann.setAttribute('aria-live','polite'); }, 3000);
                        } else {
                            _coanimmAnnounce(evt.summary || 'Terminé avec succès.');
                            const _critiqueRelance = await _coanimmCritiqueAndRetry(code, stdoutEl.value, evt.files_list || [], repairAttempt, confirmScope);
                            if (_critiqueRelance) return;
                        }
                        _coanimmMaybeShowSavePanel(code, rc === 0);
                        _coanimmSetBusy(false);
                    }
                } else if (evt.type === 'error') {
                    statusEl.textContent = '🔴 Erreur : ' + evt.message;
                    _coanimmAnnounce('Erreur : ' + evt.message);
                    _coanimmSetBusy(false);
                }
            }
        }
    } catch (e) {
        console.error('[COANIMM] Erreur exécution :', e);
        statusEl.textContent = '🔴 Erreur réseau.';
        _coanimmAnnounce('Erreur réseau lors de l’exécution.');
        _coanimmSetBusy(false);
    }
}
// ── Reprise apr\xe8s permission ──

function _coanimmResumePending(confirmScope) {
    if (!_coanimmPendingAction) return;
    const action = _coanimmPendingAction;
    _coanimmPendingAction = null;
    document.getElementById('coanimm-permission').classList.add('hidden');
    if (action.kind === 'run_code') {
        runCoanimmExecuteCode(action.code, confirmScope);
    } else if (action.kind === 'explore') {
        runCoanimmExplore(action.consigne, confirmScope);
    } else {
        runCoanimmScript(action.scriptId, action.label, confirmScope);
    }
}

document.getElementById('coanimm-allow-once')?.addEventListener('click',    () => _coanimmResumePending('once'));
document.getElementById('coanimm-allow-project')?.addEventListener('click', () => _coanimmResumePending('project'));
document.getElementById('coanimm-allow-always')?.addEventListener('click',  () => _coanimmResumePending('always'));
document.getElementById('coanimm-deny')?.addEventListener('click', () => {
    _coanimmPendingAction = null;
    document.getElementById('coanimm-permission').classList.add('hidden');
});

// ── Toggle affichage du code ──

document.getElementById('coanimm-code-toggle')?.addEventListener('click', () => {
    const area  = document.getElementById('coanimm-code-area');
    const btn   = document.getElementById('coanimm-code-toggle');
    const shown = !area.classList.contains('hidden');
    area.classList.toggle('hidden', shown);
    btn.textContent = shown ? 'Afficher le code' : 'Masquer le code';
    btn.setAttribute('aria-expanded', shown ? 'false' : 'true');
    if (!shown) setTimeout(() => document.getElementById('coanimm-code-edit')?.focus(), 50);
});

// ── Bouton plan OK : ex\xe9cuter le code tel quel (\xe9ventuellement modifi\xe9) ──

document.getElementById('coanimm-plan-ok')?.addEventListener('click', () => {
    const consigne = _coanimmCurrentConsigne;
    if (!consigne) return;
    if (document.getElementById('coanimm-plan-ok').dataset.needsExplore === '1') {
        // Exploration requise : le code est généré et exécuté après l'exploration.
        document.getElementById('coanimm-plan-ok').disabled = true;
        document.getElementById('coanimm-plan-no').disabled = true;
        runCoanimmExplore(consigne, null);
        return;
    }
    const codeEdit = document.getElementById('coanimm-code-edit');
    const code = codeEdit?.value || '';
    if (!code.trim() || code.startsWith('# G\xe9n\xe9ration en cours')) {
        document.getElementById('coanimm-plan-text').textContent +=
            '\n[Patientez, le code est encore en cours de génération…]';
        return;
    }
    if (code.startsWith('# Erreur')) {
        document.getElementById('coanimm-plan-text').textContent +=
            '\n🔴 La génération du code a échoué. Essayez de changer de crapauduc ou de reformuler.';
        _coanimmAnnounce('La génération du code a échoué.');
        return;
    }
    document.getElementById('coanimm-plan-ok').disabled = true;
    document.getElementById('coanimm-plan-no').disabled = true;
    const needsExplore = document.getElementById('coanimm-plan-ok').dataset.needsExplore === '1';
    if (needsExplore) {
        runCoanimmExplore(consigne, null);
    } else {
        runCoanimmExecuteCode(code, null);
    }
});

document.getElementById('coanimm-plan-no')?.addEventListener('click', () => {
    _coanimmOverrideProvider = null;
    _coanimmHideAll();
    document.getElementById('coanimm-consigne')?.focus();
});

// ── Bouton Générer ──


// Crapauduc : changer de LLM et relancer le plan
document.getElementById('coanimm-crapauduc-btn')?.addEventListener('click', () => {
    const panel = document.getElementById('coanimm-crapauduc-panel');
    const btn   = document.getElementById('coanimm-crapauduc-btn');
    if (!panel) return;
    const open = panel.hasAttribute('hidden');
    if (open) { panel.removeAttribute('hidden'); btn.setAttribute('aria-expanded','true'); }
    else      { panel.setAttribute('hidden',''); btn.setAttribute('aria-expanded','false'); }
    if (open) setTimeout(() => document.getElementById('coanimm-crapauduc-select')?.focus(), 50);
});

document.getElementById('coanimm-crapauduc-select')?.addEventListener('change', (e) => {
    const val = e.target.value;
    if (!val) return;
    _coanimmOverrideProvider = val;
    // Masquer le panel et relancer avec le nouveau provider
    const panel = document.getElementById('coanimm-crapauduc-panel');
    if (panel) panel.setAttribute('hidden','');
    const btn = document.getElementById('coanimm-crapauduc-btn');
    if (btn) btn.setAttribute('aria-expanded','false');
    e.target.value = '';
    if (_coanimmCurrentConsigne) runCoanimmPlan(_coanimmCurrentConsigne);
});

document.getElementById('coanimm-stop-btn')?.addEventListener('click', async () => {
    _coanimmCancelled = true;
    document.getElementById('coanimm-stop-btn')?.classList.add('hidden');
    _coanimmAnnounce('Arrêt du script demandé.');
    const _st = document.getElementById('coanimm-result-status');
    if (_st) _st.textContent = '⏹ Arrêt en cours…';
    try {
        await fetch('/api/coanimm/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id: currentThreadId || null }),
        });
    } catch (e) { console.error('[COANIMM] Erreur annulation :', e); }
});

document.getElementById('coanimm-test-stream-btn')?.addEventListener('click', async () => {
    const resultBox = document.getElementById('coanimm-result');
    const statusEl  = document.getElementById('coanimm-result-status');
    const stdoutEl  = document.getElementById('coanimm-result-stdout');
    resultBox.classList.remove('hidden');
    stdoutEl.value = '';
    statusEl.textContent = 'Test streaming en cours...';
    _coanimmAnnounce('Début du test de streaming.');
    try {
        const r = await fetch('/api/coanimm/test_stream');
        const ct = r.headers.get('content-type') || '';
        if (!ct.includes('event-stream')) {
            statusEl.textContent = 'ERREUR : le serveur ne renvoie pas de flux SSE (content-type: ' + ct + ')';
            _coanimmAnnounce('Erreur : pas de flux SSE reçu.');
            return;
        }
        _coanimmAnnounce('Flux SSE reçu, lecture en cours.');
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const parts = buf.split('\n');
            buf = parts.pop();
            for (const part of parts) {
                if (!part.startsWith('data: ')) continue;
                let evt;
                try { evt = JSON.parse(part.slice(6)); } catch { continue; }
                if (evt.type === 'line') {
                    stdoutEl.value += evt.text + '\n';
                } else if (evt.type === 'done') {
                    statusEl.textContent = 'Test OK : le streaming fonctionne !';
                    _coanimmAnnounce('Test OK : le streaming fonctionne correctement.');
                }
            }
        }
    } catch(e) {
        statusEl.textContent = 'ERREUR réseau : ' + e.message;
        _coanimmAnnounce('Erreur réseau lors du test.');
    }
});

// Pont contexte optionnel : joint le contexte du fil courant à la demande si la case est cochée.
async function _coanimmBuildContext() {
    const cb = document.getElementById('coanimm-use-context');
    if (!cb || !cb.checked || !currentThreadId) return '';
    try {
        const r = await fetch('/api/threads/' + currentThreadId + '/messages');
        const msgs = await r.json();
        if (!Array.isArray(msgs) || !msgs.length) return '';
        const recent = msgs.slice(-8).map(function (m) {
            return (m.role === 'user' ? 'Utilisateur' : 'Assistant') + ' : ' + (m.content || '').slice(0, 500);
        }).join('\n');
        return '[Contexte de la conversation en cours]\n' + recent;
    } catch (e) { return ''; }
}
document.getElementById('coanimm-generate-btn')?.addEventListener('click', async () => {
    const input = document.getElementById('coanimm-consigne');
    const consigne = (input?.value || '').trim();
    if (!consigne) { input?.focus(); return; }
    const btn = document.getElementById('coanimm-generate-btn');
    if (btn) { btn.disabled = true; btn.textContent = '🐸 Réflexion…'; }
    _coanimmAnnounce('CoaNIMM réfléchit, veuillez patienter.');
    const _ctx = await _coanimmBuildContext();
    runCoanimmPlan(_ctx ? _ctx + '\n\n' + consigne : consigne).finally(() => {
        if (btn) { btn.disabled = false; btn.textContent = 'Coa !'; }
    });
});

document.getElementById('coanimm-consigne')?.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        document.getElementById('coanimm-generate-btn')?.click();
    }
});


// ══════════════════════════════════════════
// ══════════════════════════
// SAUVEGARDE SCRIPT COANIMM
// ══════════════════════════

document.getElementById('coanimm-save-confirm')?.addEventListener('click', async () => {
    const labelVal = (document.getElementById('coanimm-save-label')?.value || '').trim();
    const feedback = document.getElementById('coanimm-save-feedback');
    if (!labelVal) {
        if (feedback) feedback.textContent = 'Veuillez saisir un nom pour le script.';
        document.getElementById('coanimm-save-label')?.focus();
        return;
    }
    const code = document.getElementById('coanimm-code-edit')?.value || '';
    if (!code.trim()) {
        if (feedback) feedback.textContent = 'Aucun code à enregistrer.';
        return;
    }
    try {
        const r = await fetch('/api/prompts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label: labelVal, text: code, type: 'script' }),
        });
        const d = await r.json();
        if (d.status === 'ok') {
            const st = document.getElementById('coanimm-result-status');
            let suffix = ' — script enregistré dans la Promptothèque.';
            const wantSkill = document.getElementById('coanimm-save-skill-check')?.checked;
            if (wantSkill) {
                if (feedback) feedback.textContent = 'Mémorisation de la méthode en cours…';
                try {
                    const rs = await fetch('/api/coanimm/save_skill', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            consigne: _coanimmCurrentConsigne || '',
                            script: code,
                            thread_id: currentThreadId || null,
                        }),
                    });
                    const ds = await rs.json();
                    if (ds.status === 'created') {
                        suffix += ' Méthode mémorisée comme bond' + (ds.skill && ds.skill.label ? ' : ' + ds.skill.label : '') + '.';
                    } else if (ds.status === 'skip') {
                        suffix += ' (Méthode non retenue : déjà couverte par un bond existant.)';
                    } else {
                        suffix += ' (Méthode non mémorisée : ' + (ds.message || 'erreur') + '.)';
                    }
                } catch (e) {
                    suffix += ' (Méthode non mémorisée : erreur réseau.)';
                }
            }
            document.getElementById('coanimm-save-panel')?.setAttribute('hidden', '');
            if (feedback) feedback.textContent = '';
            if (st) { st.textContent += suffix; st.focus(); }
        } else {
            if (feedback) feedback.textContent = 'Erreur : ' + (d.detail || d.message || 'inconnue');
        }
    } catch(e) {
        if (feedback) feedback.textContent = 'Erreur réseau.';
    }
});

document.getElementById('coanimm-save-cancel')?.addEventListener('click', () => {
    document.getElementById('coanimm-save-panel')?.setAttribute('hidden', '');
});

// RACCOURCIS CLAVIER GLOBAUX (Alt+Maj+lettre)
// ══════════════════════════════════════════
(function () {
    var SHORTCUTS = {
        'f': 'toggle-history',    // Fils
        'a': 'toggle-agenda',     // Agenda
        'm': 'toggle-memory',     // Mémoire
        'g': 'toggle-galerie',    // Galerie d'images
        'e': 'toggle-enrich',     // Enrichissement web
        'p': 'toggle-settings',   // Paramètres
        'o': 'toggle-prompt-library',      // Promptothèque
        'r': 'toggle-search-conversations', // Recherches
        't': 'toggle-coanimm',             // agenT CoaNIMM
        'u': 'toggle-musique'              // mUsique (Lyria)
    };
    var LABELS = {
        'toggle-history': 'Alt+Shift+F', 'toggle-agenda': 'Alt+Shift+A',
        'toggle-memory': 'Alt+Shift+M', 'toggle-galerie': 'Alt+Shift+G',
        'toggle-enrich': 'Alt+Shift+E', 'toggle-settings': 'Alt+Shift+P',
        'toggle-prompt-library': 'Alt+Shift+O',
        'toggle-search-conversations': 'Alt+Shift+R',
        'toggle-coanimm': 'Alt+Shift+T',
        'toggle-musique': 'Alt+Shift+U'
    };
    // Le studio n'a plus de bouton dans la barre : son raccourci est annoncé
    // sur l'entrée du menu « + » qui l'ouvre.
    document.getElementById('plus-studio')?.setAttribute('aria-keyshortcuts', 'Alt+Shift+I');
    // Annonce les raccourcis aux lecteurs d'écran.
    Object.keys(LABELS).forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.setAttribute('aria-keyshortcuts', LABELS[id]);
    });
    var input = document.getElementById('user-input');
    if (input) input.setAttribute('aria-keyshortcuts', 'Alt+Shift+S');
    var _coaInput = document.getElementById('coanimm-consigne');
    if (_coaInput) _coaInput.setAttribute('aria-keyshortcuts', 'Alt+Shift+S');

    function focusModal(container) {
        if (!container || container.classList.contains('hidden')) return;
        // Cible l'élément de dialogue (ou le conteneur) pour que le lecteur d'écran y entre.
        var dlg = container.querySelector('[role="dialog"]') || container;
        dlg.setAttribute('tabindex', '-1');
        dlg.focus();
    }
    document.addEventListener('keydown', function (e) {
        if (!e.altKey || !e.shiftKey || e.ctrlKey || e.metaKey) return;
        var k = (e.key || '').toLowerCase();
        if (k === 's') {  // focus zone de saisie (contextuel : CoaNIMM si ouvert, sinon chat)
            e.preventDefault();
            var _coa = document.getElementById('coanimm-modal');
            if (_coa && !_coa.classList.contains('hidden')) {
                document.getElementById('coanimm-consigne')?.focus();
            } else {
                document.getElementById('user-input')?.focus();
            }
            return;
        }
        if (k === 'k') {   // K comme « parler » — dernière lettre libre parlante
            // Traité à part plutôt que dans la table SHORTCUTS : le bouton
            // sert AUSSI à raccrocher quand une conversation est en cours, et
            // il ne faut alors pas envoyer le focus dans une modale fermée.
            var _btnLive = document.getElementById('live-toggle');
            if (!_btnLive) return;
            e.preventDefault();
            var _enCours = (typeof _liveActif !== 'undefined') && _liveActif;
            _btnLive.click();
            if (!_enCours) {
                setTimeout(function () { focusModal(document.getElementById('live-modal')); }, 90);
            }
            return;
        }
        if (k === 'i') {   // studIo image et vidéo
            var _entree = document.getElementById('plus-studio');
            // Caché = pas de clé Gemini : ouvrir mènerait à un panneau inutilisable.
            if (!_entree || _entree.hidden) return;
            e.preventDefault();
            if (typeof window._ouvrirStudio === 'function') window._ouvrirStudio();
            setTimeout(function () { focusModal(document.getElementById('studio-modal')); }, 90);
            return;
        }
        var id = SHORTCUTS[k];
        if (id) {
            var btn = document.getElementById(id);
            if (btn) {
                e.preventDefault();
                btn.click();
                // Déplace le focus dans le panneau ouvert (sinon le lecteur d'écran reste en arrière).
                var targetId = (id === 'toggle-history') ? 'history-panel' : id.replace('toggle-', '') + '-modal';
                setTimeout(function () { focusModal(document.getElementById(targetId)); }, 90);
            }
        }
    });
})();

// ══════════════════════════════════════════
// MODE LOCAL (inférence Ollama + OCR Tesseract)
// ══════════════════════════════════════════
(function () {
    var toggle = document.getElementById('local-mode-toggle');
    var modelField = document.getElementById('local-mode-model');
    var msg = document.getElementById('local-mode-msg');
    if (!toggle) return;

    function updateMsg() {
        if (!msg) return;
        msg.textContent = toggle.checked
            ? 'Activé : inférence et OCR sur la machine (plus lent, sans clé). Web actif.'
            : '';
    }
    async function load() {
        try {
            var d = await fetch('/api/settings/local-mode').then(function (r) { return r.json(); });
            toggle.checked = !!d.enabled;
            if (modelField) modelField.value = d.ollama_model || '';
            updateMsg();
        } catch (e) {}
    }
    async function save() {
        try {
            await fetch('/api/settings/local-mode', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    enabled: toggle.checked,
                    ollama_model: modelField ? modelField.value.trim() : undefined
                })
            });
            updateMsg();
        } catch (e) {}
    }
    toggle.addEventListener('change', save);
    if (modelField) modelField.addEventListener('change', save);
    document.getElementById('toggle-settings')?.addEventListener('click', load);
    load();
})();

// ══════════════════════════════════════════
// MODERATION MISTRAL
// ══════════════════════════════════════════
(function () {
    var toggle   = document.getElementById('moderation-toggle');
    var status   = document.getElementById('moderation-status');
    var CATS     = ['sexual', 'hate', 'violence', 'jailbreak', 'selfharm', 'pii'];
    var CAT_KEYS = {'sexual':'sexual','hate':'hate_and_discrimination','violence':'violence_and_threats','jailbreak':'jailbreak','selfharm':'self_harm','pii':'pii'};
    if (!toggle) return;

    function _getSliderValues() {
        var cats = {};
        CATS.forEach(function(c) {
            var el = document.getElementById('mod-' + c);
            if (el) cats[CAT_KEYS[c]] = parseFloat(el.value) / 100;
        });
        return cats;
    }
    function _setSliderValues(cats) {
        CATS.forEach(function(c) {
            var el = document.getElementById('mod-' + c);
            var out = document.getElementById('mod-' + c + '-val');
            var key = CAT_KEYS[c];
            if (el && cats && cats[key] !== undefined) {
                el.value = Math.round(cats[key] * 100);
                if (out) out.textContent = cats[key].toFixed(2);
            }
        });
    }
    CATS.forEach(function(c) {
        var el = document.getElementById('mod-' + c);
        var out = document.getElementById('mod-' + c + '-val');
        if (el && out) {
            out.textContent = (parseFloat(el.value) / 100).toFixed(2);
            el.addEventListener('input', function() { out.textContent = (parseFloat(el.value) / 100).toFixed(2); });
            el.addEventListener('change', save);
        }
    });

    async function load() {
        try {
            var d = await fetch('/api/settings/moderation').then(function(r){ return r.json(); });
            toggle.checked = !!d.enabled;
            _setSliderValues(d.categories || {});
        } catch(e) {}
    }
    async function save() {
        try {
            await fetch('/api/settings/moderation', {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ enabled: toggle.checked, categories: _getSliderValues() })
            });
            if (status) {
                status.textContent = toggle.checked ? 'Filtre actif.' : '';
            }
        } catch(e) {}
    }
    toggle.addEventListener('change', save);
    document.getElementById('toggle-settings')?.addEventListener('click', load);
    load();
})();

// ── Genre de l'utilisateur (formulations genrées des relations) ──
(function () {
    var sel = document.getElementById('user-genre-select');
    if (!sel) return;
    async function load() {
        try { var d = await fetch('/api/settings/user-genre').then(function (r) { return r.json(); }); sel.value = d.genre || ''; } catch (e) {}
    }
    sel.addEventListener('change', async function () {
        try {
            await fetch('/api/settings/user-genre', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ genre: sel.value })
            });
        } catch (e) {}
    });
    document.getElementById('toggle-settings')?.addEventListener('click', load);
    load();
})();

// -- Dictee vocale (STT Whisper) --
(function () {
    var toggle    = document.getElementById('stt-enabled-toggle');
    var modelSel  = document.getElementById('stt-model-select');
    var modelRow  = document.getElementById('stt-model-row');
    if (!toggle) return;

    function applyVisibility(enabled) {
        // Bouton micro desktop
        if (micBtn) micBtn.style.display = enabled ? '' : 'none';
        // Bouton micro mobile
        var mobileBtn = document.getElementById('mobile-mic-btn');
        if (mobileBtn) mobileBtn.style.display = enabled ? '' : 'none';
        // Afficher/masquer le selecteur de modele et turbo
        if (modelRow) modelRow.style.display = enabled ? '' : 'none';
        var turboRow = document.getElementById('stt-turbo-row');
        if (turboRow) turboRow.style.display = enabled ? '' : 'none';
    }

    async function load() {
        try {
            var d = await fetch('/api/settings/stt').then(function (r) { return r.json(); });
            toggle.checked = !!d.enabled;
            if (modelSel) modelSel.value = d.model || 'base';
            applyVisibility(!!d.enabled);
        } catch (e) {}
    }

    async function save() {
        try {
            await fetch('/api/settings/stt', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    enabled: toggle.checked,
                    model:   modelSel ? modelSel.value : 'base'
                })
            });
            applyVisibility(toggle.checked);
        } catch (e) {}
    }

    toggle.addEventListener('change', save);
    if (modelSel) modelSel.addEventListener('change', save);
    document.getElementById('toggle-settings')?.addEventListener('click', load);
    load();
})();

// -- Turbo Whisper --
(function () {
    var turboToggle = document.getElementById('stt-turbo-toggle');
    if (!turboToggle) return;

    function applyTurbo(enabled) {
        _sttTurboActive = enabled;
        if (micBtn) micBtn.classList.toggle('turbo', enabled);
    }

    async function load() {
        try {
            var d = await fetch('/api/settings/stt-turbo').then(function (r) { return r.json(); });
            turboToggle.checked = !!d.enabled;
            applyTurbo(!!d.enabled);
        } catch (e) {}
    }

    async function save() {
        try {
            await fetch('/api/settings/stt-turbo', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: turboToggle.checked ? 'true' : 'false' })
            });
            applyTurbo(turboToggle.checked);
        } catch (e) {}
    }

    turboToggle.addEventListener('change', save);
    document.getElementById('toggle-settings')?.addEventListener('click', load);
    load();
})();

// -- Dictionnaire phonétique STT --
(function () {
    var modal    = document.getElementById('stt-dict-modal');
    var btnOpen  = document.getElementById('stt-dict-btn');
    var btnClose = document.getElementById('stt-dict-close');
    var btnAdd   = document.getElementById('stt-dict-add');
    var inFrom   = document.getElementById('stt-dict-from');
    var inTo     = document.getElementById('stt-dict-to');
    var list     = document.getElementById('stt-dict-list');
    if (!modal || !btnOpen) return;

    var _entries = [];

    function renderList() {
        list.innerHTML = '';
        if (_entries.length === 0) {
            list.innerHTML = '<span style="font-size:0.78rem;color:var(--text-muted);">Aucune entrée. Ajoutez vos premières corrections ci-dessous.</span>';
            return;
        }
        _entries.forEach(function (e, i) {
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:8px;background:var(--bg-input);font-size:0.85rem;';
            row.innerHTML = '<span style="flex:1;color:var(--text-muted);">' + e.from + '</span>'
                          + '<span style="color:var(--accent);">→</span>'
                          + '<span style="flex:1;">' + e.to + '</span>'
                          + '<button data-i="' + i + '" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:1rem;" title="Supprimer">🗑</button>';
            list.appendChild(row);
        });
        list.querySelectorAll('button[data-i]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                _entries.splice(parseInt(btn.dataset.i), 1);
                saveAndRender();
            });
        });
    }

    async function loadDict() {
        try {
            var d = await fetch('/api/stt/dict').then(function (r) { return r.json(); });
            _entries = d.entries || [];
            renderList();
        } catch (e) {}
    }

    async function saveAndRender() {
        try {
            await fetch('/api/stt/dict', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entries: _entries })
            });
            renderList();
        } catch (e) {}
    }

    btnOpen.addEventListener('click', function () {
        modal.style.display = 'flex';
        loadDict();
    });

    btnClose.addEventListener('click', function () {
        modal.style.display = 'none';
    });

    modal.addEventListener('click', function (ev) {
        if (ev.target === modal) modal.style.display = 'none';
    });

    btnAdd.addEventListener('click', function () {
        var f = inFrom.value.trim();
        var t = inTo.value.trim();
        if (!f || !t) return;
        _entries.push({ from: f, to: t });
        inFrom.value = '';
        inTo.value   = '';
        saveAndRender();
    });

    inTo.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') btnAdd.click();
    });
})();
// ── Moteur de recherche web (Brave / Tavily) ──
(function () {
    var sel = document.getElementById('search-provider-select');
    if (!sel) return;
    async function load() {
        try { var d = await fetch('/api/settings/search-provider').then(function (r) { return r.json(); }); sel.value = d.provider || 'auto'; } catch (e) {}
    }
    sel.addEventListener('change', async function () {
        try {
            await fetch('/api/settings/search-provider', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: sel.value })
            });
        } catch (e) {}
    });
    document.getElementById('toggle-settings')?.addEventListener('click', load);
    load();
})();

// ══════════════════════════════════════════
// CODE INTERPRETER MISTRAL CLOUD (CoaNIMM)
// ══════════════════════════════════════════
(function () {
    var btn    = document.getElementById('coanimm-cloud-ci-run');
    var prompt = document.getElementById('coanimm-cloud-ci-prompt');
    var status = document.getElementById('coanimm-cloud-ci-status');
    var result = document.getElementById('coanimm-cloud-ci-result');
    var codeEl = document.getElementById('coanimm-cloud-ci-code');
    var outEl  = document.getElementById('coanimm-cloud-ci-output');
    var filesEl = document.getElementById('coanimm-cloud-ci-files');
    var inject  = document.getElementById('coanimm-cloud-ci-inject');
    if (!btn) return;

    var _lastResult = null;

    btn.addEventListener('click', async function () {
        var task = (prompt && prompt.value.trim()) || '';
        if (!task) { if (status) status.textContent = 'Saisissez une consigne.'; return; }
        btn.disabled = true;
        if (status) status.textContent = 'Envoi a Mistral Code Interpreter...';
        if (result) result.classList.add('hidden');
        try {
            var r = await fetch('/api/coanimm/mistral_code_interpreter', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ task: task, prompt: task })
            });
            var d = await r.json();
            if (d.detail || d.error) throw new Error(d.detail || d.error);
            _lastResult = d;
            if (codeEl)  codeEl.value  = d.code   || '(aucun code retourne)';
            if (outEl)   outEl.value   = d.output || d.text || '(aucune sortie)';
            if (filesEl && d.files && d.files.length) {
                filesEl.innerHTML = '<p style="font-size:0.82rem;font-weight:600;margin:0 0 4px;">Fichiers produits :</p>' +
                    d.files.map(function(f) {
                        if (f.url && f.url.startsWith('data:image')) {
                            return '<img src="' + f.url + '" alt="Image produite" style="max-width:100%;border-radius:6px;margin-top:4px;">';
                        }
                        return '<a href="' + f.url + '" target="_blank" rel="noopener" style="font-size:0.82rem;">' + (f.name || 'fichier') + '</a>';
                    }).join('<br>');
            } else if (filesEl) {
                filesEl.innerHTML = '';
            }
            if (result) result.classList.remove('hidden');
            if (status) status.textContent = 'Execution terminee.';
        } catch(e) {
            if (status) status.textContent = 'Erreur : ' + (e.message || e);
        } finally {
            btn.disabled = false;
        }
    });

    if (inject) {
        inject.addEventListener('click', function () {
            if (!_lastResult) return;
            var txt = '';
            if (_lastResult.code)   txt += '```python\n' + _lastResult.code + '\n```\n\n';
            if (_lastResult.output || _lastResult.text) txt += (_lastResult.output || _lastResult.text) + '\n';
            var inp = document.getElementById('user-input');
            if (inp) {
                inp.value = (inp.value ? inp.value + '\n\n' : '') + txt.trim();
                inp.focus();
            }
        });
    }
})();

setupSettingsTabs();
init();

// ══════════════════════════════════════════
// VEILLE DOCUMENTAIRE (Exa)
// ══════════════════════════════════════════
(function () {
    function _vStatus(msg) {
        var el = document.getElementById('veille-status');
        if (el) el.textContent = msg;
    }

    async function _veilleCharger(annoncer) {
        var sel = document.getElementById('veille-select');
        if (!sel) return;
        try {
            var r = await fetch('/api/veille/sujets');
            var d = await r.json();
            var sujets = d.sujets || [];
            // Les catégories viennent du serveur : les libellés français y sont
            // définis une seule fois, à côté des valeurs qu'Exa impose.
            var cat = document.getElementById('veille-categorie');
            if (cat && !cat.options.length) {
                cat.innerHTML = (d.categories || []).map(function (c) {
                    return '<option value="' + c.valeur + '">' + c.libelle + '</option>';
                }).join('');
            }
            sel.innerHTML = sujets.length
                ? sujets.map(function (s) {
                      var etat = s.dernier_run
                          ? ('relevé le ' + s.dernier_run.slice(0, 10)
                             + (s.nb_trouves ? ', ' + s.nb_trouves + ' nouveauté(s)' : ''))
                          : 'jamais relevé';
                      return '<option value="' + s.id + '">' + s.libelle
                           + ' — ' + s.periode + ', ' + etat
                           + (s.du ? ' (à relever)' : '') + '</option>';
                  }).join('')
                : '<option value="">Aucun sujet suivi</option>';
            if (annoncer) {
                _vStatus(sujets.length ? sujets.length + ' sujet(s) suivi(s).'
                                       : 'Aucun sujet suivi pour l\'instant.');
            }
        } catch (e) { if (annoncer) _vStatus('Liste indisponible : ' + e.message); }
    }

    document.getElementById('veille-add-btn')?.addEventListener('click', async function () {
        var lib = (document.getElementById('veille-libelle')?.value || '').trim();
        var req = (document.getElementById('veille-requete')?.value || '').trim();
        var url = (document.getElementById('veille-url')?.value || '').trim();
        var per = document.getElementById('veille-periode')?.value || 'hebdomadaire';
        if (!req && !url) { _vStatus('Décris ce que tu cherches, ou donne une adresse de référence.'); return; }
        try {
            var r = await fetch('/api/veille/sujets', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ libelle: lib, requete: req, url_reference: url,
                                       periode: per,
                                       categorie: document.getElementById('veille-categorie')?.value || '' })
            });
            if (!r.ok) throw new Error(await r.text());
            var d = await r.json();
            _vStatus('Sujet suivi : « ' + d.libelle + ' », relevé ' + d.periode + '.');
            await _veilleCharger(false);
        } catch (e) { _vStatus('Erreur : ' + e.message); }
    });

    document.getElementById('veille-refresh-btn')?.addEventListener('click', function () {
        _veilleCharger(true);
    });

    document.getElementById('veille-run-btn')?.addEventListener('click', async function () {
        var id = document.getElementById('veille-select')?.value || '';
        if (!id) return;
        _vStatus('Relevé en cours… (cela peut prendre une minute)');
        var out = document.getElementById('veille-out');
        try {
            var r = await fetch('/api/veille/relever/' + encodeURIComponent(id), { method: 'POST' });
            var d = await r.json();
            _vStatus(d.message || 'Relevé terminé.');
            if (out) {
                out.innerHTML = '';
                (d.nouveautes || []).forEach(function (n, i) {
                    var det = document.createElement('details');
                    det.style.cssText = 'margin-top:6px;border:1px solid var(--border);border-radius:4px;padding:4px 8px;';
                    var sum = document.createElement('summary');
                    sum.textContent = (i + 1) + '. ' + n.titre + (n.date ? ' (' + n.date + ')' : '');
                    sum.style.cursor = 'pointer';
                    var pre = document.createElement('pre');
                    pre.style.cssText = 'white-space:pre-wrap;word-break:break-word;font-size:0.82rem;margin:6px 0 0;';
                    pre.textContent = n.url + '\n\n' + (n.extrait || '(pas d\'extrait)');
                    det.appendChild(sum); det.appendChild(pre);
                    out.appendChild(det);
                });
            }
            await _veilleCharger(false);
        } catch (e) { _vStatus('Erreur : ' + e.message); }
    });

    document.getElementById('veille-del-btn')?.addEventListener('click', async function () {
        var id = document.getElementById('veille-select')?.value || '';
        if (!id) return;
        if (!confirm('Ne plus suivre ce sujet ?')) return;
        try {
            await fetch('/api/veille/sujets/' + encodeURIComponent(id), { method: 'DELETE' });
            _vStatus('Sujet retiré.');
            await _veilleCharger(false);
        } catch (e) { _vStatus('Erreur : ' + e.message); }
    });

    document.getElementById('veille-details')?.addEventListener('toggle', function () {
        if (this.open) _veilleCharger(true);
    });

    // ── Annonce des relevés faits en arrière-plan ───────────────────────────
    // Le travailleur de fond relève à échéance, panneau fermé, NIMM parfois
    // ouvert depuis des heures. Sans cette boucle, le résultat n'existait que
    // dans la console du serveur : invisible à l'afficheur braille. Le serveur
    // CONSOMME les notifications (POST), donc chaque relevé est annoncé une
    // fois et une seule — pas de radotage toutes les cinq minutes.
    var _VEILLE_NOTIF_MS = 300000;

    function _veilleAnnoncer(txt) {
        // Une seule annonce groupée : _coanimmAnnounce remet la zone à vide
        // avant d'écrire, donc deux appels d'affilée s'écraseraient.
        if (typeof _coanimmAnnounce === 'function') { _coanimmAnnounce(txt); return; }
        var el = document.getElementById('coanimm-status-announce');
        if (el) { el.textContent = ''; setTimeout(function () { el.textContent = txt; }, 200); }
    }

    function _veilleRendreNouveautes(notifs) {
        // Trace consultable et COPIABLE : l'annonce vocale passe, le texte reste.
        var out = document.getElementById('veille-out');
        if (!out) return;
        notifs.forEach(function (n) {
            if (!(n.nouveautes || []).length) return;
            var bloc = document.createElement('details');
            bloc.open = true;
            bloc.style.cssText = 'margin-top:8px;border:1px solid var(--border);border-radius:4px;padding:4px 8px;';
            var sum = document.createElement('summary');
            sum.textContent = 'Relevé automatique — ' + (n.libelle || 'veille')
                + ' (' + (n.nouveautes || []).length + ' nouveauté'
                + ((n.nouveautes || []).length > 1 ? 's' : '') + ')';
            sum.style.cursor = 'pointer';
            bloc.appendChild(sum);
            var ul = document.createElement('ul');
            ul.style.cssText = 'margin:6px 0 0;padding-left:1.2em;font-size:0.85rem;';
            (n.nouveautes || []).forEach(function (a) {
                var li = document.createElement('li');
                li.style.marginBottom = '4px';
                var lien = document.createElement('a');
                lien.href = a.url; lien.target = '_blank'; lien.rel = 'noopener noreferrer';
                lien.textContent = a.titre || a.url;
                li.appendChild(lien);
                if (a.date) li.appendChild(document.createTextNode(' — ' + a.date));
                ul.appendChild(li);
            });
            bloc.appendChild(ul);
            out.insertBefore(bloc, out.firstChild);
        });
    }

    async function _veillePollNotifications() {
        try {
            var r = await fetch('/api/veille/notifications', { method: 'POST' });
            if (!r.ok) return;
            var d = await r.json();
            var notifs = d.notifications || [];
            if (!notifs.length) return;
            _veilleAnnoncer(notifs.map(function (n) { return n.message || ''; })
                                  .filter(Boolean).join(' '));
            _veilleRendreNouveautes(notifs);
            _veilleCharger(false).catch(function () {});
        } catch (e) { /* silencieux : un serveur muet ne doit pas faire de bruit */ }
    }

    setInterval(_veillePollNotifications, _VEILLE_NOTIF_MS);
    setTimeout(_veillePollNotifications, 8000);
})();

// ══════════════════════════════════════════
// PERTINENCE DE LA BASE DE CONNAISSANCES (réordonnancement)
// ══════════════════════════════════════════
(function () {
    function _rkStatus(msg) {
        var el = document.getElementById('rerank-status');
        if (el) el.textContent = msg;
    }
    function _rkVal(id) { return document.getElementById(id)?.value || ''; }

    async function _rerankCharger(annoncer) {
        try {
            var r = await fetch('/api/settings/rerank');
            var d = await r.json();
            var m = document.getElementById('rag-rerank-mode');
            if (m) m.value = d.mode || 'auto';
            var u = document.getElementById('rag-rerank-url');
            if (u) u.value = d.url || '';
            var mo = document.getElementById('rag-rerank-modele');
            if (mo) mo.value = d.modele || '';
            var se = document.getElementById('rag-rerank-seuil');
            if (se) se.value = d.seuil;
            if (annoncer) _rkStatus(d.explication || '');
        } catch (e) {
            if (annoncer) _rkStatus('Réglages indisponibles : ' + e.message);
        }
    }

    document.getElementById('rerank-save-btn')?.addEventListener('click', async function () {
        _rkStatus('Enregistrement…');
        try {
            var r = await fetch('/api/settings/rerank', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mode: _rkVal('rag-rerank-mode'),
                    url: _rkVal('rag-rerank-url'),
                    modele: _rkVal('rag-rerank-modele'),
                    seuil: parseFloat(_rkVal('rag-rerank-seuil') || '0.3')
                })
            });
            var d = await r.json();
            // On annonce l'effet RÉEL, pas « enregistré » : un moteur choisi sans
            // clé est accepté par le formulaire mais reste sans effet.
            _rkStatus('Enregistré. ' + (d.explication || ''));
        } catch (e) { _rkStatus('Erreur : ' + e.message); }
    });

    document.getElementById('rerank-test-btn')?.addEventListener('click', function () {
        _rerankCharger(true);
    });

    document.getElementById('rerank-details')?.addEventListener('toggle', function () {
        if (this.open) _rerankCharger(true);
    });

    // ── Banc d'essai : la même question dans chaque moteur ──────────────────
    // Rendu en TABLEAU par moteur plutôt qu'en prose : à l'afficheur braille,
    // un classement se parcourt ligne à ligne, il ne s'écoute pas en paragraphe.
    var _bancDernierTexte = '';

    function _bStatus(msg) {
        var el = document.getElementById('banc-status');
        if (el) el.textContent = msg;
    }

    function _bancRendre(d) {
        var out = document.getElementById('banc-out');
        if (!out) return;
        out.innerHTML = '';

        var chapeau = document.createElement('p');
        chapeau.style.cssText = 'font-size:0.85rem;margin:4px 0 10px;';
        chapeau.textContent = d.nb_passages + ' passage'
            + (d.nb_passages > 1 ? 's' : '') + ' candidat'
            + (d.nb_passages > 1 ? 's' : '') + ' — seuil de pertinence '
            + Number(d.seuil).toFixed(2) + '.';
        out.appendChild(chapeau);

        (d.moteurs || []).forEach(function (m) {
            var bloc = document.createElement('details');
            bloc.open = !!(m.ok && (m.classement || []).length);
            bloc.style.cssText = 'margin-top:8px;border:1px solid var(--border);border-radius:4px;padding:6px 10px;';
            var sum = document.createElement('summary');
            sum.style.cssText = 'cursor:pointer;font-weight:600;';
            sum.textContent = m.libelle + ' — '
                + (m.ok ? Number(m.secondes).toFixed(2) + ' s' : 'indisponible');
            bloc.appendChild(sum);

            var note = document.createElement('p');
            note.style.cssText = 'font-size:0.8rem;color:var(--text-muted);margin:6px 0;';
            note.textContent = m.note || '';
            bloc.appendChild(note);

            if ((m.classement || []).length) {
                var tab = document.createElement('table');
                tab.style.cssText = 'width:100%;border-collapse:collapse;font-size:0.82rem;';
                var cap = document.createElement('caption');
                cap.className = 'sr-only';
                cap.textContent = 'Classement des passages par ' + m.libelle;
                tab.appendChild(cap);
                var thead = document.createElement('thead');
                var trh = document.createElement('tr');
                ['Rang', 'Score', 'Servi', 'Document'].forEach(function (t) {
                    var th = document.createElement('th');
                    th.scope = 'col'; th.textContent = t;
                    th.style.cssText = 'text-align:left;padding:2px 6px;border-bottom:1px solid var(--border);';
                    trh.appendChild(th);
                });
                thead.appendChild(trh); tab.appendChild(thead);
                var tbody = document.createElement('tbody');
                (m.classement || []).forEach(function (l) {
                    var tr = document.createElement('tr');
                    var cells = [String(l.rang), String(l.score),
                                 l.retenu ? 'oui' : 'non',
                                 l.titre + (l.source ? ' — ' + l.source : '')];
                    cells.forEach(function (v, i) {
                        var td = document.createElement(i === 0 ? 'th' : 'td');
                        if (i === 0) td.scope = 'row';
                        td.textContent = v;
                        td.style.cssText = 'text-align:left;padding:2px 6px;border-bottom:1px solid var(--border);';
                        tr.appendChild(td);
                    });
                    tbody.appendChild(tr);
                });
                tab.appendChild(tbody);
                bloc.appendChild(tab);
            }
            out.appendChild(bloc);
        });

        _bancDernierTexte = d.texte || '';
        var zone = document.getElementById('banc-texte');
        var env = document.getElementById('banc-texte-details');
        if (zone) zone.value = _bancDernierTexte;
        if (env) env.hidden = !_bancDernierTexte;
    }

    // Quels moteurs répondront, AVANT de lancer une mesure de plusieurs dizaines
    // de secondes. Les indisponibles sont listés avec leur raison : « Voyage :
    // aucune clé » est une information, une ligne absente n'en est pas une.
    async function _bancMoteurs() {
        var box = document.getElementById('banc-moteurs');
        if (!box) return;
        try {
            var d = await fetch('/api/rag/banc/moteurs').then(function (r) { return r.json(); });
            box.innerHTML = '';
            var liste = d.moteurs || [];
            var prets = liste.filter(function (m) { return m.disponible; }).length;
            var titre = document.createElement('p');
            titre.style.cssText = 'margin:0 0 4px;';
            titre.textContent = prets + ' moteur' + (prets > 1 ? 's' : '')
                + ' interrogeable' + (prets > 1 ? 's' : '') + ' sur ' + liste.length + ' :';
            box.appendChild(titre);
            var ul = document.createElement('ul');
            ul.style.cssText = 'margin:0;padding-left:1.2em;';
            liste.forEach(function (m) {
                var li = document.createElement('li');
                li.textContent = (m.disponible ? '✔ ' : '· ') + m.libelle + ' — ' + m.raison;
                if (!m.disponible) li.style.color = 'var(--text-muted)';
                ul.appendChild(li);
            });
            box.appendChild(ul);
        } catch (e) { /* silencieux : le banc reste lançable */ }
    }

    document.getElementById('banc-details')?.addEventListener('toggle', function () {
        if (this.open) _bancMoteurs();
    });

    document.getElementById('banc-run-btn')?.addEventListener('click', async function () {
        var q = (document.getElementById('banc-question')?.value || '').trim();
        if (!q) { _bStatus('Écris d\'abord une question à mesurer.'); return; }
        var k = parseInt(document.getElementById('banc-k')?.value || '10', 10);
        _bStatus('Banc en cours… chaque moteur est interrogé à son tour, cela peut prendre une minute.');
        try {
            var r = await fetch('/api/rag/banc', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: q, k: isNaN(k) ? 10 : k, top_n: 5 })
            });
            var d = await r.json();
            if (!r.ok) { _bStatus(d.detail || 'Le banc n\'a pas pu aboutir.'); return; }
            _bancRendre(d);
            var ok = (d.moteurs || []).filter(function (m) { return m.ok; }).length;
            _bStatus('Banc terminé : ' + ok + ' moteur' + (ok > 1 ? 's ont' : ' a')
                + ' répondu sur ' + (d.moteurs || []).length + '. Résultats ci-dessous.');
        } catch (e) { _bStatus('Erreur : ' + e.message); }
    });

    document.getElementById('banc-copy-btn')?.addEventListener('click', async function () {
        if (!_bancDernierTexte) { _bStatus('Lance d\'abord le banc : il n\'y a rien à copier.'); return; }
        try {
            await navigator.clipboard.writeText(_bancDernierTexte);
            _bStatus('Rapport copié dans le presse-papiers.');
        } catch (e) {
            // Repli : sélectionner le texte, l'utilisateur fait Ctrl+C lui-même.
            var zone = document.getElementById('banc-texte');
            if (zone) { zone.focus(); zone.select(); _bStatus('Rapport sélectionné : fais Contrôle C pour le copier.'); }
            else _bStatus('Copie impossible : ' + e.message);
        }
    });
})();

// ══════════════════════════════════════════
// DOCUMENT DE LA CONVERSATION (tous fournisseurs)
// ══════════════════════════════════════════
(function () {
    function _tdStatus(msg) {
        var el = document.getElementById('thread-doc-status');
        if (el) el.textContent = msg;
    }
    function _tdThread() {
        return (typeof currentThreadId !== 'undefined' && currentThreadId) ? currentThreadId : '';
    }

    // La base de connaissances alimente le sélecteur : choisir dans une liste
    // vaut mieux que saisir une adresse Windows au clavier braille.
    async function _tdRemplirBase() {
        var sel = document.getElementById('thread-doc-base-select');
        if (!sel) return;
        try {
            var r = await fetch('/api/documents/base');
            var d = await r.json();
            var docs = d.documents || [];
            sel.innerHTML = '<option value="">— choisir un document —</option>'
                + docs.map(function (x) {
                      var ko = Math.max(1, Math.round((x.nb_car || 0) / 1000));
                      return '<option value="' + x.id + '">' + x.titre
                           + ' (' + ko + ' k caractères'
                           + (x.capture ? ', versé le ' + x.capture : '') + ')</option>';
                  }).join('');
            if (!docs.length) sel.innerHTML = '<option value="">Base de connaissances vide</option>';
        } catch (e) {
            sel.innerHTML = '<option value="">Base indisponible</option>';
        }
    }

    async function _threadDocRefresh() {
        var tid = _tdThread();
        if (!tid) { _tdStatus('Ouvre ou démarre une conversation pour y attacher un document.'); return; }
        try {
            var r = await fetch('/api/threads/' + encodeURIComponent(tid) + '/document');
            var d = await r.json();
            if (!d.attache) { _tdStatus('Aucun document attaché à cette conversation.'); return; }
            _tdStatus('Attaché : « ' + d.titre + ' », ' + d.nb_car + ' caractères'
                    + (d.tronque ? ' (tronqué)' : '') + '. ' + (d.regime || ''));
        } catch (e) { _tdStatus('Statut indisponible : ' + e.message); }
    }

    document.getElementById('thread-doc-attach-btn')?.addEventListener('click', async function () {
        var tid = _tdThread();
        if (!tid) { _tdStatus('Aucune conversation en cours.'); return; }
        var refId  = document.getElementById('thread-doc-base-select')?.value || '';
        var chemin = (document.getElementById('thread-doc-path')?.value || '').trim();
        if (!refId && !chemin) {
            _tdStatus('Choisis un document dans la liste, ou indique un chemin.'); return;
        }
        _tdStatus('Lecture du document…');
        try {
            var corps = refId ? { ref_id: parseInt(refId, 10) } : { chemin: chemin };
            var r = await fetch('/api/threads/' + encodeURIComponent(tid) + '/document', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(corps)
            });
            var d = await r.json();
            if (!d.ok) { _tdStatus('Échec : ' + (d.erreur || 'raison inconnue')); return; }
            _tdStatus('Attaché : « ' + d.titre + ' », ' + d.nb_car + ' caractères'
                    + (d.tronque ? ' (tronqué au-delà de 300 000 caractères)' : '')
                    + '. ' + (d.regime || ''));
        } catch (e) { _tdStatus('Erreur : ' + e.message); }
    });

    document.getElementById('thread-doc-detach-btn')?.addEventListener('click', async function () {
        var tid = _tdThread();
        if (!tid) return;
        try {
            var r = await fetch('/api/threads/' + encodeURIComponent(tid) + '/document', { method: 'DELETE' });
            var d = await r.json();
            _tdStatus(d.ok ? 'Document détaché ; le texte conservé a été effacé.'
                           : 'Aucun document n’était attaché.');
        } catch (e) { _tdStatus('Erreur : ' + e.message); }
    });

    document.getElementById('thread-doc-details')?.addEventListener('toggle', function () {
        if (this.open) { _tdRemplirBase(); _threadDocRefresh(); }
    });
})();

// ══════════════════════════════════════════
// DOCUMENTS ÉPINGLÉS (cache explicite Gemini)
// ══════════════════════════════════════════
(function () {
    var _pins = [];

    function _pinStatus(msg) {
        var el = document.getElementById('pin-status-out');
        if (el) el.textContent = msg;
    }

    // Combien de temps reste-t-il ? Une durée relative se lit mieux à la
    // synthèse vocale qu'un horodatage ISO.
    function _pinRestant(expire) {
        if (!expire) return '';
        var ms = new Date(expire).getTime() - Date.now();
        if (isNaN(ms)) return '';
        if (ms <= 0) return ' — expiré';
        var min = Math.round(ms / 60000);
        if (min < 60) return ' — encore ' + min + ' min';
        return ' — encore ' + Math.floor(min / 60) + ' h ' + (min % 60) + ' min';
    }

    async function _pinRefresh(silencieux) {
        var sel = document.getElementById('pin-select');
        if (!sel) return;
        try {
            var r = await fetch('/api/gemini/pins');
            var d = await r.json();
            _pins = d.pins || [];
        } catch (e) {
            if (!silencieux) _pinStatus('Liste indisponible : ' + e.message);
            return;
        }
        sel.innerHTML = _pins.length
            ? _pins.map(function (p) {
                  var t = (p.titre || p.name);
                  return '<option value="' + p.name + '">' + t
                       + ' (' + (p.nb_tokens || 0) + ' jetons)' + _pinRestant(p.expire) + '</option>';
              }).join('')
            : '<option value="">Aucun document épinglé</option>';
        if (!silencieux) {
            _pinStatus(_pins.length
                ? _pins.length + ' document(s) épinglé(s).'
                : 'Aucun document épinglé pour l\'instant.');
        }
    }

    document.getElementById('pin-create-btn')?.addEventListener('click', async function () {
        var chemin = (document.getElementById('pin-file-path')?.value || '').trim();
        var titre  = (document.getElementById('pin-title')?.value || '').trim();
        var duree  = parseFloat(document.getElementById('pin-duree')?.value || '2');
        if (!chemin) { _pinStatus('Indique le chemin du document à épingler.'); return; }
        _pinStatus('Lecture puis mise en cache… (cela peut prendre une minute)');
        try {
            var r = await fetch('/api/gemini/pins', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chemin: chemin, titre: titre, duree_h: duree })
            });
            var d = await r.json();
            if (!d.ok) { _pinStatus('Échec : ' + (d.erreur || 'raison inconnue')); return; }
            _pinStatus('Épinglé : « ' + (d.titre || titre) + ' », ' + (d.nb_tokens || 0)
                     + ' jetons. Les questions suivantes coûteront une fraction du prix.');
            await _pinRefresh(true);
        } catch (e) { _pinStatus('Erreur : ' + e.message); }
    });

    document.getElementById('pin-refresh-btn')?.addEventListener('click', function () { _pinRefresh(false); });

    document.getElementById('pin-ask-btn')?.addEventListener('click', async function () {
        var ref = document.getElementById('pin-select')?.value || '';
        var q   = (document.getElementById('pin-question')?.value || '').trim();
        var out = document.getElementById('pin-answer-out');
        if (!ref) { _pinStatus('Aucun document épinglé à interroger.'); return; }
        if (!q)   { _pinStatus('Écris ta question.'); return; }
        _pinStatus('Interrogation du document…');
        try {
            var r = await fetch('/api/gemini/pins/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reference: ref, question: q })
            });
            var d = await r.json();
            _pinStatus('Réponse reçue.');
            if (out) {
                out.innerHTML = '';
                var pre = document.createElement('pre');
                pre.style.cssText = 'white-space:pre-wrap;word-break:break-word;font-size:0.85rem;margin:0;';
                pre.textContent = d.result || '(vide)';
                var copie = document.createElement('button');
                copie.textContent = 'Copier la réponse';
                copie.className = 'btn-secondary';
                copie.style.cssText = 'font-size:0.75rem;margin-top:6px;';
                copie.setAttribute('aria-label', 'Copier la réponse du document épinglé');
                copie.addEventListener('click', function () {
                    navigator.clipboard.writeText(pre.textContent).then(function () {
                        copie.textContent = 'Copié !';
                        setTimeout(function () { copie.textContent = 'Copier la réponse'; }, 1500);
                    });
                });
                out.appendChild(pre);
                out.appendChild(copie);
                pre.setAttribute('tabindex', '-1');
                pre.focus();
            }
        } catch (e) { _pinStatus('Erreur : ' + e.message); }
    });

    document.getElementById('pin-delete-btn')?.addEventListener('click', async function () {
        var ref = document.getElementById('pin-select')?.value || '';
        if (!ref) return;
        if (!confirm('Libérer ce document épinglé ? Il faudra le réépingler pour l\'interroger à nouveau.')) return;
        try {
            await fetch('/api/gemini/pins?name=' + encodeURIComponent(ref), { method: 'DELETE' });
            _pinStatus('Document libéré.');
            await _pinRefresh(true);
        } catch (e) { _pinStatus('Erreur : ' + e.message); }
    });

    // On ne charge la liste qu'à l'ouverture du panneau : inutile d'appeler
    // Gemini à chaque démarrage de NIMM.
    document.getElementById('gemini-pins-details')?.addEventListener('toggle', function () {
        if (this.open) _pinRefresh(false);
    });
})();

// ══════════════════════════════════════════
// MISTRAL BATCH
// ══════════════════════════════════════════
(function () {
    var _batchJobId = null;

    // Fournisseur choisi : routes et modèles en dépendent.
    function _batchProvider() {
        return document.getElementById('batch-provider-select')?.value || 'mistral';
    }
    function _batchBase() {
        return '/api/' + _batchProvider() + '/batch';
    }
    var _BATCH_MODELS = {
        mistral: [
            ['mistral-small-latest', 'Mistral Small (rapide, économique)'],
            ['mistral-medium-latest', 'Mistral Medium'],
            ['mistral-large-latest', 'Mistral Large'],
            ['magistral-small-latest', 'Magistral Small (raisonnement)'],
            ['magistral-medium-latest', 'Magistral Medium (raisonnement)'],
        ],
        anthropic: [],
        gemini: [],
    };
    var _BATCH_ANTHROPIC_REPLI = [
        ['claude-haiku-4-5-20251001', 'Claude Haiku (rapide, économique)'],
        ['claude-sonnet-4-6', 'Claude Sonnet (équilibre)'],
    ];
    var _BATCH_GEMINI_REPLI = [
        ['gemini-2.5-flash', 'Gemini Flash (rapide, économique)'],
        ['gemini-2.5-pro', 'Gemini Pro (plus fin)'],
    ];
    async function _batchPopulateModels() {
        var sel = document.getElementById('batch-model-select');
        if (!sel) return;
        var p = _batchProvider();
        var liste = _BATCH_MODELS[p] || [];
        // Mistral garde une liste écrite en dur ; pour les deux autres on
        // interroge le fournisseur, avec une liste de repli s'il ne répond pas.
        if ((p === 'anthropic' || p === 'gemini') && !liste.length) {
            try {
                var r = await fetch('/api/models/' + p);
                var d = await r.json();
                liste = (d.models || []).map(function (m) { return [m.id, m.label || m.id]; });
            } catch (e) { /* repli */ }
            if (!liste.length) liste = (p === 'gemini' ? _BATCH_GEMINI_REPLI : _BATCH_ANTHROPIC_REPLI);
            _BATCH_MODELS[p] = liste;
        }
        sel.innerHTML = liste.map(function (m) {
            return '<option value="' + m[0] + '">' + m[1] + '</option>';
        }).join('');
    }
    document.getElementById('batch-provider-select')?.addEventListener('change', function () {
        _batchSetJobId(null);
        _batchSetStatus('Fournisseur changé : ' + _batchProvider() + '. Nouveau lot à soumettre.');
        _batchPopulateModels();
    });
    _batchPopulateModels();

    function _batchSetStatus(msg) {
        var el = document.getElementById('batch-status-out');
        if (el) el.textContent = msg;
    }
    function _batchSetJobId(id) {
        _batchJobId = id;
        var el = document.getElementById('batch-job-id');
        if (el) el.textContent = id ? 'Job ID : ' + id : '';
        var s = document.getElementById('batch-status-btn');
        var r = document.getElementById('batch-results-btn');
        var c = document.getElementById('batch-cancel-btn');
        if (s) s.disabled = !id;
        if (r) r.disabled = !id;
        if (c) c.disabled = !id;
    }

    document.getElementById('batch-submit-btn')?.addEventListener('click', async function () {
        var raw = (document.getElementById('batch-prompts')?.value || '').trim();
        if (!raw) { _batchSetStatus('Entrez au moins une requête.'); return; }
        var prompts = raw.split('\n').map(l => l.trim()).filter(Boolean);
        var model   = document.getElementById('batch-model-select')?.value || 'mistral-small-latest';
        var maxTok  = parseInt(document.getElementById('batch-max-tokens')?.value || '1024', 10);
        _batchSetStatus('Envoi du lot… (' + prompts.length + ' requêtes)');
        try {
            var resp = await fetch(_batchBase() + '/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompts, model, max_tokens: maxTok })
            });
            if (!resp.ok) throw new Error(await resp.text());
            var data = await resp.json();
            _batchSetJobId(data.job_id || data.batch_id);
            _batchSetStatus('Lot soumis. Statut : ' + (data.status || '?'));
        } catch(e) { _batchSetStatus('Erreur : ' + e.message); }
    });

    document.getElementById('batch-status-btn')?.addEventListener('click', async function () {
        if (!_batchJobId) return;
        _batchSetStatus('Vérification…');
        try {
            var resp = await fetch(_batchBase() + '/status/' + _batchJobId);
            if (!resp.ok) throw new Error(await resp.text());
            var d = await resp.json();
            var detail = '';
            if (d.total_requests) {
                detail = ' | ' + (d.succeeded_requests || 0) + '/' + d.total_requests + ' réussies';
            } else if (d.succeeded !== undefined) {
                detail = ' | ' + (d.succeeded || 0) + ' réussies, ' + (d.errored || 0)
                       + ' en erreur, ' + (d.processing || 0) + ' en cours';
            }
            _batchSetStatus('Statut : ' + (d.libelle || d.status) + detail
                          + (d.erreur ? ' — ' + d.erreur : ''));
        } catch(e) { _batchSetStatus('Erreur : ' + e.message); }
    });

    document.getElementById('batch-results-btn')?.addEventListener('click', async function () {
        if (!_batchJobId) return;
        _batchSetStatus('Récupération des résultats…');
        var out = document.getElementById('batch-results-out');
        try {
            var resp = await fetch(_batchBase() + '/results/' + _batchJobId);
            if (!resp.ok) throw new Error(await resp.text());
            var d = await resp.json();
            if (d.status !== 'SUCCESS' && d.status !== 'ended') {
                _batchSetStatus('Pas encore terminé (statut : ' + d.status + ').');
                return;
            }
            _batchSetStatus(d.results.length + ' résultat(s) reçu(s).');
            if (out) {
                out.innerHTML = '';
                d.results.forEach(function (r, i) {
                    var wrap = document.createElement('details');
                    wrap.style.cssText = 'margin-top:6px;border:1px solid var(--border);border-radius:4px;padding:4px 8px;';
                    var sum = document.createElement('summary');
                    sum.textContent = 'Résultat ' + (i + 1) + (r.error ? ' ⚠️ erreur' : '');
                    sum.style.cursor = 'pointer';
                    var pre = document.createElement('pre');
                    pre.style.cssText = 'white-space:pre-wrap;word-break:break-word;font-size:0.82rem;margin:6px 0 0;';
                    pre.textContent = r.error ? '[Erreur] ' + JSON.stringify(r.error) : (r.text || '(vide)');
                    var copyBtn = document.createElement('button');
                    copyBtn.textContent = 'Copier';
                    copyBtn.className = 'btn-secondary';
                    copyBtn.style.cssText = 'font-size:0.75rem;margin-top:4px;';
                    copyBtn.setAttribute('aria-label', 'Copier le résultat ' + (i + 1));
                    copyBtn.addEventListener('click', function () {
                        navigator.clipboard.writeText(pre.textContent).then(function () {
                            copyBtn.textContent = 'Copié !';
                            setTimeout(function () { copyBtn.textContent = 'Copier'; }, 1500);
                        });
                    });
                    wrap.appendChild(sum);
                    wrap.appendChild(pre);
                    wrap.appendChild(copyBtn);
                    out.appendChild(wrap);
                });
            }
        } catch(e) { _batchSetStatus('Erreur : ' + e.message); }
    });

    document.getElementById('batch-cancel-btn')?.addEventListener('click', async function () {
        if (!_batchJobId) return;
        if (!confirm('Annuler ce job batch ?')) return;
        try {
            var resp = await fetch(_batchBase() + '/' + _batchJobId, { method: 'DELETE' });
            if (!resp.ok) throw new Error(await resp.text());
            _batchSetStatus('Job annulé.');
            _batchSetJobId(null);
        } catch(e) { _batchSetStatus('Erreur : ' + e.message); }
    });
})();
// ══════════════════════════════════════════
// MUSIQUE (Lyria 3) — génération et bibliothèque
// ══════════════════════════════════════════
//
// Deux exigences ont dessiné ce panneau :
//   1. le résultat d'une génération musicale n'est pas QUE du son — le modèle
//      rend aussi les paroles et la structure. C'est la seule partie lisible au
//      braille : elle est affichée dans une zone de texte copiable, pas noyée ;
//   2. une génération peut durer plusieurs minutes. Le bouton se désarme et
//      l'attente est annoncée, sinon rien ne distingue « ça travaille » de
//      « c'est cassé ».
(function () {
    var _musModeles = [];

    function _mStatus(msg) {
        var el = document.getElementById('musique-status');
        if (el) el.textContent = msg;
    }

    function _musMajFormats() {
        var sel = document.getElementById('musique-modele');
        var fmt = document.getElementById('musique-format');
        var aide = document.getElementById('musique-modele-aide');
        var m = _musModeles.filter(function (x) { return x.nom === (sel && sel.value); })[0];
        if (!m || !fmt) return;
        if (aide) aide.textContent = m.description || '';
        var formats = m.formats || ['mp3'];
        fmt.innerHTML = '';
        formats.forEach(function (f) {
            var o = document.createElement('option');
            o.value = f; o.textContent = f.toUpperCase();
            fmt.appendChild(o);
        });
        fmt.disabled = formats.length < 2;
    }

    async function _musChargerModeles() {
        try {
            var r = await fetch('/api/musique/modeles');
            var d = await r.json();
            _musModeles = d.modeles || [];
            var note = document.getElementById('musique-note');
            if (note) note.textContent = d.note || '';
            var sel = document.getElementById('musique-modele');
            if (sel) {
                sel.innerHTML = '';
                _musModeles.forEach(function (m) {
                    var o = document.createElement('option');
                    o.value = m.nom; o.textContent = m.libelle;
                    sel.appendChild(o);
                });
            }
            _musMajFormats();
            var btn = document.getElementById('musique-gen-btn');
            if (btn) btn.disabled = !d.cle_presente;
        } catch (e) { _mStatus('Modèles indisponibles : ' + e.message); }
    }

    function _musCarte(m) {
        var bloc = document.createElement('details');
        bloc.style.cssText = 'margin-top:8px;border:1px solid var(--border);border-radius:6px;padding:6px 10px;';
        var sum = document.createElement('summary');
        sum.style.cssText = 'cursor:pointer;font-weight:600;';
        sum.textContent = (m.prompt || m.fichier || 'Morceau').slice(0, 90)
            + (m.cree_le ? ' — ' + m.cree_le.replace('T', ' à ').slice(0, 16) : '');
        bloc.appendChild(sum);

        var audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'none';
        audio.src = m.url;
        audio.style.cssText = 'width:100%;margin-top:8px;';
        audio.setAttribute('aria-label', 'Lecteur : ' + (m.prompt || m.fichier || 'morceau'));
        bloc.appendChild(audio);

        if (m.paroles) {
            var lab = document.createElement('label');
            lab.style.cssText = 'display:block;font-size:0.8rem;margin-top:8px;';
            var idz = 'musique-paroles-' + (m.fichier || '').replace(/[^a-z0-9]/gi, '');
            lab.setAttribute('for', idz);
            lab.textContent = 'Paroles et structure';
            var zone = document.createElement('textarea');
            zone.id = idz;
            zone.readOnly = true;
            zone.rows = 8;
            zone.value = m.paroles;
            zone.style.cssText = 'width:100%;box-sizing:border-box;font-size:0.82rem;margin-top:4px;';
            bloc.appendChild(lab);
            bloc.appendChild(zone);
        }

        var barre = document.createElement('div');
        barre.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;';
        var dl = document.createElement('a');
        dl.href = m.url;
        dl.download = m.fichier || 'morceau';
        dl.className = 'btn-secondary';
        dl.textContent = 'Télécharger';
        dl.setAttribute('aria-label', 'Télécharger le fichier ' + (m.fichier || ''));
        barre.appendChild(dl);
        var sup = document.createElement('button');
        sup.className = 'btn-secondary';
        sup.textContent = 'Supprimer';
        sup.setAttribute('aria-label', 'Supprimer ce morceau');
        sup.addEventListener('click', async function () {
            if (!confirm('Supprimer ce morceau ?')) return;
            try {
                await fetch('/api/musique/' + encodeURIComponent(m.fichier), { method: 'DELETE' });
                _mStatus('Morceau supprimé.');
                _musChargerBiblio();
            } catch (e) { _mStatus('Erreur : ' + e.message); }
        });
        barre.appendChild(sup);
        bloc.appendChild(barre);
        return bloc;
    }

    async function _musChargerBiblio() {
        var box = document.getElementById('musique-biblio');
        if (!box) return;
        try {
            var r = await fetch('/api/musique');
            var d = await r.json();
            box.innerHTML = '';
            var liste = d.musiques || [];
            if (!liste.length) {
                var p = document.createElement('p');
                p.style.cssText = 'color:var(--text-muted);font-size:0.85rem;';
                p.textContent = 'Aucun morceau pour le moment.';
                box.appendChild(p);
                return;
            }
            var titre = document.createElement('h4');
            titre.textContent = 'Bibliothèque — ' + liste.length + ' morceau'
                + (liste.length > 1 ? 'x' : '');
            titre.style.cssText = 'font-size:0.9rem;margin:10px 0 4px;';
            box.appendChild(titre);
            liste.forEach(function (m) { box.appendChild(_musCarte(m)); });
        } catch (e) { _mStatus('Bibliothèque indisponible : ' + e.message); }
    }

    document.getElementById('musique-modele')?.addEventListener('change', _musMajFormats);

    document.getElementById('musique-gen-btn')?.addEventListener('click', async function () {
        var prompt = (document.getElementById('musique-prompt')?.value || '').trim();
        if (!prompt) { _mStatus('Décris d\'abord la musique que tu veux.'); return; }
        var modele = document.getElementById('musique-modele')?.value || 'clip';
        var format = document.getElementById('musique-format')?.value || 'mp3';
        var btn = this;
        btn.disabled = true;
        _mStatus('Génération en cours. Un clip demande environ une minute, un '
            + 'morceau complet plusieurs minutes — laisse la fenêtre ouverte.');
        try {
            var r = await fetch('/api/musique/generer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: prompt, modele: modele, format: format })
            });
            var d = await r.json();
            if (!r.ok) { _mStatus(d.detail || 'La génération a échoué.'); return; }
            _mStatus('Morceau prêt en ' + d.secondes + ' secondes'
                + (d.paroles ? ', avec paroles.' : '.')
                + ' Il est en tête de la bibliothèque ci-dessous.');
            await _musChargerBiblio();
        } catch (e) { _mStatus('Erreur : ' + e.message); }
        finally { btn.disabled = false; }
    });

    document.getElementById('musique-refresh-btn')?.addEventListener('click', function () {
        _mStatus('Rafraîchissement…');
        _musChargerBiblio().then(function () { _mStatus('Bibliothèque à jour.'); });
    });

    document.getElementById('toggle-musique')?.addEventListener('click', function () {
        document.getElementById('musique-modal')?.classList.remove('hidden');
        _musChargerModeles();
        _musChargerBiblio();
        setTimeout(function () { document.getElementById('musique-prompt')?.focus(); }, 60);
    });
    document.getElementById('musique-close')?.addEventListener('click', function () {
        document.getElementById('musique-modal')?.classList.add('hidden');
    });
    document.getElementById('musique-modal')?.addEventListener('click', function (e) {
        if (e.target === this) this.classList.add('hidden');
    });
})();

// ══════════════════════════════════════════
// STUDIO — image réglée (Nano Banana) et vidéo (Veo)
// ══════════════════════════════════════════
//
// Trois choix de conception, tous dictés par l'usage au lecteur d'écran :
//   1. l'image générée est TOUJOURS accompagnée d'une description (alt WCAG)
//      quand la case est cochée : une image sans texte alternatif est un
//      fichier muet, et c'est le texte qui compte ici, pas la vignette ;
//   2. la vidéo dure de onze secondes à six minutes. Le suivi annonce
//      l'avancement à intervalle ESPACÉ (30 s) : une annonce toutes les cinq
//      secondes couvrirait tout le reste à la synthèse vocale ;
//   3. une génération lancée survit à un rechargement de page — l'opération
//      vit chez Google et NIMM garde sa trace sur disque, donc on la reprend.
(function () {
    var _stImageModeles = [], _stVideoModeles = [];
    var _stVideoTimer = null, _stVideoDebut = 0;
    var _ST_INTERVALLE_MS = 30000;

    function _stImgStatus(m) {
        var e = document.getElementById('studio-image-status');
        if (e) e.textContent = m;
    }
    function _stVidStatus(m) {
        var e = document.getElementById('studio-video-status');
        if (e) e.textContent = m;
    }
    function _stRemplir(id, valeurs, libelle) {
        var sel = document.getElementById(id);
        if (!sel) return;
        sel.innerHTML = '';
        valeurs.forEach(function (v) {
            var o = document.createElement('option');
            if (typeof v === 'string') { o.value = v; o.textContent = v; }
            else { o.value = v.valeur || v.nom; o.textContent = libelle ? libelle(v) : (v.libelle || v.valeur); }
            sel.appendChild(o);
        });
    }

    // ── Image ───────────────────────────────────────────────────────────────
    function _stImgMajTailles() {
        var sel = document.getElementById('studio-image-modele');
        var m = _stImageModeles.filter(function (x) { return x.nom === (sel && sel.value); })[0];
        if (!m) return;
        var aide = document.getElementById('studio-image-aide');
        if (aide) aide.textContent = m.description || '';
        _stRemplir('studio-image-taille', m.tailles || ['1K']);
    }

    async function _stChargerImage() {
        try {
            var d = await fetch('/api/imagerie/options').then(function (r) { return r.json(); });
            _stImageModeles = d.modeles || [];
            var note = document.getElementById('studio-image-note');
            if (note) note.textContent = d.note || '';
            _stRemplir('studio-image-modele', _stImageModeles, function (m) { return m.libelle; });
            _stRemplir('studio-image-ratio', d.ratios || [], function (r) { return r.libelle; });
            _stImgMajTailles();
            var btn = document.getElementById('studio-image-btn');
            if (btn) btn.disabled = !d.cle_presente;
        } catch (e) { _stImgStatus('Réglages indisponibles : ' + e.message); }
    }

    document.getElementById('studio-image-modele')?.addEventListener('change', _stImgMajTailles);

    document.getElementById('studio-image-btn')?.addEventListener('click', async function () {
        var prompt = (document.getElementById('studio-image-prompt')?.value || '').trim();
        if (!prompt) { _stImgStatus('Décris d\'abord l\'image que tu veux.'); return; }
        var btn = this;
        btn.disabled = true;
        _stImgStatus('Génération en cours…');
        try {
            var r = await fetch('/api/imagerie/generer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: prompt,
                    modele: document.getElementById('studio-image-modele')?.value || 'flash',
                    ratio: document.getElementById('studio-image-ratio')?.value || '1:1',
                    taille: document.getElementById('studio-image-taille')?.value || '1K',
                    decrire: !!document.getElementById('studio-image-decrire')?.checked
                })
            });
            var d = await r.json();
            if (!r.ok) { _stImgStatus(d.detail || 'La génération a échoué.'); return; }

            var out = document.getElementById('studio-image-out');
            if (out) {
                out.innerHTML = '';
                (d.images || []).forEach(function (im) {
                    var bloc = document.createElement('div');
                    bloc.style.cssText = 'margin-top:8px;border:1px solid var(--border);border-radius:6px;padding:8px 10px;';
                    var vign = document.createElement('img');
                    vign.src = im.url;
                    // L'alt EST le contenu ici : sans description, on ne ment pas
                    // avec un alt inventé, on dit que la description manque.
                    vign.alt = im.alt || 'Image générée, sans description disponible';
                    vign.style.cssText = 'max-width:100%;height:auto;border-radius:4px;';
                    bloc.appendChild(vign);

                    var lab = document.createElement('label');
                    var idz = 'studio-alt-' + (im.fichier || '').replace(/[^a-z0-9]/gi, '');
                    lab.setAttribute('for', idz);
                    lab.textContent = 'Description de l\'image (texte alternatif)';
                    lab.style.cssText = 'display:block;font-size:0.8rem;margin-top:8px;';
                    var zone = document.createElement('textarea');
                    zone.id = idz; zone.rows = 4; zone.readOnly = true;
                    zone.value = im.alt || '(aucune description — la case était décochée, '
                        + 'ou le modèle de vision n\'a pas répondu)';
                    zone.style.cssText = 'width:100%;box-sizing:border-box;font-size:0.82rem;margin-top:4px;';
                    bloc.appendChild(lab); bloc.appendChild(zone);

                    var det = document.createElement('p');
                    det.style.cssText = 'font-size:0.78rem;color:var(--text-muted);margin:6px 0 0;';
                    det.textContent = 'Format ' + (im.ratio || '?') + ', résolution '
                        + (im.taille || '?') + ', modèle ' + (im.modele || '?') + '.';
                    bloc.appendChild(det);

                    var dl = document.createElement('a');
                    dl.href = im.url; dl.download = im.fichier || 'image.png';
                    dl.className = 'btn-secondary';
                    dl.textContent = 'Télécharger';
                    dl.style.cssText = 'display:inline-block;margin-top:8px;';
                    bloc.appendChild(dl);
                    out.appendChild(bloc);
                });
            }
            var avecAlt = (d.images || []).filter(function (i) { return i.alt; }).length;
            _stImgStatus('Image prête en ' + d.secondes + ' secondes'
                + (avecAlt ? ', avec sa description ci-dessous.' : '.')
                + ' Elle est aussi rangée dans la galerie.');
        } catch (e) { _stImgStatus('Erreur : ' + e.message); }
        finally { btn.disabled = false; }
    });

    // ── Vidéo ───────────────────────────────────────────────────────────────
    function _stVidMajResolutions() {
        var sel = document.getElementById('studio-video-modele');
        var m = _stVideoModeles.filter(function (x) { return x.nom === (sel && sel.value); })[0];
        if (!m) return;
        var aide = document.getElementById('studio-video-aide');
        if (aide) aide.textContent = m.description || '';
        _stRemplir('studio-video-resolution', m.resolutions || ['720p']);
    }

    async function _stChargerVideo() {
        try {
            var d = await fetch('/api/video/options').then(function (r) { return r.json(); });
            _stVideoModeles = d.modeles || [];
            var note = document.getElementById('studio-video-note');
            if (note) note.textContent = (d.note || '') + ' ' + (d.avertissement || '');
            _stRemplir('studio-video-modele', _stVideoModeles, function (m) { return m.libelle; });
            _stRemplir('studio-video-ratio', d.ratios || [], function (r) { return r.libelle; });
            _stRemplir('studio-video-duree', d.durees || ['8']);
            _stVidMajResolutions();
            var btn = document.getElementById('studio-video-btn');
            if (btn) btn.disabled = !d.cle_presente;
        } catch (e) { _stVidStatus('Réglages indisponibles : ' + e.message); }
    }

    document.getElementById('studio-video-modele')?.addEventListener('change', _stVidMajResolutions);

    function _stArreterSuivi() {
        if (_stVideoTimer) { clearInterval(_stVideoTimer); _stVideoTimer = null; }
        var btn = document.getElementById('studio-video-btn');
        if (btn) btn.disabled = false;
    }

    function _stSuivre(operation) {
        _stArreterSuivi();
        _stVideoDebut = Date.now();
        var btn = document.getElementById('studio-video-btn');
        if (btn) btn.disabled = true;

        async function tour() {
            try {
                var r = await fetch('/api/video/etat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ operation: operation })
                });
                var d = await r.json();
                if (!r.ok) { _stVidStatus(d.detail || 'La génération a échoué.'); _stArreterSuivi(); return; }
                if (!d.fait) {
                    var min = Math.round((Date.now() - _stVideoDebut) / 60000);
                    _stVidStatus('Génération en cours' + (min >= 1 ? ' depuis ' + min + ' minute'
                        + (min > 1 ? 's' : '') : '') + '. Tu peux fermer cette fenêtre : '
                        + 'la génération continue et se retrouvera dans la bibliothèque.');
                    return;
                }
                _stArreterSuivi();
                if (d.erreur) { _stVidStatus(d.erreur); return; }
                _stVidStatus('Vidéo prête, téléchargée sur ta machine. '
                    + 'Elle est en tête de la bibliothèque ci-dessous.');
                _stChargerBiblioVideo();
            } catch (e) {
                // Le réseau peut hoqueter : la génération, elle, continue chez
                // Google. On ne coupe pas le suivi pour autant.
                _stVidStatus('État indisponible pour l\'instant, nouvelle tentative dans 30 secondes.');
            }
        }
        _stVideoTimer = setInterval(tour, _ST_INTERVALLE_MS);
        setTimeout(tour, 8000);
    }

    document.getElementById('studio-video-btn')?.addEventListener('click', async function () {
        var prompt = (document.getElementById('studio-video-prompt')?.value || '').trim();
        if (!prompt) { _stVidStatus('Décris d\'abord la vidéo que tu veux.'); return; }
        _stVidStatus('Lancement…');
        try {
            var r = await fetch('/api/video/lancer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: prompt,
                    modele: document.getElementById('studio-video-modele')?.value || 'veo31',
                    ratio: document.getElementById('studio-video-ratio')?.value || '16:9',
                    duree: document.getElementById('studio-video-duree')?.value || '8',
                    resolution: document.getElementById('studio-video-resolution')?.value || '720p'
                })
            });
            var d = await r.json();
            if (!r.ok) { _stVidStatus(d.detail || 'Le lancement a échoué.'); return; }
            _stVidStatus('Génération lancée' + (d.note ? '. ' + d.note : '')
                + ' Compte de onze secondes à six minutes.');
            _stSuivre(d.operation);
        } catch (e) { _stVidStatus('Erreur : ' + e.message); }
    });

    async function _stReprendre() {
        // Une génération lancée avant un rechargement de page vit toujours
        // chez Google : on la reprend plutôt que de la perdre de vue.
        try {
            var d = await fetch('/api/video/en-cours').then(function (r) { return r.json(); });
            var liste = d.en_cours || [];
            if (!liste.length || _stVideoTimer) return;
            _stVidStatus('Une génération lancée précédemment est reprise : « '
                + (liste[0].prompt || '').slice(0, 60) + ' ».');
            _stSuivre(liste[0].operation);
        } catch (e) { /* silencieux */ }
    }

    async function _stChargerBiblioVideo() {
        var box = document.getElementById('studio-video-biblio');
        if (!box) return;
        try {
            var d = await fetch('/api/video').then(function (r) { return r.json(); });
            box.innerHTML = '';
            var liste = d.videos || [];
            if (!liste.length) {
                var p = document.createElement('p');
                p.style.cssText = 'color:var(--text-muted);font-size:0.85rem;';
                p.textContent = 'Aucune vidéo pour le moment.';
                box.appendChild(p);
                return;
            }
            liste.forEach(function (v) {
                var bloc = document.createElement('details');
                bloc.style.cssText = 'margin-top:8px;border:1px solid var(--border);border-radius:6px;padding:6px 10px;';
                var sum = document.createElement('summary');
                sum.style.cssText = 'cursor:pointer;font-weight:600;';
                sum.textContent = (v.prompt || v.fichier || 'Vidéo').slice(0, 80)
                    + (v.cree_le ? ' — ' + v.cree_le.replace('T', ' à ').slice(0, 16) : '');
                bloc.appendChild(sum);

                var lecteur = document.createElement('video');
                lecteur.controls = true;
                lecteur.preload = 'none';
                lecteur.src = v.url;
                lecteur.style.cssText = 'width:100%;margin-top:8px;border-radius:4px;';
                lecteur.setAttribute('aria-label', 'Lecteur vidéo : ' + (v.prompt || v.fichier || ''));
                bloc.appendChild(lecteur);

                var det = document.createElement('p');
                det.style.cssText = 'font-size:0.78rem;color:var(--text-muted);margin:6px 0 0;';
                det.textContent = 'Format ' + (v.ratio || '?') + ', ' + (v.duree || '?')
                    + ' secondes, ' + (v.resolution || '?') + ', modèle ' + (v.modele || '?') + '.';
                bloc.appendChild(det);

                var barre = document.createElement('div');
                barre.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;';
                var dl = document.createElement('a');
                dl.href = v.url; dl.download = v.fichier || 'video.mp4';
                dl.className = 'btn-secondary'; dl.textContent = 'Télécharger';
                dl.setAttribute('aria-label', 'Télécharger la vidéo ' + (v.fichier || ''));
                barre.appendChild(dl);
                var sup = document.createElement('button');
                sup.className = 'btn-secondary'; sup.textContent = 'Supprimer';
                sup.setAttribute('aria-label', 'Supprimer cette vidéo');
                sup.addEventListener('click', async function () {
                    if (!confirm('Supprimer cette vidéo ?')) return;
                    try {
                        await fetch('/api/video/' + encodeURIComponent(v.fichier), { method: 'DELETE' });
                        _stVidStatus('Vidéo supprimée.');
                        _stChargerBiblioVideo();
                    } catch (e) { _stVidStatus('Erreur : ' + e.message); }
                });
                barre.appendChild(sup);
                bloc.appendChild(barre);
                box.appendChild(bloc);
            });
        } catch (e) { _stVidStatus('Bibliothèque indisponible : ' + e.message); }
    }

    document.getElementById('studio-video-refresh')?.addEventListener('click', function () {
        _stVidStatus('Rafraîchissement…');
        _stChargerBiblioVideo().then(function () { _stVidStatus('Bibliothèque à jour.'); });
    });

    // Le studio s'ouvre depuis le menu « + » — là où se prennent déjà les
    // décisions « je crée quelque chose » — et non plus depuis la barre du haut,
    // qui comptait trois portes pour deux idées. Exposé aussi en global pour que
    // le raccourci clavier n'ait pas à connaître le menu.
    function _ouvrirStudio() {
        document.getElementById('plus-menu')?.classList.add('hidden');
        document.getElementById('studio-modal')?.classList.remove('hidden');
        _stChargerImage();
        _stChargerVideo();
        _stChargerBiblioVideo();
        _stReprendre();
        setTimeout(function () { document.getElementById('studio-image-prompt')?.focus(); }, 60);
    }
    window._ouvrirStudio = _ouvrirStudio;
    document.getElementById('plus-studio')?.addEventListener('click', _ouvrirStudio);
    document.getElementById('studio-close')?.addEventListener('click', function () {
        document.getElementById('studio-modal')?.classList.add('hidden');
    });
    document.getElementById('studio-modal')?.addEventListener('click', function (e) {
        if (e.target === this) this.classList.add('hidden');
    });
})();

// ══════════════════════════════════════════
// JOURNAL TECHNIQUE — la sortie du serveur, rendue lisible
// ══════════════════════════════════════════
// NIMM démarre en fenêtre cachée : sa sortie technique était perdue, et de
// toute façon inaccessible au lecteur d'écran. Elle est désormais écrite dans
// un fichier, et affichée ici dans une zone de texte : navigable ligne à ligne,
// sélectionnable, copiable. Le filtre évite d'avoir à parcourir le démarrage.
(function () {
    function _jtMsg(m) {
        var el = document.getElementById('journal-technique-msg');
        if (el) el.textContent = m;
    }

    async function _jtCharger(annoncer) {
        var zone = document.getElementById('journal-technique-texte');
        if (!zone) return;
        var filtre = (document.getElementById('journal-filtre')?.value || '').trim();
        try {
            var url = '/api/journal-technique?lignes=200'
                + (filtre ? '&filtre=' + encodeURIComponent(filtre) : '');
            var d = await fetch(url).then(function (r) { return r.json(); });
            if (d.note) { zone.value = ''; _jtMsg(d.note); return; }
            var lignes = d.lignes || [];
            zone.value = lignes.join(String.fromCharCode(10));
            if (annoncer !== false) {
                _jtMsg(lignes.length + ' ligne' + (lignes.length > 1 ? 's' : '')
                    + (filtre ? ' contenant « ' + filtre + ' »' : '')
                    + (d.total ? ' sur ' + d.total + ' au total.' : '.'));
            }
        } catch (e) { _jtMsg('Journal indisponible : ' + e.message); }
    }

    document.getElementById('journal-charger-btn')?.addEventListener('click', function () {
        _jtMsg('Lecture…');
        _jtCharger(true);
    });
    document.getElementById('journal-filtre')?.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); _jtCharger(true); }
    });
    document.getElementById('journal-technique-details')?.addEventListener('toggle', function () {
        if (this.open) _jtCharger(true);
    });

    document.getElementById('journal-copier-btn')?.addEventListener('click', async function () {
        var zone = document.getElementById('journal-technique-texte');
        if (!zone || !zone.value.trim()) { _jtMsg('Rien à copier : affiche d\'abord le journal.'); return; }
        try {
            await navigator.clipboard.writeText(zone.value);
            _jtMsg('Journal copié dans le presse-papiers.');
        } catch (e) {
            zone.focus(); zone.select();
            _jtMsg('Journal sélectionné : fais Contrôle C pour le copier.');
        }
    });
})();

// ══════════════════════════════════════════════════════════════════════
// CONVERSATION LIVE — parler à NIMM, et pouvoir le couper
// ══════════════════════════════════════════════════════════════════════
//
// CE QUI A ÉTÉ TRANCHÉ ICI, ET POURQUOI
//
// 1. La transcription ne s'annonce PAS toute seule.
//    Un aria-live sur la transcription ferait lire chaque bribe par le lecteur
//    d'écran PENDANT que NIMM parle. Deux voix simultanées, et plus rien de
//    compréhensible. Seul l'état — qui a la parole — est annoncé : c'est court,
//    et ça se glisse entre deux phrases. La transcription, elle, vit dans un
//    champ de texte qu'on parcourt, relit et copie quand on veut, au braille,
//    sans un mot de synthèse.
//
// 2. Le son sortant est joué dans un contexte audio SÉPARÉ du micro.
//    L'entrée est à 16 kHz, la sortie à 24 kHz : ce sont deux horloges. Les
//    mélanger obligerait à rééchantillonner à la main, avec le grésillement
//    qui va avec.
//
// 3. Couper la parole vide la file de lecture, ne la met pas en pause.
//    Une pause laisserait la fin d'une phrase déjà annulée repartir plus tard,
//    hors contexte. On jette.
//
// 4. Rien n'est écrit tant qu'on n'a pas dit oui.
//    La transcription reste en mémoire du navigateur. Elle ne touche le disque
//    qu'après une question explicite, au raccroché.

let _liveWS        = null;   // passerelle vers le serveur
let _liveMicCtx    = null;   // contexte audio d'ENTRÉE (16 kHz)
let _liveOutCtx    = null;   // contexte audio de SORTIE (24 kHz)
let _liveFlux      = null;   // MediaStream du micro
let _liveNoeud     = null;   // noeud de capture
let _liveSources   = [];     // morceaux de son programmés, pour pouvoir les jeter
let _liveProchain  = 0;      // horloge de lecture
let _liveTours     = [];     // transcription accumulée, en mémoire seulement
let _liveMicCoupe  = false;
let _liveActif     = false;
let _liveMoteur    = 'gemini';
let _liveFocusAvant = null;
let _liveFilEphemere = null; // moteur « chaîne » : fil fantôme, détruit à la fin
let _liveDernierQui  = '';

const LIVE_TAUX_ENTREE = 16000;
const LIVE_TAUX_SORTIE = 24000;

function _liveEtat(texte) {
    const el = document.getElementById('live-etat');
    if (el && el.textContent !== texte) el.textContent = texte;
}

/**
 * Ajoute du texte à la transcription.
 * Les bribes successives du même locuteur sont RECOLLÉES sur la même ligne :
 * la Live API envoie la transcription par morceaux, parfois mot à mot. Une
 * ligne par mot rendrait la relecture au braille inutilisable.
 */
function _liveTranscrire(qui, texte) {
    if (!texte) return;
    const zone = document.getElementById('live-transcript');
    const etiquette = qui === 'moi' ? 'Moi' : 'NIMM';
    if (qui === _liveDernierQui && _liveTours.length) {
        _liveTours[_liveTours.length - 1].texte += texte;
    } else {
        _liveTours.push({ qui, texte });
        _liveDernierQui = qui;
    }
    if (zone) {
        zone.value = _liveTours
            .map(t => t.qui === 'moi'  ? 'Moi : ' + t.texte.trim()
                    : t.qui === 'nimm' ? 'NIMM : ' + t.texte.trim()
                    : '[' + t.texte.trim() + ']')
            .join('\n\n');
        // Ne pas déplacer le curseur si l'utilisateur est en train de relire :
        // il perdrait sa place à chaque mot reçu.
        if (document.activeElement !== zone) zone.scrollTop = zone.scrollHeight;
    }
    void etiquette;
}

// ── Les outils de NIMM pendant une conversation Live ─────────────────────
//
// POURQUOI CE NOMMAGE EN FRANÇAIS
// Le nom technique d'un outil (`search_acceslibre`, `get_jours_feries`) ne
// veut rien dire à l'oreille, et encore moins au braille au milieu d'une
// conversation. On annonce ce que NIMM FAIT, pas comment ça s'appelle dans
// le code. Un outil inconnu de cette table reste annoncé sous son nom brut
// plutôt que passé sous silence : mieux vaut une étiquette laide qu'un
// silence inexpliqué pendant que NIMM se tait.
const LIVE_NOMS_OUTILS = {
    search_memory:       'sa mémoire',
    search_bibliotheque: 'les conversations archivées',
    search_anecdotes:    'tes anecdotes',
    search_web:          'le web',
    search_documents:    'ta base de connaissances',
    search_carnet:       'le carnet de bord',
    find_skill:          'ses méthodes enregistrées',
    search_acceslibre:   'l’accessibilité des lieux',
    search_food_product: 'la base des produits alimentaires',
    search_recipe:       'des recettes',
    get_weather:         'la météo',
    get_jours_feries:    'les jours fériés',
    get_exchange_rate:   'les taux de change',
    geocode_address:     'une adresse',
    extract_url_content: 'une page web',
    lookup_book:         'un livre',
    get_country_info:    'des informations sur un pays',
    search_commune:      'une commune',
    search_wikipedia:    'Wikipédia',
    search_wikidata:     'Wikidata',
    search_sirene:       'le registre des entreprises',
    search_datagouv:     'les données publiques',
    describe_image:      'une image',
};

function _liveNomOutil(nom) {
    return LIVE_NOMS_OUTILS[nom] || nom;
}

/**
 * Trace un passage par un outil dans la transcription.
 * Écrit sur SA propre ligne, entre crochets, et ne se recolle jamais à la
 * parole : en relisant au braille, on doit pouvoir distinguer d'un coup ce
 * que NIMM a DIT de ce qu'il est allé CHERCHER.
 */
function _liveNoterOutil(texte) {
    _liveTours.push({ qui: 'outil', texte: texte });
    _liveDernierQui = 'outil';
    const zone = document.getElementById('live-transcript');
    if (!zone) return;
    zone.value = _liveTours
        .map(t => t.qui === 'moi'   ? 'Moi : ' + t.texte.trim()
                : t.qui === 'nimm'  ? 'NIMM : ' + t.texte.trim()
                : '[' + t.texte.trim() + ']')
        .join('\n\n');
    if (document.activeElement !== zone) zone.scrollTop = zone.scrollHeight;
}

// ── Conversion des formats audio ─────────────────────────────────────────
function _liveVersPCM16(float32) {
    const out = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
        // Bornage avant conversion : au-delà de 1 le repliage produit un
        // craquement très audible, et le modèle entend mal.
        const v = Math.max(-1, Math.min(1, float32[i]));
        out[i] = v < 0 ? v * 0x8000 : v * 0x7FFF;
    }
    return out;
}

function _liveVersBase64(int16) {
    const octets = new Uint8Array(int16.buffer);
    let s = '';
    // Par tranches : String.fromCharCode sur un tableau de 100 000 éléments
    // dépasse la pile d'appels du navigateur.
    const pas = 0x8000;
    for (let i = 0; i < octets.length; i += pas) {
        s += String.fromCharCode.apply(null, octets.subarray(i, i + pas));
    }
    return btoa(s);
}

function _liveDeBase64(b64) {
    const bin = atob(b64);
    const octets = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) octets[i] = bin.charCodeAt(i);
    return new Int16Array(octets.buffer);
}

// ── Lecture du son reçu ──────────────────────────────────────────────────
function _liveJouer(b64) {
    if (!_liveOutCtx) return;
    let pcm;
    try { pcm = _liveDeBase64(b64); } catch (e) { return; }
    if (!pcm.length) return;
    const buf = _liveOutCtx.createBuffer(1, pcm.length, LIVE_TAUX_SORTIE);
    const canal = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) canal[i] = pcm[i] / 0x8000;
    const src = _liveOutCtx.createBufferSource();
    src.buffer = buf;
    src.connect(_liveOutCtx.destination);
    // Les morceaux arrivent plus vite qu'ils ne se jouent : on les met bout à
    // bout sur une horloge, sinon ils se superposeraient tous à l'instant zéro.
    const maintenant = _liveOutCtx.currentTime;
    if (_liveProchain < maintenant) _liveProchain = maintenant + 0.02;
    src.start(_liveProchain);
    _liveProchain += buf.duration;
    _liveSources.push(src);
    src.onended = () => {
        const i = _liveSources.indexOf(src);
        if (i >= 0) _liveSources.splice(i, 1);
    };
}

function _liveViderLecture() {
    // On JETTE, on ne met pas en pause : reprendre plus tard la fin d'une
    // phrase que l'on a coupée n'aurait aucun sens dans un dialogue.
    _liveSources.forEach(s => { try { s.stop(); } catch (e) {} });
    _liveSources = [];
    _liveProchain = _liveOutCtx ? _liveOutCtx.currentTime : 0;
}

// ── Capture du micro ─────────────────────────────────────────────────────
const _LIVE_WORKLET = `
class CaptureNimm extends AudioWorkletProcessor {
  process(entrees) {
    const c = entrees[0] && entrees[0][0];
    if (c && c.length) this.port.postMessage(new Float32Array(c));
    return true;
  }
}
registerProcessor('capture-nimm', CaptureNimm);
`;

async function _liveDemarrerMicro(surMorceau) {
    _liveFlux = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            echoCancellation: true,   // sans elle, NIMM s'entend parler et se coupe lui-même
            noiseSuppression: true,
            autoGainControl: true,
        }
    });
    _liveMicCtx = new (window.AudioContext || window.webkitAudioContext)(
        { sampleRate: LIVE_TAUX_ENTREE });
    const source = _liveMicCtx.createMediaStreamSource(_liveFlux);

    try {
        // AudioWorklet chargé depuis une URL de données : NIMM tient en un
        // seul fichier de script, on ne va pas en ajouter un pour douze lignes.
        const url = URL.createObjectURL(new Blob([_LIVE_WORKLET],
                                                { type: 'application/javascript' }));
        await _liveMicCtx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        _liveNoeud = new AudioWorkletNode(_liveMicCtx, 'capture-nimm');
        _liveNoeud.port.onmessage = (e) => surMorceau(e.data);
        source.connect(_liveNoeud);
        // Le worklet ne produit pas de son : on le relie quand même à la
        // sortie, sinon certains navigateurs suspendent le graphe.
        _liveNoeud.connect(_liveMicCtx.destination);
    } catch (e) {
        // Repli sur l'ancien procédé, déprécié mais universel. Mieux vaut un
        // avertissement dans la console qu'un micro qui ne marche pas.
        console.warn('[LIVE] AudioWorklet indisponible, repli ScriptProcessor :', e);
        _liveNoeud = _liveMicCtx.createScriptProcessor(4096, 1, 1);
        _liveNoeud.onaudioprocess = (ev) => {
            surMorceau(new Float32Array(ev.inputBuffer.getChannelData(0)));
        };
        source.connect(_liveNoeud);
        _liveNoeud.connect(_liveMicCtx.destination);
    }
}

function _liveArreterMicro() {
    try { if (_liveNoeud) _liveNoeud.disconnect(); } catch (e) {}
    try { if (_liveFlux) _liveFlux.getTracks().forEach(t => t.stop()); } catch (e) {}
    try { if (_liveMicCtx) _liveMicCtx.close(); } catch (e) {}
    _liveNoeud = null; _liveFlux = null; _liveMicCtx = null;
}

// ── Moteur 1 : Gemini Live (vrai dialogue) ───────────────────────────────
async function _liveGemini(reglages) {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    _liveWS = new WebSocket(`${proto}//${location.host}/api/live/ws`);

    _liveWS.onopen = () => {
        _liveWS.send(JSON.stringify({ demarrer: reglages }));
    };

    _liveWS.onmessage = async (ev) => {
        let evt;
        try { evt = JSON.parse(ev.data); } catch (e) { return; }
        switch (evt.type) {
            case 'connectee':
                _liveOutCtx = new (window.AudioContext || window.webkitAudioContext)(
                    { sampleRate: LIVE_TAUX_SORTIE });
                _liveProchain = 0;
                try {
                    await _liveDemarrerMicro((f32) => {
                        if (_liveMicCoupe || !_liveWS || _liveWS.readyState !== 1) return;
                        _liveWS.send(JSON.stringify(
                            { audio: _liveVersBase64(_liveVersPCM16(f32)) }));
                    });
                } catch (e) {
                    _liveEtat('Micro refusé : ' + e.message);
                    _liveTranscrire('nimm',
                        '[Le micro n’a pas pu être ouvert : ' + e.message +
                        '. Tu peux quand même écrire dans le champ ci-dessous.]');
                    return;
                }
                _liveEtat('À toi de parler.');
                break;
            case 'prete':
                break;
            case 'audio':
                _liveEtat('NIMM parle — coupe-le quand tu veux.');
                _liveJouer(evt.donnees);
                break;
            case 'transcription':
                _liveTranscrire(evt.qui, evt.texte);
                break;
            case 'interrompu':
                _liveViderLecture();
                _liveEtat('Tu as coupé NIMM. À toi.');
                break;
            case 'tour_fini':
                _liveEtat('À toi de parler.');
                break;
            case 'bientot_fini':
                _liveEtat('La session va se fermer côté serveur.');
                break;
            case 'outil': {
                // Annoncé dans l'état ET écrit dans la transcription : sans
                // cela, NIMM se tait pendant une à deux secondes sans qu'on
                // sache pourquoi — et un silence inexpliqué dans une
                // conversation vocale ressemble à une panne.
                const _q = _liveNomOutil(evt.nom);
                _liveEtat('NIMM consulte ' + _q + '\u2026');
                _liveNoterOutil('NIMM consulte ' + _q);
                break;
            }
            case 'outil_fini':
                _liveEtat('NIMM a ce qu\u2019il cherchait. Il r\u00e9pond.');
                break;
            case 'outil_annule':
            case 'outil_abandonne':
                // On a coupé NIMM pendant qu'il cherchait : le dire, sinon le
                // silence passerait pour un outil en panne.
                _liveNoterOutil('Recherche abandonn\u00e9e : tu as repris la parole');
                _liveEtat('\u00c0 toi de parler.');
                break;
            case 'erreur':
                _liveEtat('Incident : ' + (evt.texte || ''));
                _liveTranscrire('nimm', '[' + (evt.texte || 'incident') + ']');
                break;
        }
    };

    _liveWS.onerror = () => { _liveEtat('La liaison vocale a échoué.'); };
    _liveWS.onclose  = () => {
        if (_liveActif) _liveEtat('Liaison fermée. Tu peux raccrocher.');
    };
}

// ── Moteur 2 : Whisper + ton LLM + voix NIMM (le repli) ──────────────────
//
// Il n'atteint PAS la fluidité du premier, et le dire est plus utile que de
// le laisser croire : chaque tour attend la fin du précédent. Il existe pour
// que quelqu'un sans clé Gemini puisse tout de même parler à NIMM.
let _liveRec = null, _liveAnalyse = null, _liveAudioTTS = null;

async function _liveChaine() {
    // Un fil fantôme sert de support : il n'enregistre aucun message (c'est
    // la définition du mode fantôme), et il est détruit au raccroché.
    try {
        const r = await fetch('/api/threads', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: '🎙️ Live', mode: 'chat', ghost: true })
        });
        _liveFilEphemere = (await r.json()).thread_id;
    } catch (e) {
        _liveEtat('Impossible de préparer la session : ' + e.message);
        return;
    }

    _liveFlux = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true }
    });
    _liveMicCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = _liveMicCtx.createMediaStreamSource(_liveFlux);
    _liveAnalyse = _liveMicCtx.createAnalyser();
    _liveAnalyse.fftSize = 512;
    src.connect(_liveAnalyse);

    _liveEtat('À toi de parler.');
    _liveChaineTour();
}

function _liveNiveau() {
    if (!_liveAnalyse) return 0;
    const buf = new Uint8Array(_liveAnalyse.fftSize);
    _liveAnalyse.getByteTimeDomainData(buf);
    let somme = 0;
    for (let i = 0; i < buf.length; i++) {
        const v = (buf[i] - 128) / 128;
        somme += v * v;
    }
    return Math.sqrt(somme / buf.length);
}

async function _liveChaineTour() {
    if (!_liveActif || _liveMoteur !== 'chaine') return;
    const morceaux = [];
    _liveRec = new MediaRecorder(_liveFlux);
    _liveRec.ondataavailable = (e) => { if (e.data.size) morceaux.push(e.data); };

    let aParle = false, silence = 0;
    const SEUIL = 0.02, SILENCE_MAX = 900;   // ~0,9 s de silence = fin de tour
    _liveRec.start(200);

    await new Promise(resolve => {
        const tic = setInterval(() => {
            if (!_liveActif) { clearInterval(tic); resolve(); return; }
            if (_liveMicCoupe) { silence = 0; return; }
            const n = _liveNiveau();
            if (n > SEUIL) {
                aParle = true; silence = 0;
                // Barge-in approximatif : si NIMM parle et qu'on se met à
                // parler, on le coupe. Approximatif parce qu'il faut d'abord
                // détecter la voix — un vrai dialogue coupe plus tôt.
                if (_liveAudioTTS && !_liveAudioTTS.paused) {
                    try { _liveAudioTTS.pause(); } catch (e) {}
                    _liveEtat('Tu as coupé NIMM. À toi.');
                }
            } else if (aParle) {
                silence += 120;
                if (silence >= SILENCE_MAX) { clearInterval(tic); resolve(); }
            }
        }, 120);
    });

    try { _liveRec.stop(); } catch (e) {}
    if (!_liveActif || !aParle) { if (_liveActif) _liveChaineTour(); return; }

    _liveEtat('NIMM écoute et réfléchit…');
    await new Promise(r => setTimeout(r, 250));   // laisse le dernier morceau arriver

    let texte = '';
    try {
        const fd = new FormData();
        fd.append('file', new Blob(morceaux, { type: 'audio/webm' }), 'live.webm');
        if (_liveFilEphemere) fd.append('thread_id', _liveFilEphemere);
        const r = await fetch('/api/stt/transcribe', { method: 'POST', body: fd });
        texte = ((await r.json()).text || '').trim();
    } catch (e) { texte = ''; }

    if (!texte) { _liveEtat('Je n’ai rien compris. Reprends.'); _liveChaineTour(); return; }
    _liveTranscrire('moi', texte);

    let reponse = '';
    try {
        const r = await fetch('/api/chat/stream', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: texte, thread_id: _liveFilEphemere })
        });
        const lecteur = r.body.getReader();
        const dec = new TextDecoder();
        let tampon = '';
        while (true) {
            const { done, value } = await lecteur.read();
            if (done) break;
            tampon += dec.decode(value, { stream: true });
            const lignes = tampon.split('\n');
            tampon = lignes.pop();
            for (const l of lignes) {
                if (l.startsWith('data: ')) reponse += l.slice(6);
            }
        }
    } catch (e) { reponse = 'Je n’ai pas pu répondre : ' + e.message; }

    reponse = (reponse || '').trim();
    if (!reponse) { _liveEtat('Pas de réponse. Reprends.'); _liveChaineTour(); return; }
    _liveTranscrire('nimm', reponse);

    _liveEtat('NIMM parle — coupe-le quand tu veux.');
    try {
        const rv = await fetch('/api/tts/speak', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: reponse.slice(0, 4000),
                                   voice: localStorage.getItem('nimm-voice') || '' })
        });
        const blob = await rv.blob();
        _liveAudioTTS = new Audio(URL.createObjectURL(blob));
        await new Promise(res => {
            _liveAudioTTS.onended = res;
            _liveAudioTTS.onpause = res;     // coupé par la voix : on enchaîne
            _liveAudioTTS.onerror = res;
            _liveAudioTTS.play().catch(res);
        });
    } catch (e) { /* la transcription reste lisible : on continue */ }

    if (_liveActif) { _liveEtat('À toi de parler.'); _liveChaineTour(); }
}

// ── Lancement, arrêt, conservation ───────────────────────────────────────
async function _liveLancer(moteur, voix) {
    _liveMoteur = moteur;
    _liveActif  = true;
    _liveMicCoupe = false;
    _liveTours = [];
    _liveDernierQui = '';
    const zone = document.getElementById('live-transcript');
    if (zone) zone.value = '';
    _liveFocusAvant = document.activeElement;

    document.getElementById('live-panel')?.classList.remove('hidden');
    _liveEtat('Connexion…');
    document.getElementById('live-voix-row').style.display =
        moteur === 'gemini' ? '' : 'none';
    setTimeout(() => { document.getElementById('live-raccrocher')?.focus(); }, 60);

    try {
        if (moteur === 'gemini') {
            // « Il te connaît, mais n'écrit rien » : NIMM part avec la mémoire
            // longue et le prénom, et ne consigne rien de l'échange.
            await _liveGemini({ voix, se_souvient: true, langue: 'fr-FR',
                                interruption: true });
        } else {
            await _liveChaine();
        }
    } catch (e) {
        _liveEtat('Impossible de démarrer : ' + e.message);
    }
}

async function _liveRaccrocher() {
    if (!_liveActif) return;
    _liveActif = false;
    _liveEtat('Terminé.');

    try { if (_liveWS && _liveWS.readyState === 1) _liveWS.send(JSON.stringify({ raccrocher: true })); } catch (e) {}
    try { if (_liveWS) _liveWS.close(); } catch (e) {}
    _liveWS = null;
    try { if (_liveAudioTTS) _liveAudioTTS.pause(); } catch (e) {}
    try { if (_liveRec && _liveRec.state !== 'inactive') _liveRec.stop(); } catch (e) {}
    _liveViderLecture();
    try { if (_liveOutCtx) _liveOutCtx.close(); } catch (e) {}
    _liveOutCtx = null;
    _liveArreterMicro();

    // Le fil support du moteur « chaîne » n'a servi qu'à faire transiter les
    // messages : il n'en a conservé aucun (mode fantôme), et il disparaît.
    if (_liveFilEphemere) {
        fetch(`/api/threads/${_liveFilEphemere}`, { method: 'DELETE' }).catch(() => {});
        _liveFilEphemere = null;
    }

    const utiles = _liveTours.filter(t => (t.texte || '').trim());
    document.getElementById('live-panel')?.classList.add('hidden');

    if (utiles.length) {
        // La question est posée UNE fois, à la fin, et le défaut est de ne
        // rien garder : une session Live est éphémère par construction.
        // La modale de NIMM plutôt que confirm() : elle gère le focus et se
        // lit comme le reste de l'interface.
        const garder = await confirmModal(
            'Conversation termin\u00e9e (' + utiles.length + ' prise' +
            (utiles.length > 1 ? 's' : '') + ' de parole). '
            + 'Conserver la transcription comme fil normal ? '
            + 'Annuler : rien n\u2019est gard\u00e9.');
        if (garder) {
            try {
                const r = await fetch('/api/live/conserver', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tours: utiles })
                });
                const d = await r.json();
                if (d.thread_id) {
                    await loadThreads();
                    await selectThread(d.thread_id);
                    if (typeof _notify === 'function') _notify('Transcription conservée.', 'ok');
                }
            } catch (e) {
                if (typeof _notify === 'function') _notify('Conservation impossible : ' + e.message, 'error');
            }
        }
    }
    _liveTours = [];
    setTimeout(() => { _liveFocusAvant?.focus(); }, 0);
}

// ── Modale de lancement ──────────────────────────────────────────────────
async function _liveOuvrirModale() {
    const modal = document.getElementById('live-modal');
    if (!modal) return;
    let o = {};
    try { o = await (await fetch('/api/live/options')).json(); } catch (e) { o = {}; }

    const selMoteur = document.getElementById('live-moteur');
    const selVoix   = document.getElementById('live-voix');
    const aide      = document.getElementById('live-moteur-aide');
    const rangVoix  = document.getElementById('live-voix-row');
    const caseOutils = document.getElementById('live-outils');
    const aideOutils = document.getElementById('live-outils-aide');
    if (caseOutils) caseOutils.checked = o.outils !== false;
    if (aideOutils) aideOutils.textContent = o.outils_note || '';

    selMoteur.innerHTML = (o.moteurs || []).map(m =>
        `<option value="${m.nom}"${m.ouvert ? '' : ' disabled'}>` +
        `${m.libelle}${m.ouvert ? '' : ' — indisponible'}</option>`).join('');
    selMoteur.value = o.moteur_defaut || 'chaine';

    selVoix.innerHTML = (o.voix || []).map(v =>
        `<option value="${v.nom}">${v.libelle}</option>`).join('');
    if (o.voix_enregistree) selVoix.value = o.voix_enregistree;

    const majAide = () => {
        const m = (o.moteurs || []).find(x => x.nom === selMoteur.value);
        aide.textContent = m ? m.description : '';
        rangVoix.style.display = selMoteur.value === 'gemini' ? '' : 'none';
        // Les outils ne se déclarent que dans la session Gemini Live ; le
        // repli Whisper passe par le chat de NIMM, qui les a déjà tous.
        const _ro = caseOutils ? caseOutils.closest('div') : null;
        if (_ro) _ro.style.display = selMoteur.value === 'gemini' ? '' : 'none';
    };
    selMoteur.onchange = majAide;
    majAide();

    const prevFocus = document.activeElement;
    modal.classList.remove('hidden');
    setTimeout(() => selMoteur.focus(), 50);

    const fermer = () => {
        modal.classList.add('hidden');
        setTimeout(() => prevFocus?.focus(), 0);
    };
    document.getElementById('live-cancel').onclick = fermer;
    document.getElementById('live-start').onclick = async () => {
        const moteur = selMoteur.value, voix = selVoix.value;
        // On ATTEND l'enregistrement avant d'ouvrir la session : le serveur
        // lit ces réglages au moment de configurer la session Live, et une
        // requête lancée sans attendre arrivait parfois après. La case
        // « outils » aurait alors été sans effet une fois sur deux.
        try {
            await fetch('/api/live/options', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ moteur, voix,
                                       outils: caseOutils ? caseOutils.checked : true })
            });
        } catch (e) { /* réglage non retenu : la session s'ouvre quand même */ }
        modal.classList.add('hidden');
        await _liveLancer(moteur, voix);
    };
}

// ── Le bouton, à la place laissée par le mode fantôme ────────────────────
(function setupLiveToggle() {
    const btn = document.createElement('button');
    btn.id        = 'live-toggle';
    btn.className = 'topbar-icon-btn';
    btn.innerHTML = '<span aria-hidden="true">🎙️</span>';
    btn.title     = 'Conversation Live (Alt+Maj+K) — parler à NIMM, rien n\'est conservé';
    btn.setAttribute('aria-label',
        'Conversation Live : parler à NIMM et pouvoir le couper. Rien n\'est conservé. Alt+Maj+K.');
    btn.setAttribute('aria-keyshortcuts', 'Alt+Shift+K');
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.addEventListener('click', () => {
        if (_liveActif) { _liveRaccrocher(); return; }
        _liveOuvrirModale();
    });
    const topRight = document.getElementById('top-right');
    if (topRight) topRight.insertBefore(btn, topRight.firstChild);

    // Pas de DOMContentLoaded ici : app.js est chargé à la fin du corps de la
    // page, donc l'événement est DÉJÀ passé quand ce code s'exécute — les
    // gestionnaires ne se seraient jamais installés. On câble tout de suite,
    // en se contentant d'attendre si, par exception, la page est encore
    // en cours d'analyse.
    const _liveCabler = () => {
        document.getElementById('live-raccrocher')?.addEventListener('click', _liveRaccrocher);

        const micBtn = document.getElementById('live-micro');
        micBtn?.addEventListener('click', () => {
            _liveMicCoupe = !_liveMicCoupe;
            micBtn.setAttribute('aria-pressed', _liveMicCoupe ? 'true' : 'false');
            micBtn.textContent = _liveMicCoupe ? '🎤 Rouvrir le micro' : '🎤 Couper le micro';
            _liveEtat(_liveMicCoupe ? 'Micro coupé — NIMM ne t’entend plus.'
                                    : 'Micro ouvert. À toi de parler.');
            if (_liveMicCoupe && _liveWS && _liveWS.readyState === 1) {
                try { _liveWS.send(JSON.stringify({ fin_audio: true })); } catch (e) {}
            }
        });

        const champ = document.getElementById('live-ecrire');
        champ?.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            const t = champ.value.trim();
            if (!t) return;
            e.preventDefault();
            champ.value = '';
            _liveTranscrire('moi', t);
            if (_liveMoteur === 'gemini' && _liveWS && _liveWS.readyState === 1) {
                _liveWS.send(JSON.stringify({ texte: t }));
                _liveEtat('Envoyé. NIMM répond.');
            } else {
                _liveEtat('L’envoi de texte n’est possible qu’avec Gemini Live.');
            }
        });
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _liveCabler, { once: true });
    } else {
        _liveCabler();
    }
})();

// Échap raccroche, et Alt+M coupe le micro : au clavier, on doit pouvoir
// sortir d'une conversation vocale sans chercher un bouton.
document.addEventListener('keydown', (e) => {
    if (!_liveActif) return;
    if (e.key === 'Escape') { e.preventDefault(); _liveRaccrocher(); }
    else if (e.altKey && (e.key === 'm' || e.key === 'M')) {
        e.preventDefault();
        document.getElementById('live-micro')?.click();
    }
});

// ══════════════════════════════════════════════════════════════════════
// MANIPULER UNE IMAGE — dire ce qu'on veut, savoir qui l'a fait
// ══════════════════════════════════════════════════════════════════════
//
// LE PRINCIPE, ET IL EST TOUT DANS LE COMPTE RENDU
// On ne voit pas le résultat. Ce qui compte, ce n'est donc pas l'image : c'est
// la phrase qui dit ce qu'elle est devenue. Le panneau en produit trois :
//   1. la VOIE — découpée sur ta machine, ou redessinée par un modèle ;
//   2. le JOURNAL — les opérations réelles, dimensions et poids compris ;
//   3. la DESCRIPTION — ce que NIMM voit dans l'image obtenue, pas ce qu'on
//      avait demandé.
// Les trois vivent dans un champ de texte copiable, parce qu'on doit pouvoir
// les relire au braille et les coller ailleurs.

(function () {
    let _retoucheOptions = null;
    let _retoucheResultat = null;   // {b64, mime} — pour repartir du résultat

    const $ = (id) => document.getElementById(id);

    function _retoucheEtat(texte) {
        const el = $('studio-retouche-status');
        if (el) el.textContent = texte;
    }

    /** Écrit le compte rendu, dans l'ordre où on veut le lire. */
    function _retoucheCompteRendu(d) {
        const lignes = [];
        if (d.voie === 'local') {
            lignes.push('Retouche EXACTE, faite sur ta machine.');
        } else if (d.voie === 'modele') {
            lignes.push('Image REDESSINÉE par le modèle : tous les pixels ont changé.');
        }
        if (d.raison) lignes.push(d.raison);
        if (d.journal && d.journal.length) {
            lignes.push('');
            lignes.push('Ce qui a été fait :');
            d.journal.forEach(l => lignes.push('- ' + l));
        }
        if (d.commentaire) {
            lignes.push('');
            lignes.push('Commentaire du modèle : ' + d.commentaire);
        }
        if (d.description) {
            lignes.push('');
            lignes.push('Ce que contient l’image obtenue :');
            lignes.push(d.description);
        } else if (d.image) {
            // Le dire plutôt que de laisser croire à un oubli. C'est la règle
            // de l'alternative honnête : une description absente s'annonce.
            lignes.push('');
            lignes.push('Aucune description disponible pour cette image.');
        }
        const zone = $('studio-retouche-compte-rendu');
        if (zone) zone.value = lignes.join('\n');
    }

    /** Annonce la voie AVANT de lancer : on doit savoir à quoi s'attendre. */
    let _minuteurVoie = null;
    function _retoucheAnnoncerVoie() {
        clearTimeout(_minuteurVoie);
        _minuteurVoie = setTimeout(async () => {
            const consigne = ($('studio-retouche-consigne')?.value || '').trim();
            const el = $('studio-retouche-voie');
            if (!el) return;
            if (!consigne) { el.textContent = ''; return; }
            try {
                const r = await fetch('/api/retouche/analyser', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ consigne })
                });
                const d = await r.json();
                el.textContent = (d.voie === 'local'
                    ? '✓ Retouche exacte, sur ta machine. '
                    : '↗ Retouche réinventée par le modèle. ') + (d.raison || '');
            } catch (e) { el.textContent = ''; }
        }, 500);   // on laisse finir la phrase avant de la juger
    }

    async function _retoucheAppliquer() {
        const champ = $('studio-retouche-fichier');
        const consigne = ($('studio-retouche-consigne')?.value || '').trim();
        if (!consigne) { _retoucheEtat('Dis d’abord ce que tu veux changer.'); return; }

        const fd = new FormData();
        if (_retoucheResultat && champ && !champ.files.length) {
            // Reprise : on repart du résultat précédent, pas de l'original.
            // Enchaîner sur l'original referait la retouche à zéro, et
            // « encore un peu plus » n'aurait aucun sens.
            const bin = atob(_retoucheResultat.b64);
            const oct = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) oct[i] = bin.charCodeAt(i);
            fd.append('file', new Blob([oct], { type: _retoucheResultat.mime }),
                      'reprise.png');
        } else if (champ && champ.files.length) {
            fd.append('file', champ.files[0], champ.files[0].name);
        } else {
            _retoucheEtat('Choisis d’abord une image.');
            return;
        }
        fd.append('consigne', consigne);
        fd.append('decrire', $('studio-retouche-decrire')?.checked ? 'true' : 'false');

        const btn = $('studio-retouche-btn');
        if (btn) btn.disabled = true;
        _retoucheEtat('Travail en cours…');
        try {
            const r = await fetch('/api/retouche/appliquer', { method: 'POST', body: fd });
            const d = await r.json();
            if (d.erreur) {
                _retoucheEtat('Échec : ' + d.erreur);
                _retoucheCompteRendu(d);
                return;
            }
            _retoucheResultat = { b64: d.image, mime: d.mime || 'image/png' };
            _retoucheCompteRendu(d);
            _retoucheEtat(d.voie === 'local'
                ? 'Fait, au pixel près. Le compte rendu est ci-dessous.'
                : 'Fait par le modèle. Le compte rendu est ci-dessous.');

            const out = $('studio-retouche-out');
            if (out) {
                out.innerHTML = '';
                const img = document.createElement('img');
                img.src = 'data:' + _retoucheResultat.mime + ';base64,' + d.image;
                // L'alternative dit ce que l'image EST, jamais ce qu'on avait
                // demandé — et quand la description manque, elle le dit.
                img.alt = d.description
                    || 'Image obtenue, sans description disponible.';
                img.style.cssText = 'max-width:100%;border-radius:8px;';
                out.appendChild(img);

                const lien = document.createElement('a');
                lien.href = img.src;
                lien.download = 'nimm_retouche.' +
                    (_retoucheResultat.mime.includes('jpeg') ? 'jpg' : 'png');
                lien.textContent = 'Télécharger l’image obtenue';
                lien.className = 'btn-secondary';
                lien.style.cssText = 'display:inline-block;margin-top:8px;';
                out.appendChild(lien);
            }
            const rep = $('studio-retouche-reprendre');
            if (rep) rep.hidden = false;
        } catch (e) {
            _retoucheEtat('Échec : ' + e.message);
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    function _retoucheCabler() {
        const det = $('studio-retouche-details');
        if (!det) return;

        fetch('/api/retouche/options').then(r => r.json()).then(o => {
            _retoucheOptions = o;
            const note = $('studio-retouche-note');
            if (note) note.textContent = o.note || '';
            const ex = $('studio-retouche-exemples');
            if (ex) {
                const bloc = (titre, liste) =>
                    '<p style="margin:4px 0 2px;font-weight:600;">' + titre + '</p><ul style="margin:0 0 8px 18px;">'
                    + (liste || []).map(s => '<li>' + s + '</li>').join('') + '</ul>';
                ex.innerHTML = bloc('Faites sur ta machine, au pixel près', o.exemples_locaux)
                             + bloc('Confiées au modèle, qui redessine', o.exemples_modele);
            }
        }).catch(() => {});

        $('studio-retouche-consigne')?.addEventListener('input', _retoucheAnnoncerVoie);
        $('studio-retouche-btn')?.addEventListener('click', _retoucheAppliquer);
        $('studio-retouche-fichier')?.addEventListener('change', () => {
            // Une nouvelle image repart de zéro : garder l'ancien résultat en
            // réserve laisserait un doute sur ce qui va être retouché.
            _retoucheResultat = null;
            const rep = $('studio-retouche-reprendre');
            if (rep) rep.hidden = true;
            _retoucheEtat('');
        });
        $('studio-retouche-reprendre')?.addEventListener('click', () => {
            const champ = $('studio-retouche-fichier');
            if (champ) champ.value = '';
            _retoucheEtat('La prochaine retouche partira du résultat précédent.');
            $('studio-retouche-consigne')?.focus();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _retoucheCabler, { once: true });
    } else {
        _retoucheCabler();
    }
})();
