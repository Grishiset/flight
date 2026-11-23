(() => {
  const SRC = { travelpayouts: 'Aviasales', google_flights: 'Google Flights', etihad: 'Etihad', samokatus: 'Самокатус', self_transfer: 'Свои пересадки' };
  const MON = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const rub = (n) => n == null ? '—' : Math.round(n).toLocaleString('ru-RU').replace(/\s/g, ' ') + ' ₽';
  const total = (o, passengers) => rub(o.quoted_passengers === passengers && o.total_price_rub != null
    ? o.total_price_rub : o.price_rub * passengers);
  const d = (iso) => { const [y, m, dd] = iso.split('-').map(Number); return `${dd} ${MON[m - 1]}`; };
  const color = (i) => `var(--c${i % 5})`;
  const tip = $('tip');

  function showTip(ev, text) {
    tip.textContent = text; tip.hidden = false;
    const x = Math.min(window.innerWidth - tip.offsetWidth - 8, ev.clientX + 12);
    tip.style.left = Math.max(8, x) + 'px'; tip.style.top = (ev.clientY - 36) + 'px';
  }
  const hideTip = () => { tip.hidden = true; };

  function legsList(o) {
    const ul = el('ul', 'legs');
    for (const g of o.legs) {
      const li = el('li');
      // местное время вылета, как в билете (не переводим в часовой пояс читателя)
      const when = `${d(g.dep.slice(0, 10))} ${g.dep.slice(11, 16)}`;
      const text = `${g.from}→${g.to} ${when} · ${g.airline || ''} · ${rub(g.price)}`;
      if (g.link) { const a = el('a', null, text); a.href = g.link; a.target = '_blank'; a.rel = 'noopener'; li.append(a); }
      else li.textContent = text;
      ul.append(li);
    }
    if (o.note) ul.append(el('li', 'legnote', o.note));
    return ul;
  }

  function gfl(o) {
    const N = window.__N || 1;
    const q = `Flights to ${o.destination || ''} from ${o.origin || 'MOW'} on ${o.depart} through ${o.ret}` + (N > 1 ? ` for ${N} adults` : '');
    return 'https://www.google.com/travel/flights?hl=ru&curr=RUB&q=' + encodeURIComponent(q);
  }

  // Ссылки «где проверить и купить»: агрегатор (на всех пассажиров), сайты авиакомпаний, Google Flights
  function buyLinks(o, cls) {
    const box = el('div', cls || 'buy');
    const add = (text, href) => {
      const a = el('a', cls === 'buy-inline' ? null : 'btn', text);
      a.href = href; a.target = '_blank'; a.rel = 'noopener';
      if (box.childNodes.length && cls === 'buy-inline') box.append(' · ');
      box.append(a);
    };
    const N = window.__N || 1;
    if (o.link && !o.legs) add((SRC[o.source] || o.source) + (N > 1 ? ` на ${N}` : '') + ' →', o.link);
    for (const s of o.airline_sites || []) add('Сайт ' + s.name, s.url);
    if (!o.legs && (o.source !== 'google_flights' || !o.link)) add('Google Flights' + (N > 1 ? ` на ${N}` : ''), gfl(o));
    return box;
  }

  function sparkline(points, threshold, colorVar) {
    const ns = 'http://www.w3.org/2000/svg';
    const W = 300, H = 56, P = 4;
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'spark');
    svg.setAttribute('role', 'img');
    const pts = points.filter((p) => p[1] != null).map((p) => [new Date(p[0]).getTime(), p[1], p[0]]);
    svg.setAttribute('aria-label', pts.length ? `История лучшей цены, ${pts.length} точек` : 'Истории пока нет');
    if (!pts.length) return svg;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]).concat([threshold]);
    let x0 = Math.min(...xs), x1 = Math.max(...xs); if (x0 === x1) { x0 -= 86400e3; x1 += 86400e3; }
    let y0 = Math.min(...ys) * 0.95, y1 = Math.max(...ys) * 1.05;
    const sx = (x) => P + (x - x0) / (x1 - x0) * (W - 2 * P);
    const sy = (y) => H - P - (y - y0) / (y1 - y0) * (H - 2 * P);
    const thr = document.createElementNS(ns, 'line');
    Object.entries({ x1: 0, x2: W, y1: sy(threshold), y2: sy(threshold), stroke: 'var(--ok)', 'stroke-dasharray': '4 3', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke' })
      .forEach(([k, v]) => thr.setAttribute(k, v));
    svg.append(thr);
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(''));
    Object.entries({ fill: 'none', stroke: colorVar, 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }).forEach(([k, v]) => path.setAttribute(k, v));
    svg.append(path);
    for (const p of pts) {
      const c = document.createElementNS(ns, 'circle');
      Object.entries({ cx: sx(p[0]), cy: sy(p[1]), r: pts.length > 12 ? 6 : 3, fill: pts.length > 12 ? 'transparent' : colorVar }).forEach(([k, v]) => c.setAttribute(k, v));
      const label = `${new Date(p[2]).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}: ${rub(p[1])}`;
      c.addEventListener('pointerenter', (ev) => showTip(ev, label));
      c.addEventListener('pointerdown', (ev) => showTip(ev, label));
      c.addEventListener('pointerleave', hideTip);
      svg.append(c);
    }
    return svg;
  }

  function render(data) {
    const L = data.latest;
    const N = L.passengers || 1;
    window.__N = N;
    const pp = N > 1 ? ' с чел.' : '';
    const routes = L.routes;
    const at = new Date(L.at);
    $('meta').textContent = `Туда-обратно, ${N > 1 ? N + ' взрослых (крупно — сумма на всех)' : '1 взрослый'}, эконом. Лето: ${d(L.window.start)} – ${d(L.window.end)} ${L.window.end.slice(0, 4)}, поездка ${L.window.min_days}–${L.window.max_days} дн. ` +
      `Последняя проверка: ${at.toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' })} по Москве.`;

    const deals = routes.filter((r) => r.is_deal);
    const withPrice = routes.filter((r) => r.best).sort((a, b) => a.best.price_rub / a.threshold - b.best.price_rub / b.threshold);
    if (deals.length) $('lede').textContent = 'Выгодно сейчас: ' + deals.map((r) => `${r.name} — ${total(r.best, N)}`).join(', ') + (N > 1 ? ` на ${N} чел` : '') + '.';
    else if (withPrice.length) {
      const r = withPrice[0];
      $('lede').textContent = `Ни одна летняя цена пока не дошла до порога. Ближе всего — ${r.name}: ${total(r.best, N)}${N > 1 ? ` на ${N} чел. (${rub(r.best.price_rub)} с человека)` : ''}, на ${Math.round((r.best.price_rub / r.threshold - 1) * 100)}% выше порога.`;
    } else $('lede').textContent = 'Летних билетов в выдаче пока нет ни по одному направлению.';

    const cards = $('cards'); cards.replaceChildren();
    routes.forEach((r, i) => {
      const c = el('article', 'card' + (r.is_deal ? ' deal' : ''));
      const top = el('div', 'card-top');
      const name = el('div', 'card-name'); const dot = el('span', 'dot'); dot.style.background = color(i); name.append(dot, r.name);
      top.append(name);
      if (r.best) {
        const gap = Math.round((r.best.price_rub / r.threshold - 1) * 100);
        top.append(el('span', 'chip ' + (r.best.price_rub <= r.threshold ? 'ok' : gap <= 15 ? 'warn' : ''), r.best.price_rub <= r.threshold ? 'ниже порога' : `+${gap}% к порогу`));
      }
      c.append(top);
      if (r.best) {
        const b = r.best;
        c.append(el('div', 'price', total(b, N)));
        if (N > 1) c.append(el('div', 'sub', `${rub(b.price_rub)} с человека · на ${N} чел.`));
        c.append(el('div', 'sub', `${d(b.depart)} → ${d(b.ret)} (${b.days} дн.)${b.via ? ', через ' + b.via : ''}${b.airline ? ', ' + b.airline : ''}`));
        if (b.legs) c.append(legsList(b));
        c.append(el('div', 'sub', `${SRC[b.source] || b.source} · порог ${rub(r.threshold)}${pp}${r.median ? ' · обычно ' + rub(r.median) + pp : ''}`));
        if (r.reasons.length) { const ul = el('ul', 'reasons'); r.reasons.forEach((x) => ul.append(el('li', null, x))); c.append(ul); }
        const others = Object.entries(r.by_source).filter(([k]) => k !== b.source).map(([k, v]) => `${SRC[k] || k}: ${total(v, N)}`);
        if (others.length) c.append(el('div', 'sub', 'Другие источники: ' + others.join(' · ')));
        c.append(buyLinks(b));
      } else {
        c.append(el('div', 'price none', 'Летних билетов пока нет'));
        c.append(el('div', 'sub', `Порог ${rub(r.threshold)}${pp}`));
      }
      c.append(sparkline(data.history[r.route_id] || [], r.threshold, color(i)));
      cards.append(c);
    });

    // Таблица всех билетов
    const fr = $('f-route'), fs = $('f-source');
    if (fr.options.length === 1) {
      routes.forEach((r) => fr.append(new Option(r.name, r.route_id)));
      Object.keys(L.sources).forEach((k) => fs.append(new Option(SRC[k] || k, k)));
      fr.onchange = fs.onchange = () => drawTable(routes, fr.value, fs.value);
    }
    window.__N = N;
    $('th-pp').hidden = N <= 1;
    drawTable(routes, fr.value, fs.value);

    const ul = $('sources'); ul.replaceChildren();
    for (const [k, v] of Object.entries(L.sources)) {
      const li = el('li');
      li.append(el('strong', null, SRC[k] || k), document.createElement('br'));
      if (v.skipped) li.append(el('span', 'st off', 'Пропущен: ' + v.skipped));
      else li.append(el('span', 'st ' + (v.ok ? 'ok' : 'bad'), (v.ok ? 'Работает' : 'Ошибка') + ` · билетов ${v.offers}, летних ${v.summer}`));
      if (v.errors && v.errors.length) li.append(el('div', 'err', v.errors.slice(0, 2).join(' · ')));
      ul.append(li);
    }
  }

  function drawTable(routes, routeId, source) {
    const rows = [];
    for (const r of routes) {
      if (routeId && r.route_id !== routeId) continue;
      for (const o of r.top) if (!source || o.source === source) rows.push([r, o]);
    }
    rows.sort((a, b) => a[1].price_rub - b[1].price_rub);
    const tb = $('offers'); tb.replaceChildren();
    for (const [r, o] of rows.slice(0, 80)) {
      const tr = el('tr');
      tr.append(el('td', null, r.name));
      const N = window.__N || 1;
      tr.append(el('td', 'num' + (o.price_rub <= r.threshold ? ' good' : ''), total(o, N)));
      if (N > 1) tr.append(el('td', 'num muted', rub(o.price_rub)));
      const dc = el('td', 'dates', `${d(o.depart)} → ${d(o.ret)} (${o.days} дн.)`);
      if (o.via) dc.append(el('div', 'legnote', 'через ' + o.via + (o.extra_rub ? ` · вкл. ночёвку ${rub(o.extra_rub)}` : '')));
      if (o.legs) dc.append(legsList(o));
      tr.append(dc);
      tr.append(el('td', null, (o.airline || '—') + (o.stops != null ? `, пересадок: ${o.stops}` : '')));
      const s = el('td'); s.append(el('span', 'src', SRC[o.source] || o.source)); tr.append(s);
      const l = el('td');
      l.append(buyLinks(o, 'buy-inline'));
      tr.append(l);
      tb.append(tr);
    }
    $('offers-empty').hidden = rows.length > 0;
  }

  fetch('data.json', { cache: 'no-store' })
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(render)
    .catch((e) => { $('lede').textContent = 'Не удалось загрузить данные: ' + e.message; });
})();
