/* Heizplan – Panel "Heizpläne"
 * Räume: was heute gilt und welches Profil an welchem Tag. Profile: Tagesmuster bearbeiten.
 * Daten kommen per Websocket von der Integration heizplan, die Solltemperatur pro Raum
 * aus sensor.heizplan_<kürzel>. Ändern dürfen nur Admins.
 */
(() => {
  const DOMAIN = 'heizplan';
  const WEEK = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const SHORT = { mon: 'Mo', tue: 'Di', wed: 'Mi', thu: 'Do', fri: 'Fr', sat: 'Sa', sun: 'So', free: 'Frei', homeoffice: 'Homeoffice' };
  const SPECIAL = [
    ['free', 'Freier Tag', 'Feiertag, Brückentag oder Urlaub unter der Woche'],
    ['homeoffice', 'Homeoffice', 'Werktag, an dem jemand zu Hause arbeitet'],
  ];
  // Erdtöne für Profile, Reihenfolge = Reihenfolge der Profile
  const PROFILE_COLORS = ['#C2643C', '#7A8B5A', '#C99A3B', '#6F8296', '#9C6B8E', '#8A7560', '#4F8A83', '#B5523B'];

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const errMsg = (e) => (e && (e.message || (e.error && e.error.message) || e.error)) || String(e);
  const deg = (t, unit = true) => (t == null || Number.isNaN(Number(t)) ? '–' : `${Number(t).toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${unit ? ' °C' : '°'}`);
  const short = (t) => `${Number(t).toLocaleString('de-DE', { maximumFractionDigits: 1 })}°`;
  const mins = (at) => { const [h, m] = String(at).split(':').map(Number); return h * 60 + m; };
  const hhmm = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }); };
  const isTomorrow = (iso) => { const d = new Date(iso); const t = new Date(); t.setDate(t.getDate() + 1); return d.toDateString() === t.toDateString(); };
  const ic = (n, cls = '') => `<ha-icon class="${cls}" icon="mdi:${n}"></ha-icon>`;
  const slug = (s) => String(s).toLowerCase().replace(/ä/g, 'a').replace(/ö/g, 'o').replace(/ü/g, 'u').replace(/ß/g, 'ss').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 32);

  // Temperatur -> Farbe: kühl (Blaugrau) über Sand zu warm (Terrakotta)
  const STOPS = [[15, [111, 130, 150]], [18, [201, 176, 128]], [21, [194, 100, 60]], [24, [160, 60, 40]]];
  const tempColor = (t) => {
    const v = Math.max(STOPS[0][0], Math.min(STOPS[STOPS.length - 1][0], Number(t)));
    for (let i = 1; i < STOPS.length; i += 1) {
      const [t1, c1] = STOPS[i]; const [t0, c0] = STOPS[i - 1];
      if (v <= t1) { const f = (v - t0) / (t1 - t0); return `rgb(${c0.map((c, k) => Math.round(c + (c1[k] - c) * f)).join(',')})`; }
    }
    return `rgb(${STOPS[STOPS.length - 1][1].join(',')})`;
  };

  // Tagesbalken: Segmente nach Temperatur, Höhe nach Temperatur, optional Jetzt-Markierung
  const dayBar = (points, { now = null, big = false, mini = false } = {}) => {
    if (!points || !points.length) return '<div class="bar empty-bar">Kein Profil</div>';
    if (mini) {
      return `<span class="mini">${points.map((p, i) => {
        const start = mins(p.at); const end = i + 1 < points.length ? mins(points[i + 1].at) : 1440;
        const h = 25 + Math.max(0, Math.min(1, (p.temp - 15) / 7)) * 75;
        return `<i style="left:${(start / 14.4).toFixed(2)}%;width:${((end - start) / 14.4).toFixed(2)}%;height:${h.toFixed(0)}%;background:${tempColor(p.temp)}"></i>`;
      }).join('')}</span>`;
    }
    const temps = points.map((p) => p.temp);
    const lo = Math.min(...temps, 16); const hi = Math.max(...temps, 21);
    const segs = points.map((p, i) => {
      const start = mins(p.at); const end = i + 1 < points.length ? mins(points[i + 1].at) : 1440;
      const h = 34 + ((p.temp - lo) / Math.max(1, hi - lo)) * 66;
      const label = big && end - start >= 170 ? `<span>${short(p.temp)}</span>` : '';
      return `<div class="seg" style="left:${(start / 14.4).toFixed(3)}%;width:${((end - start) / 14.4).toFixed(3)}%;height:${h.toFixed(1)}%;background:${tempColor(p.temp)}">${label}</div>`;
    }).join('');
    const marker = now == null ? '' : `<div class="now" style="left:${(now / 14.4).toFixed(3)}%"></div>`;
    const ticks = big ? '<div class="ticks"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>' : '';
    return `<div class="bar${big ? ' big' : ''}">${segs}${marker}</div>${ticks}`;
  };

  // "Mo–Fr", "Sa, So" aus einer Liste von Tagen
  const dayRanges = (days) => {
    const idx = WEEK.map((d) => days.includes(d));
    const parts = []; let i = 0;
    while (i < 7) {
      if (!idx[i]) { i += 1; continue; }
      let j = i; while (j + 1 < 7 && idx[j + 1]) j += 1;
      parts.push(j - i >= 2 ? `${SHORT[WEEK[i]]}–${SHORT[WEEK[j]]}` : WEEK.slice(i, j + 1).map((d) => SHORT[d]).join(', '));
      i = j + 1;
    }
    for (const [d] of SPECIAL) if (days.includes(d)) parts.push(SHORT[d]);
    return parts.join(', ');
  };

  const CSS = `
  :host{display:block;min-height:100vh;background:var(--primary-background-color);color:var(--primary-text-color);
    font-family:var(--ha-font-family-body,Roboto,system-ui,sans-serif);
    --acc:var(--primary-color,#C2643C);--bg2:var(--secondary-background-color,#f3f1ec);--card:var(--ha-card-background,var(--card-background-color,#fff));
    --line:var(--divider-color,rgba(127,127,127,.22));--mute:var(--secondary-text-color,#6b6560);--bad:var(--error-color,#b5523b);
    --r:var(--ha-card-border-radius,16px)}
  *{box-sizing:border-box}
  button{font:inherit;color:inherit;cursor:pointer;border:0;background:none;padding:0;-webkit-tap-highlight-color:transparent}
  input,select{font:inherit;color:inherit}
  .top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:4px;height:56px;padding:0 4px;
    background:var(--app-header-background-color,var(--primary-background-color));color:var(--app-header-text-color,var(--primary-text-color));
    border-bottom:1px solid var(--app-header-border-bottom,transparent);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
  .top .t{flex:1;font-size:20px;font-weight:500;padding-left:8px}
  .top button{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;--mdc-icon-size:24px}
  .wrap{max-width:720px;margin:0 auto;padding:12px 16px 110px}
  .seg-ctl{display:flex;background:var(--bg2);border-radius:12px;padding:3px;margin:4px 0 14px}
  .seg-ctl button{flex:1;height:36px;border-radius:10px;font-weight:600;font-size:15px;color:var(--mute)}
  .seg-ctl button.on{background:var(--card);color:var(--primary-text-color);box-shadow:0 1px 3px rgba(0,0,0,.12)}
  .today{display:flex;align-items:center;gap:8px;color:var(--mute);font-size:14px;margin:0 4px 12px;--mdc-icon-size:18px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px;margin-bottom:14px;
    box-shadow:var(--ha-card-box-shadow,0 1px 2px rgba(0,0,0,.04));backdrop-filter:var(--ha-card-backdrop-filter,none);-webkit-backdrop-filter:var(--ha-card-backdrop-filter,none)}
  .rhead{display:flex;align-items:flex-start;gap:10px}
  .rname{flex:1;min-width:0}
  .rname b{display:block;font-size:18px;font-weight:650}
  .rname small{display:block;color:var(--mute);font-size:14px;margin-top:3px;line-height:1.35}
  .rtemp{font-size:30px;font-weight:300;letter-spacing:-.02em;white-space:nowrap}
  .more{width:36px;height:36px;margin:-6px -8px 0 0;border-radius:50%;display:grid;place-items:center;color:var(--mute);--mdc-icon-size:22px}
  .bar{position:relative;height:44px;margin-top:14px;border-radius:10px;background:var(--bg2);overflow:hidden}
  .bar.big{height:84px}
  .bar .seg{position:absolute;bottom:0;border-radius:6px 6px 0 0;opacity:.9;display:flex;align-items:flex-start;justify-content:center;
    border-left:1px solid var(--card)}
  .bar .seg span{font-size:12px;font-weight:600;color:#fff;margin-top:5px;text-shadow:0 1px 2px rgba(0,0,0,.25)}
  .bar .now{position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;background:var(--primary-text-color);opacity:.75}
  .bar .now::before{content:"";position:absolute;top:-1px;left:-3px;width:8px;height:8px;border-radius:50%;background:var(--primary-text-color)}
  .empty-bar{display:grid;place-items:center;color:var(--mute);font-size:13px}
  .ticks{display:flex;justify-content:space-between;font-size:11px;color:var(--mute);margin:4px 1px 0}
  .week{display:grid;grid-template-columns:repeat(7,1fr);gap:5px;margin-top:14px}
  .day{display:flex;flex-direction:column;align-items:center;gap:5px;padding:8px 2px 7px;border-radius:12px;background:var(--bg2);min-width:0}
  .day.today{outline:2px solid var(--acc);outline-offset:-2px}
  .day .d{font-size:12px;font-weight:700;color:var(--mute)}
  .day .dot{width:8px;height:8px;border-radius:50%}
  .mini{position:relative;display:block;width:calc(100% - 8px);height:26px;border-radius:5px;overflow:hidden;background:color-mix(in srgb,var(--card) 55%,transparent)}
  .mini i{position:absolute;bottom:0}
  .mini.none{border:1.5px dashed var(--line);background:transparent}
  .legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin:10px 2px 2px;font-size:13px;color:var(--mute)}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .legend i{width:8px;height:8px;border-radius:50%}
  .specials{display:flex;flex-direction:column;margin-top:10px;border-top:1px solid var(--line)}
  .sp{display:flex;align-items:center;gap:8px;min-height:46px;padding:0 2px;border-bottom:1px solid var(--line);font-size:15px;text-align:left;--mdc-icon-size:18px}
  .sp:last-child{border-bottom:0}
  .sp b{flex:1;font-weight:500}
  .sp .dot{flex:none;width:8px;height:8px;border-radius:50%}
  .sp .dot.none{background:transparent;border:1.5px dashed var(--mute)}
  .sp .mute{color:var(--mute)}
  .sp .chev{color:var(--mute)}
  .ptile{display:flex;flex-direction:column;gap:0;cursor:pointer;width:100%;text-align:left}
  .ptile .ph{display:flex;align-items:center;gap:10px}
  .ptile .ph .dot{width:14px;height:14px;border-radius:50%;flex:none}
  .ptile .ph b{flex:1;font-size:17px;font-weight:650}
  .ptile .ph small{color:var(--mute);font-size:13px}
  .ptile .use{color:var(--mute);font-size:13px;margin-top:8px}
  .btn{min-height:46px;padding:0 18px;border-radius:14px;font-weight:600;background:var(--bg2);display:inline-flex;align-items:center;justify-content:center;gap:8px;--mdc-icon-size:20px}
  .btn.primary{background:var(--acc);color:var(--text-primary-color,#fff)}
  .btn.danger{color:var(--bad)}
  .btn.wide{width:100%}
  .btn[disabled]{opacity:.45;pointer-events:none}
  .btn.small{min-height:36px;padding:0 12px;font-size:14px;border-radius:11px}
  .add{width:100%;border:1.5px dashed var(--line);background:transparent;color:var(--mute)}
  .hint{color:var(--mute);font-size:13px;line-height:1.45;margin:4px 4px 16px}
  .warn{background:color-mix(in srgb,var(--bad) 10%,var(--card));border:1px solid var(--bad);padding:12px 14px;border-radius:14px;margin-bottom:14px;font-size:14px}
  .empty{text-align:center;padding:36px 20px;color:var(--mute);border:2px dashed var(--line);border-radius:20px;--mdc-icon-size:40px}
  .empty b{display:block;color:var(--primary-text-color);font-size:17px;margin:10px 0 6px}
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.42);z-index:20;display:flex;align-items:flex-end;justify-content:center;animation:fade .15s}
  @keyframes fade{from{opacity:0}}
  @keyframes up{from{transform:translateY(40px);opacity:.4}}
  .sheet{width:100%;max-width:560px;max-height:92vh;overflow:auto;border-radius:22px 22px 0 0;
    background:color-mix(in srgb,var(--primary-background-color) 82%,var(--card-background-color,#fff));
    padding:8px 16px calc(18px + env(safe-area-inset-bottom));animation:up .2s ease-out;
    backdrop-filter:blur(28px) saturate(1.2);-webkit-backdrop-filter:blur(28px) saturate(1.2)}
  .overlay.still,.overlay.still .sheet{animation:none}
  @media (min-width:700px){.overlay{align-items:center}.sheet{border-radius:22px;padding-bottom:18px}}
  .grab{width:38px;height:5px;border-radius:3px;background:var(--line);margin:4px auto 10px}
  .sh{display:flex;align-items:center;gap:8px;margin-bottom:12px}
  .sh b{flex:1;font-size:19px;font-weight:650}
  .sh button{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:var(--bg2);--mdc-icon-size:20px}
  .lbl{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--mute);font-weight:600;margin:16px 2px 8px}
  .chips{display:flex;flex-wrap:wrap;gap:6px}
  .chip{min-width:44px;height:36px;padding:0 12px;border-radius:18px;background:var(--bg2);font-weight:600;font-size:14px;color:var(--mute)}
  .chip.on{background:var(--acc);color:var(--text-primary-color,#fff)}
  .chip.ghost{background:transparent;border:1px solid var(--line)}
  .opt{display:flex;flex-direction:column;width:100%;padding:12px;border-radius:14px;border:1px solid var(--line);margin-bottom:8px;text-align:left}
  .opt.on{border-color:var(--acc);box-shadow:inset 0 0 0 1px var(--acc)}
  .opt .ph{display:flex;align-items:center;gap:10px}
  .opt .ph .dot{width:12px;height:12px;border-radius:50%;flex:none}
  .opt .ph b{flex:1;font-weight:600}
  .opt .bar{height:28px;margin-top:10px}
  .field{display:flex;flex-direction:column;gap:6px;margin-bottom:12px}
  .field input,.field select{height:46px;border-radius:12px;border:1px solid var(--line);background:var(--bg2);padding:0 12px;font-size:16px;width:100%}
  .field small{color:var(--mute);font-size:12px}
  .pts{display:flex;flex-direction:column;gap:8px}
  .pt{display:flex;align-items:center;gap:8px;padding:8px;border-radius:14px;background:var(--bg2)}
  .pt .sw{flex:none;width:6px;align-self:stretch;border-radius:3px}
  .pt input[type=time]{height:40px;border-radius:10px;border:1px solid var(--line);background:var(--card);padding:0 8px;font-size:16px;width:112px}
  .pt .fixed{width:112px;font-size:14px;color:var(--mute);padding-left:6px}
  .stepper{display:flex;align-items:center;gap:2px;margin-left:auto}
  .stepper button{width:40px;height:40px;border-radius:12px;background:var(--card);display:grid;place-items:center;--mdc-icon-size:20px}
  .stepper span{min-width:62px;text-align:center;font-weight:650;font-size:17px}
  .pt .x{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;color:var(--mute);--mdc-icon-size:20px}
  .pt .x.hid{visibility:hidden}
  .row{display:flex;gap:8px;margin-top:16px;flex-wrap:wrap}
  .row .btn{flex:1}
  .err{color:var(--bad);font-size:14px;margin-top:10px}
  .menu .btn{width:100%;justify-content:flex-start;margin-bottom:8px}
  `;

  class HeizplanPanel extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._data = null;
      this._tab = 'rooms';
      this._sheet = null; // { kind, ... }
      this._error = null;
      this._busy = false;
      this._sig = '';
      this.shadowRoot.addEventListener('click', (e) => this._onClick(e));
      this.shadowRoot.addEventListener('change', (e) => this._onChange(e));
      this.shadowRoot.addEventListener('input', (e) => this._onInput(e));
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first) this._subscribe();
      // Nur neu zeichnen, wenn sich die Plan-Sensoren geändert haben
      const sig = this._data ? this._data.rooms.map((r) => { const s = hass.states[`sensor.heizplan_${r.key}`]; return s ? s.last_updated : ''; }).join('|') : '';
      if (sig !== this._sig) { this._sig = sig; if (!this._sheet) this._render(); }
    }

    set narrow(v) { this._narrow = v; }

    get _admin() { return !!(this._hass && this._hass.user && this._hass.user.is_admin); }

    connectedCallback() {
      this._tick = setInterval(() => { if (!this._sheet) this._render(); }, 60000);
      if (this._hass && !this._unsub) this._subscribe();
    }

    disconnectedCallback() {
      clearInterval(this._tick);
      if (this._unsub) { this._unsub.then((u) => u()).catch(() => {}); this._unsub = null; }
    }

    _subscribe() {
      if (this._unsub || !this._hass) return;
      this._unsub = this._hass.connection.subscribeMessage((data) => {
        this._data = data; this._error = null;
        if (this._sheet && this._sheet.kind === 'assign') this._renderSheet(); else if (!this._sheet) this._render();
      }, { type: `${DOMAIN}/subscribe` });
      this._unsub.catch((e) => { this._error = errMsg(e); this._unsub = null; this._render(); });
    }

    async _ws(msg) {
      this._busy = true;
      try { return await this._hass.callWS(msg); } finally { this._busy = false; }
    }

    // ---------- Hilfen ----------
    _profiles() { return this._data ? this._data.profiles : []; }
    _profile(id) { return this._profiles().find((p) => p.id === id); }
    _color(id) { const i = this._profiles().findIndex((p) => p.id === id); return i < 0 ? 'transparent' : PROFILE_COLORS[i % PROFILE_COLORS.length]; }
    _room(key) { return this._data && this._data.rooms.find((r) => r.key === key); }
    _todayKey() { return WEEK[(new Date().getDay() + 6) % 7]; }

    _roomState(room) {
      const st = this._hass && this._hass.states[`sensor.heizplan_${room.key}`];
      if (!st || st.state === 'unavailable' || st.state === 'unknown') return null;
      return st;
    }

    _usageText(p) {
      if (!p.usage || !p.usage.length) return 'Nicht verwendet';
      const byRoom = new Map();
      for (const u of p.usage) { if (!byRoom.has(u.room)) byRoom.set(u.room, []); byRoom.get(u.room).push(u.day); }
      return [...byRoom.entries()].map(([k, days]) => `${esc((this._room(k) || { name: k }).name)} ${dayRanges(days)}`).join(' · ');
    }

    // ---------- Rendern ----------
    _render() {
      const nowMin = new Date().getHours() * 60 + new Date().getMinutes();
      let body = '';
      if (this._error) body += `<div class="warn">${esc(this._error)}</div>`;
      if (!this._data) {
        body += this._error ? '' : '<div class="hint">Lädt …</div>';
      } else {
        body += `<div class="seg-ctl"><button data-act="tab" data-tab="rooms" class="${this._tab === 'rooms' ? 'on' : ''}">Räume</button><button data-act="tab" data-tab="profiles" class="${this._tab === 'profiles' ? 'on' : ''}">Profile</button></div>`;
        body += this._tab === 'rooms' ? this._renderRooms(nowMin) : this._renderProfiles();
      }
      this.shadowRoot.innerHTML = `<style>${CSS}</style>
        <div class="top"><button data-act="menu" title="Menü">${ic('menu')}</button><div class="t">Heizpläne</div></div>
        <div class="wrap">${body}</div><div id="sheet"></div>`;
      this._renderSheet();
    }

    _todayLine() {
      const f = this._data.flags || {};
      const wd = new Date().getDay();
      let kind = (wd === 0 || wd === 6) ? 'Wochenende' : 'Werktag';
      if (wd >= 1 && wd <= 5 && f.workday === false) kind = 'Freier Tag';
      else if (wd >= 1 && wd <= 5 && f.homeoffice) kind = 'Werktag mit Homeoffice';
      const date = new Date().toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' });
      return `<div class="today">${ic('calendar-today')}<span>${esc(date)} · ${kind}</span></div>`;
    }

    _renderRooms(nowMin) {
      const rooms = this._data.rooms;
      let h = this._todayLine();
      if (!rooms.length) {
        h += `<div class="empty">${ic('home-thermometer-outline')}<b>Noch kein Raum</b>Leg einen Raum an und weise jedem Wochentag ein Profil zu.</div>`;
      }
      const today = this._todayKey();
      for (const room of rooms) {
        const st = this._roomState(room);
        const a = st ? st.attributes : {};
        let sub = 'Heute kein Profil zugewiesen';
        if (st) {
          sub = `${esc(a.profil)} · seit ${esc(hhmm(a.seit))}`;
          if (a.naechster_wechsel) sub += `<br>${isTomorrow(a.naechster_wechsel) ? 'morgen ' : ''}ab ${esc(hhmm(a.naechster_wechsel))} ${deg(a.naechste_temperatur)}`;
        }
        const days = WEEK.map((d) => {
          const p = this._profile(room.days[d]);
          return `<button class="day${d === today ? ' today' : ''}" data-act="assign" data-room="${esc(room.key)}" data-day="${d}" ${this._admin ? '' : 'disabled'} title="${p ? esc(p.name) : 'kein Profil'}">
            <span class="d">${SHORT[d]}</span>${p ? dayBar(p.points, { mini: true }) : '<span class="mini none"></span>'}
            <span class="dot" style="background:${p ? this._color(p.id) : 'transparent'};${p ? '' : 'border:1.5px dashed var(--mute)'}"></span></button>`;
        }).join('');
        const used = [...new Set(WEEK.map((d) => room.days[d]).filter(Boolean))].map((id) => this._profile(id)).filter(Boolean);
        const legend = used.map((p) => `<span><i style="background:${this._color(p.id)}"></i>${esc(p.name)}</span>`).join('');
        const specials = SPECIAL.map(([d, label]) => {
          const p = this._profile(room.days[d]);
          return `<button class="sp" data-act="assign" data-room="${esc(room.key)}" data-day="${d}" ${this._admin ? '' : 'disabled'}>
            <b>${label}</b><span class="dot${p ? '' : ' none'}" style="${p ? `background:${this._color(p.id)}` : ''}"></span>
            <span class="${p ? '' : 'mute'}">${p ? esc(p.name) : 'wie Wochentag'}</span>${ic('chevron-right', 'chev')}</button>`;
        }).join('');
        h += `<div class="card">
          <div class="rhead"><div class="rname"><b>${esc(room.name)}</b><small>${sub}</small></div>
            <div class="rtemp">${st ? deg(st.state, false) : '–'}</div>
            ${this._admin ? `<button class="more" data-act="room-menu" data-room="${esc(room.key)}" title="Raum bearbeiten">${ic('dots-vertical')}</button>` : ''}</div>
          ${dayBar(st ? a.heute : null, { now: st ? nowMin : null, big: true })}
          <div class="week">${days}</div>
          <div class="legend">${legend}</div>
          <div class="specials">${specials}</div>
        </div>`;
      }
      if (this._admin) h += `<button class="btn add" data-act="room-new">${ic('plus')}Raum hinzufügen</button>`;
      h += '<div class="hint" style="margin-top:18px">Der Plan sagt, welche Temperatur gerade gelten soll. Fenster, Abwesenheit, Urlaub und Handeinstellungen am Thermostat regelt die Heizung zusätzlich.</div>';
      return h;
    }

    _renderProfiles() {
      let h = '<div class="hint">Ein Profil ist ein Tagesmuster: ab welcher Uhrzeit welche Temperatur gilt. Ein Profil kannst du in beliebig vielen Räumen und an beliebig vielen Tagen verwenden.</div>';
      for (const p of this._profiles()) {
        const temps = p.points.map((x) => x.temp);
        h += `<div class="card"><button class="ptile" data-act="profile-edit" data-id="${esc(p.id)}" ${this._admin ? '' : 'disabled'}>
          <div class="ph"><span class="dot" style="background:${this._color(p.id)}"></span><b>${esc(p.name)}</b>
            <small>${deg(Math.min(...temps), false)} bis ${deg(Math.max(...temps), false)}</small></div>
          ${dayBar(p.points, { big: true })}
          <div class="use">${this._usageText(p)}</div></button></div>`;
      }
      if (this._admin) h += `<button class="btn add" data-act="profile-new">${ic('plus')}Neues Profil</button>`;
      return h;
    }

    // ---------- Sheets ----------
    _renderSheet() {
      const host = this.shadowRoot.getElementById('sheet');
      if (!host) return;
      const s = this._sheet;
      if (!s) { host.innerHTML = ''; delete host.dataset.kind; return; }
      const old = host.querySelector('.sheet');
      const again = !!old && host.dataset.kind === s.kind;
      const scroll = old ? old.scrollTop : 0;
      host.dataset.kind = s.kind;
      let inner = '';
      if (s.kind === 'assign') inner = this._sheetAssign(s);
      else if (s.kind === 'profile') inner = this._sheetProfile(s);
      else if (s.kind === 'room') inner = this._sheetRoom(s);
      else if (s.kind === 'room-menu') inner = this._sheetRoomMenu(s);
      else if (s.kind === 'delete-profile') inner = this._sheetDeleteProfile(s);
      host.innerHTML = `<div class="overlay${again ? ' still' : ''}" data-act="close-bg"><div class="sheet"><div class="grab"></div>${inner}
        ${s.error ? `<div class="err">${esc(s.error)}</div>` : ''}</div></div>`;
      // Neu zeichnen ohne Sprung: Scrollposition halten, Animation nur beim Öffnen
      if (again) host.querySelector('.sheet').scrollTop = scroll;
    }

    _head(title) { return `<div class="sh"><b>${esc(title)}</b><button data-act="close" title="Schließen">${ic('close')}</button></div>`; }

    _sheetAssign(s) {
      const room = this._room(s.room);
      if (!room) return this._head('Raum fehlt');
      const special = SPECIAL.some(([d]) => s.days.includes(d));
      const chips = (special ? SPECIAL.map(([d]) => d) : WEEK).map((d) => `<button class="chip${s.days.includes(d) ? ' on' : ''}" data-act="toggle-day" data-day="${d}">${SHORT[d]}</button>`).join('');
      const quick = special ? '' : `<div class="chips" style="margin-top:8px">
        <button class="chip ghost" data-act="quick" data-q="work">Mo–Fr</button><button class="chip ghost" data-act="quick" data-q="weekend">Sa + So</button><button class="chip ghost" data-act="quick" data-q="all">Alle</button></div>`;
      const current = s.days.length === 1 ? room.days[s.days[0]] : null;
      let opts = this._profiles().map((p) => `<button class="opt${current === p.id ? ' on' : ''}" data-act="pick" data-id="${esc(p.id)}">
        <div class="ph"><span class="dot" style="background:${this._color(p.id)}"></span><b>${esc(p.name)}</b></div>${dayBar(p.points)}</button>`).join('');
      if (special) {
        const desc = SPECIAL.find(([d]) => d === s.days[0]);
        opts = `<div class="hint" style="margin:0 2px 10px">${esc(desc ? desc[2] : '')}</div>
          <button class="opt${current == null ? ' on' : ''}" data-act="pick" data-id=""><div class="ph"><span class="dot" style="border:1.5px dashed var(--mute)"></span><b>Wie Wochentag</b></div></button>${opts}`;
      }
      return `${this._head(room.name)}<div class="lbl">Für</div><div class="chips">${chips}</div>${quick}
        <div class="lbl">Profil</div>${opts}`;
    }

    _sheetProfile(s) {
      const d = s.draft;
      const pts = d.points.map((p, i) => `<div class="pt"><span class="sw" style="background:${tempColor(p.temp)}"></span>
        ${i === 0 ? '<span class="fixed">ab 00:00</span>' : `<input type="time" lang="de" step="900" value="${esc(p.at)}" data-act="pt-time" data-i="${i}">`}
        <div class="stepper"><button data-act="pt-dec" data-i="${i}" title="Kälter">${ic('minus')}</button><span>${deg(p.temp)}</span><button data-act="pt-inc" data-i="${i}" title="Wärmer">${ic('plus')}</button></div>
        <button class="x${i === 0 ? ' hid' : ''}" data-act="pt-del" data-i="${i}" title="Entfernen">${ic('close')}</button></div>`).join('');
      const max = (this._data.limits || {}).max_points || 12;
      return `${this._head(s.id ? 'Profil bearbeiten' : 'Neues Profil')}
        <div class="field"><input type="text" maxlength="40" placeholder="Name, z. B. Werktag" value="${esc(d.name)}" data-act="name"></div>
        <div id="preview">${dayBar(d.points, { big: true })}</div>
        <div class="lbl">Ab Uhrzeit</div><div class="pts">${pts}</div>
        <div class="row"><button class="btn small" data-act="pt-add" ${d.points.length >= max ? 'disabled' : ''}>${ic('plus')}Zeitpunkt</button></div>
        <div class="row"><button class="btn primary" data-act="profile-save" ${this._busy ? 'disabled' : ''}>Speichern</button></div>
        ${s.id ? `<div class="row"><button class="btn" data-act="profile-copy">${ic('content-copy')}Kopie</button><button class="btn danger" data-act="profile-delete">${ic('delete-outline')}Löschen</button></div>` : ''}`;
    }

    _sheetDeleteProfile(s) {
      const p = this._profile(s.id);
      if (!p) return this._head('Profil fehlt');
      const others = this._profiles().filter((x) => x.id !== p.id);
      const used = p.usage && p.usage.length;
      const sel = used ? `<div class="hint" style="margin:0 2px 10px">Verwendet in: ${this._usageText(p)}. Dort soll stattdessen gelten:</div>
        ${others.map((o) => `<button class="opt${s.replacement === o.id ? ' on' : ''}" data-act="replacement" data-id="${esc(o.id)}"><div class="ph"><span class="dot" style="background:${this._color(o.id)}"></span><b>${esc(o.name)}</b></div>${dayBar(o.points)}</button>`).join('')}`
        : '<div class="hint" style="margin:0 2px 10px">Das Profil wird nirgends verwendet.</div>';
      return `${this._head(`„${p.name}“ löschen`)}${sel}
        <div class="row"><button class="btn" data-act="close">Abbrechen</button><button class="btn primary" data-act="profile-delete-do" ${used && !s.replacement ? 'disabled' : ''}>Löschen</button></div>`;
    }

    _sheetRoom(s) {
      const d = s.draft;
      const opts = (sel) => this._profiles().map((p) => `<option value="${esc(p.id)}" ${sel === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
      const keyField = s.edit
        ? `<div class="field"><small>Kürzel: ${esc(d.key)} · Sensor sensor.heizplan_${esc(d.key)}</small></div>`
        : `<div class="field"><input type="text" placeholder="kuerzel" value="${esc(d.key)}" data-act="room-key"><small>Kürzel für den Sensor sensor.heizplan_&lt;kürzel&gt;, nur a–z, 0–9 und _</small></div>`;
      const start = s.edit ? '' : `<div class="lbl">Startprofile</div>
        <div class="field"><small>Montag bis Freitag</small><select data-act="room-work">${opts(d.work)}</select></div>
        <div class="field"><small>Samstag und Sonntag</small><select data-act="room-weekend">${opts(d.weekend)}</select></div>`;
      return `${this._head(s.edit ? 'Raum umbenennen' : 'Neuer Raum')}
        <div class="field"><input type="text" maxlength="40" placeholder="Name, z. B. Wohnzimmer" value="${esc(d.name)}" data-act="room-name"></div>
        ${keyField}${start}
        <div class="row"><button class="btn primary" data-act="room-save">${s.edit ? 'Speichern' : 'Anlegen'}</button></div>`;
    }

    _sheetRoomMenu(s) {
      const room = this._room(s.room);
      if (!room) return this._head('Raum fehlt');
      if (s.confirm) {
        return `${this._head(`${room.name} entfernen?`)}<div class="hint" style="margin:0 2px 10px">Der Sensor sensor.heizplan_${esc(room.key)} verschwindet. Die Profile bleiben.</div>
          <div class="row"><button class="btn" data-act="close">Abbrechen</button><button class="btn primary" data-act="room-delete-do">Entfernen</button></div>`;
      }
      return `${this._head(room.name)}<div class="menu">
        <button class="btn" data-act="room-rename">${ic('pencil-outline')}Umbenennen</button>
        <button class="btn danger" data-act="room-delete">${ic('delete-outline')}Raum entfernen</button></div>`;
    }

    _openProfile(p, copy = false) {
      this._sheet = {
        kind: 'profile',
        id: copy ? null : (p ? p.id : null),
        draft: p
          ? { name: copy ? `${p.name} (Kopie)` : p.name, points: p.points.map((x) => ({ ...x })) }
          : { name: '', points: [{ at: '00:00', temp: 17 }, { at: '06:00', temp: 20 }, { at: '22:00', temp: 17 }] },
      };
      this._renderSheet();
    }

    _sortPoints(d) {
      const first = d.points[0];
      const rest = d.points.slice(1).sort((a, b) => mins(a.at) - mins(b.at));
      d.points = [first, ...rest];
    }

    _updatePreview() {
      const el = this.shadowRoot.getElementById('preview');
      if (el && this._sheet && this._sheet.draft) el.innerHTML = dayBar(this._sheet.draft.points, { big: true });
    }

    // ---------- Ereignisse ----------
    _onInput(e) {
      const t = e.target; const s = this._sheet;
      if (!s || !t.dataset) return;
      if (t.dataset.act === 'name') s.draft.name = t.value;
      if (t.dataset.act === 'room-name') {
        s.draft.name = t.value;
        if (!s.edit && !s.keyTouched) {
          s.draft.key = slug(t.value);
          const k = this.shadowRoot.querySelector('[data-act="room-key"]'); if (k) k.value = s.draft.key;
        }
      }
      if (t.dataset.act === 'room-key') { s.draft.key = t.value.trim(); s.keyTouched = true; }
    }

    _onChange(e) {
      const t = e.target; const s = this._sheet;
      if (!s || !t.dataset) return;
      if (t.dataset.act === 'pt-time') {
        const i = Number(t.dataset.i);
        if (!t.value) return;
        s.draft.points[i].at = t.value.slice(0, 5);
        this._sortPoints(s.draft);
        this._renderSheet();
      }
      if (t.dataset.act === 'room-work') s.draft.work = t.value;
      if (t.dataset.act === 'room-weekend') s.draft.weekend = t.value;
    }

    async _onClick(e) {
      const el = e.target.closest('[data-act]');
      if (!el) return;
      const act = el.dataset.act; const s = this._sheet;
      if (act === 'close-bg') { if (e.target === el) { this._sheet = null; this._render(); } return; }
      e.stopPropagation();
      const lim = (this._data && this._data.limits) || { temp_min: 5, temp_max: 30, temp_step: 0.5 };
      try {
        switch (act) {
          case 'menu': this.dispatchEvent(new Event('hass-toggle-menu', { bubbles: true, composed: true })); break;
          case 'tab': this._tab = el.dataset.tab; this._render(); break;
          case 'close': this._sheet = null; this._render(); break;
          case 'assign': this._sheet = { kind: 'assign', room: el.dataset.room, days: [el.dataset.day] }; this._renderSheet(); break;
          case 'toggle-day': {
            const d = el.dataset.day;
            if (SPECIAL.some(([x]) => x === d)) s.days = [d];
            else s.days = s.days.includes(d) ? s.days.filter((x) => x !== d) : [...s.days, d];
            this._renderSheet(); break;
          }
          case 'quick': s.days = el.dataset.q === 'work' ? WEEK.slice(0, 5) : el.dataset.q === 'weekend' ? ['sat', 'sun'] : [...WEEK]; this._renderSheet(); break;
          case 'pick': {
            if (!s.days.length) { s.error = 'Bitte mindestens einen Tag wählen'; this._renderSheet(); break; }
            await this._ws({ type: `${DOMAIN}/assign`, key: s.room, days: s.days, profile: el.dataset.id || null });
            this._sheet = null; this._render(); break;
          }
          case 'profile-new': this._openProfile(null); break;
          case 'profile-edit': this._openProfile(this._profile(el.dataset.id)); break;
          case 'profile-copy': this._openProfile({ ...s.draft, id: null }, true); break;
          case 'pt-inc': case 'pt-dec': {
            const p = s.draft.points[Number(el.dataset.i)];
            p.temp = Math.max(lim.temp_min, Math.min(lim.temp_max, p.temp + (act === 'pt-inc' ? lim.temp_step : -lim.temp_step)));
            this._renderSheet(); break;
          }
          case 'pt-del': s.draft.points.splice(Number(el.dataset.i), 1); this._renderSheet(); break;
          case 'pt-add': {
            const last = s.draft.points[s.draft.points.length - 1];
            const at = Math.min(23 * 60 + 45, mins(last.at) + 120);
            const hh = String(Math.floor(at / 60)).padStart(2, '0'); const mm = String(at % 60).padStart(2, '0');
            s.draft.points.push({ at: `${hh}:${mm}`, temp: last.temp });
            this._sortPoints(s.draft); this._renderSheet(); break;
          }
          case 'profile-save': {
            const name = (s.draft.name || '').trim();
            if (!name) { s.error = 'Bitte einen Namen eingeben'; this._renderSheet(); break; }
            const seen = new Set();
            for (const p of s.draft.points) { if (seen.has(p.at)) { s.error = `Uhrzeit ${p.at} kommt doppelt vor`; this._renderSheet(); return; } seen.add(p.at); }
            const profile = { name, points: s.draft.points };
            if (s.id) profile.id = s.id;
            await this._ws({ type: `${DOMAIN}/profile/save`, profile });
            this._sheet = null; this._tab = 'profiles'; this._render(); break;
          }
          case 'profile-delete': this._sheet = { kind: 'delete-profile', id: s.id, replacement: null }; this._renderSheet(); break;
          case 'replacement': s.replacement = el.dataset.id; this._renderSheet(); break;
          case 'profile-delete-do':
            await this._ws({ type: `${DOMAIN}/profile/delete`, profile_id: s.id, replacement: s.replacement });
            this._sheet = null; this._render(); break;
          case 'room-new': {
            const ps = this._profiles();
            const work = (ps.find((p) => p.id === 'werktag') || ps[0] || {}).id;
            const weekend = (ps.find((p) => p.id === 'zuhause') || ps[0] || {}).id;
            this._sheet = { kind: 'room', edit: false, draft: { name: '', key: '', work, weekend } }; this._renderSheet(); break;
          }
          case 'room-menu': this._sheet = { kind: 'room-menu', room: el.dataset.room }; this._renderSheet(); break;
          case 'room-rename': { const r = this._room(s.room); this._sheet = { kind: 'room', edit: true, draft: { name: r.name, key: r.key } }; this._renderSheet(); break; }
          case 'room-delete': s.confirm = true; this._renderSheet(); break;
          case 'room-delete-do': await this._ws({ type: `${DOMAIN}/room/delete`, key: s.room }); this._sheet = null; this._render(); break;
          case 'room-save': {
            const d = s.draft;
            if (!d.name.trim()) { s.error = 'Bitte einen Namen eingeben'; this._renderSheet(); break; }
            let days;
            if (s.edit) days = { ...this._room(d.key).days };
            else {
              if (this._room(d.key)) { s.error = 'Dieses Kürzel gibt es schon'; this._renderSheet(); break; }
              days = Object.fromEntries(WEEK.map((w, i) => [w, i < 5 ? d.work : d.weekend]));
            }
            await this._ws({ type: `${DOMAIN}/room/save`, room: { key: d.key, name: d.name.trim(), days } });
            this._sheet = null; this._tab = 'rooms'; this._render(); break;
          }
          default: break;
        }
      } catch (err) {
        if (this._sheet) { this._sheet.error = errMsg(err); this._renderSheet(); } else { this._error = errMsg(err); this._render(); }
      }
    }
  }

  if (!customElements.get('heizplan-panel')) customElements.define('heizplan-panel', HeizplanPanel);
})();
