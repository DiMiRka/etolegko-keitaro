var App = (function () {
  var toastTimer;

  function toast(text, isError) {
    var $t = $('#toast');
    $t.text(text).toggleClass('error', !!isError).prop('hidden', false);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { $t.prop('hidden', true); }, isError ? 6000 : 2500);
  }

  function api(method, url, body) {
    return $.ajax({
      method: method,
      url: url,
      contentType: 'application/json',
      data: body === undefined ? undefined : JSON.stringify(body),
      dataType: 'json'
    }).fail(function (xhr) {
      var detail = xhr.responseJSON && xhr.responseJSON.detail;
      if (Array.isArray(detail)) {
        detail = detail.map(function (d) { return d.msg; }).join('; ');
      }
      toast(detail || ('Ошибка ' + xhr.status), true);
    });
  }

  function busy($btn, xhr) {
    $btn.prop('disabled', true).addClass('loading');
    return xhr.always(function () { $btn.prop('disabled', false).removeClass('loading'); });
  }

  function offerSelect($el, placeholder) {
    return $el.select2({
      placeholder: placeholder,
      width: '100%',
      minimumInputLength: 0,
      language: {
        searching: function () { return 'Поиск…'; },
        noResults: function () { return 'Ничего не найдено'; },
        errorLoading: function () { return 'Не удалось загрузить офферы'; }
      },
      ajax: {
        url: '/api/offers',
        delay: 250,
        data: function (p) { return {q: p.term || ''}; },
        processResults: function (rows) {
          return {results: rows.map(function (o) { return {id: o.id, text: o.name}; })};
        }
      }
    });
  }

  function field($form, name) { return $form.find('[name="' + name + '"]'); }

  function num(n) {
    if (Math.abs(n) >= 10000) {
      return (n / 1000).toLocaleString('ru-RU', {maximumFractionDigits: 1}) + 'K';
    }
    return n.toLocaleString('ru-RU', {maximumFractionDigits: 2});
  }

  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  function clicks(n) { return num(n) + ' ' + plural(n, 'клик', 'клика', 'кликов'); }

  function shortDay(iso) { return iso.slice(8, 10) + '.' + iso.slice(5, 7); }

  var STATE_LABELS = {active: 'Включена', disabled: 'Выключена'};

  function stateBadge(state) {
    if (!state) return $('<span class="muted">').text('—');
    return $('<span class="state-badge">').addClass('state-' + state).text(STATE_LABELS[state] || state);
  }

  function copy(text) {
    var done = function () { toast('Ссылка скопирована'); };
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(done, function () { toast('Не удалось скопировать', true); });
    }
    var $t = $('<textarea>').val(text).css({position: 'fixed', opacity: 0}).appendTo('body');
    $t[0].select();
    try { document.execCommand('copy'); done(); } catch (e) { toast('Не удалось скопировать', true); }
    $t.remove();
  }

  var REFS = [['domain_id', 'domains'], ['group_id', 'groups'], ['traffic_source_id', 'traffic_sources']];

  function fillRefs($f, data) {
    REFS.forEach(function (ref) {
      var $sel = field($f, ref[0]).empty();
      data[ref[1]].forEach(function (item) {
        $('<option>').val(item.id).text(item.name + ' (#' + item.id + ')').appendTo($sel);
      });
      $sel.prop('disabled', false);
      if (data[ref[1]].length > 8) $sel.select2({width: '100%'});
    });
  }

  function setRefs($f, values) {
    REFS.forEach(function (ref) {
      var $sel = field($f, ref[0]);
      var v = values[ref[0]];
      $sel.find('option.unknown').remove();
      if (v !== null && v !== undefined && !$sel.find('option[value="' + v + '"]').length) {
        $('<option class="unknown">').val(v).text('#' + v + ' (нет в списке)').prependTo($sel);
      }
      if (v === null || v === undefined) {
        $('<option class="unknown" value="">').text('—').prependTo($sel);
        v = '';
      }
      $sel.val(String(v)).trigger('change.select2');
    });
  }

  function readRefs($f) {
    var out = {};
    REFS.forEach(function (ref) {
      var v = Number(field($f, ref[0]).val());
      if (v) out[ref[0]] = v;
    });
    return out;
  }

  return {
    toast: toast, api: api, busy: busy, offerSelect: offerSelect, field: field,
    num: num, plural: plural, clicks: clicks, shortDay: shortDay,
    STATE_LABELS: STATE_LABELS, stateBadge: stateBadge, copy: copy,
    fillRefs: fillRefs, setRefs: setRefs, readRefs: readRefs
  };
})();

var Charts = (function () {
  function niceMax(v) {
    if (v <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v)));
    var steps = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) {
      if (steps[i] * p >= v) return steps[i] * p;
    }
    return 10 * p;
  }

  function columns(days, values, title) {
    var max = Math.max.apply(null, values);
    var top = niceMax(max);
    var peak = max > 0 ? values.indexOf(max) : -1;
    var summary = days.map(function (d, i) { return App.shortDay(d) + ': ' + values[i]; }).join(', ');

    var $chart = $('<div class="chart">').attr({role: 'img', 'aria-label': title + '. ' + summary});
    var $plot = $('<div class="chart-plot">');
    [top, top / 2, 0].filter(function (t) { return t === Math.floor(t); }).forEach(function (t) {
      $('<div class="chart-grid">').css('bottom', (t / top * 100) + '%')
        .append($('<span class="chart-tick">').text(App.num(t)))
        .appendTo($plot);
    });
    var $tip = $('<div class="chart-tip" hidden>');
    var $cols = $('<div class="chart-cols">');
    values.forEach(function (v, i) {
      var $slot = $('<div class="chart-slot">');
      var $col = $('<div class="chart-col">').css('height', (v / top * 100) + '%').toggleClass('zero', v === 0);
      if (i === peak) $col.append($('<span class="chart-peak">').text(App.num(v)));
      $slot.append($col).on('mouseenter', function () {
        $cols.find('.chart-slot').removeClass('hover');
        $slot.addClass('hover');
        $tip.text(App.shortDay(days[i]) + ' · ' + App.clicks(v)).prop('hidden', false)
          .css('left', ((i + 0.5) / values.length * 100) + '%');
      });
      $cols.append($slot);
    });
    $cols.on('mouseleave', function () {
      $cols.find('.chart-slot').removeClass('hover');
      $tip.prop('hidden', true);
    });
    $plot.append($cols, $tip);

    var $x = $('<div class="chart-x">');
    days.forEach(function (d) { $x.append($('<span>').text(App.shortDay(d))); });
    $chart.append($plot, $x);

    var $table = $('<table class="table compact"><thead><tr><th>День</th><th class="right">Клики</th></tr></thead><tbody></tbody></table>');
    days.forEach(function (d, i) {
      $table.find('tbody').append($('<tr>').append($('<td>').text(App.shortDay(d)), $('<td class="right">').text(App.num(values[i]))));
    });
    var $details = $('<details class="chart-table"><summary>Показать таблицей</summary></details>').append($table);
    return $('<div>').append($chart, $details);
  }

  function spark(days, values) {
    var top = Math.max.apply(null, values) || 1;
    var $s = $('<span class="spark">').attr({
      role: 'img',
      'aria-label': 'Клики по дням: ' + values.join(', ')
    });
    values.forEach(function (v, i) {
      $('<span class="spark-bar">')
        .css('height', Math.max(v / top * 100, v > 0 ? 12 : 0) + '%')
        .toggleClass('last', i === values.length - 1)
        .attr('title', App.shortDay(days[i]) + ' · ' + App.clicks(v))
        .appendTo($s);
    });
    return $s;
  }

  return {columns: columns, spark: spark};
})();

var Stats = (function () {
  var TILES = [
    ['clicks', 'Клики', function (v) { return App.num(v); }],
    ['unique_clicks', 'Уникальные', function (v) { return App.num(v); }],
    ['conversions', 'Конверсии', function (v) { return App.num(v); }],
    ['cr', 'CR', function (v) { return App.num(v) + '%'; }],
    ['revenue', 'Доход', function (v) { return '$' + App.num(v); }]
  ];

  function render(data) {
    var t = data.total;
    var n = data.days.length;
    $('#stats-title').text('Статистика за ' + n + ' ' + App.plural(n, 'день', 'дня', 'дней'));
    var $root = $('#stats').empty();
    var $tiles = $('<div class="tiles">');
    TILES.forEach(function (tile) {
      $('<div class="tile">')
        .append($('<div class="tile-label">').text(tile[1]))
        .append($('<div class="tile-value">').text(tile[2](t[tile[0]])))
        .appendTo($tiles);
    });
    $root.append($tiles);
    $root.append($('<div class="chart-title">').text('Клики по дням'));
    $root.append(Charts.columns(data.days, t.by_day, 'Клики по дням'));
    if (!t.clicks) {
      $root.append('<p class="muted small">Кликов за период нет. Статистика появится, когда на кампанию пойдёт трафик</p>');
    }
  }

  function load(url, onData) {
    var $btn = $('#stats-refresh');
    return App.busy($btn, App.api('GET', url)).done(function (data) {
      render(data);
      if (onData) onData(data);
    }).fail(function () {
      $('#stats').html('<p class="muted">Статистику получить не удалось</p>');
    });
  }

  return {load: load};
})();

var CampaignList = (function () {
  var LINK_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>';
  var rows = null;
  var groups = {};
  var totals = null;

  function statCell(c, key) {
    if (totals === null) return $('<td class="right num muted">').text('…');
    var t = totals[c.keitaro_id];
    return $('<td class="right num">').text(App.num(t ? t[key] : 0));
  }

  function render() {
    if (rows === null) return;
    var q = $.trim($('#f-search').val()).toLowerCase();
    var group = $('#f-group').val();
    var state = $('#f-state').val();
    var shown = rows.filter(function (c) {
      return (!q || c.name.toLowerCase().indexOf(q) >= 0 || String(c.keitaro_id).indexOf(q) === 0) &&
        (!group || String(c.group_id) === group) &&
        (!state || c.state === state);
    });
    var $tb = $('#campaigns tbody').empty();
    if (!shown.length) {
      $tb.append($('<tr><td colspan="8" class="muted"></td></tr>').find('td').text(rows.length
        ? 'Ничего не найдено'
        : 'Пока пусто: создайте новую кампанию или подключите существующую').end());
    }
    shown.forEach(function (c) {
      var href = '/campaigns/' + c.id;
      var $copy = $('<button class="icon-btn" type="button">').html(LINK_ICON)
        .attr('title', c.url ? 'Скопировать ссылку ' + c.url : 'Ссылка появится после загрузки потоков')
        .attr('aria-label', 'Скопировать ссылку кампании')
        .prop('disabled', !c.url)
        .on('click', function (e) { e.stopPropagation(); App.copy(c.url); });
      $('<tr>')
        .append($('<td>').append($('<a>').attr('href', href).text(c.name)))
        .append($('<td>').append(App.stateBadge(c.state)))
        .append($('<td>').text(c.geo || '—'))
        .append($('<td>').text(c.group_id ? (groups[c.group_id] || '#' + c.group_id) : '—'))
        .append(statCell(c, 'clicks'))
        .append(statCell(c, 'conversions'))
        .append($('<td class="right num">').text(c.keitaro_id))
        .append($('<td class="right">').append($copy))
        .on('click', function (e) { if (!$(e.target).closest('a, button').length) window.location = href; })
        .appendTo($tb);
    });
  }

  function fillGroups() {
    if (rows === null) return;
    var $sel = $('#f-group');
    $sel.find('option:not(:first)').remove();
    var used = {};
    rows.forEach(function (c) { if (c.group_id) used[c.group_id] = groups[c.group_id] || '#' + c.group_id; });
    Object.keys(used).sort(function (a, b) { return used[a].localeCompare(used[b]); }).forEach(function (id) {
      $('<option>').val(id).text(used[id]).appendTo($sel);
    });
  }

  function load() {
    App.api('GET', '/api/campaigns').done(function (data) { rows = data; fillGroups(); render(); });
    App.api('GET', '/api/references').done(function (refs) {
      refs.groups.forEach(function (g) { groups[g.id] = g.name; });
      fillGroups();
      render();
    });
    $.ajax({url: '/api/campaigns/stats', dataType: 'json'})
      .done(function (data) { totals = data.campaigns; })
      .fail(function () { totals = {}; })
      .always(render);
  }

  function init() {
    load();
    $('#f-search').on('input', render);
    $('#f-group, #f-state').on('change', render);
    $('#import-form').on('submit', function (e) {
      e.preventDefault();
      var $f = $(this);
      var body = {keitaro_id: Number(App.field($f, 'keitaro_id').val())};
      App.busy($f.find('button'), App.api('POST', '/api/campaigns/import', body)).done(function (c) {
        window.location = '/campaigns/' + c.id;
      });
    });
  }

  return {init: init};
})();

var CampaignNew = (function () {
  function init() {
    var $f = $('#create-form');
    App.offerSelect(App.field($f, 'offer_id'), 'Поиск оффера по названию или ID');
    App.api('GET', '/api/references').done(function (data) {
      App.fillRefs($f, data);
      App.setRefs($f, data.defaults);
    });
    $f.on('submit', function (e) {
      e.preventDefault();
      var body = {
        name: App.field($f, 'name').val(),
        geo: App.field($f, 'geo').val(),
        offer_id: Number(App.field($f, 'offer_id').val())
      };
      $.extend(body, App.readRefs($f));
      if (!body.offer_id) { App.toast('Выберите оффер', true); return; }
      App.busy($f.find('button[type=submit]'), App.api('POST', '/api/campaigns', body)).done(function (c) {
        window.location = '/campaigns/' + c.id;
      });
    });
  }

  return {init: init};
})();

var Editor = (function () {
  var stats = null;
  var known = {};
  var EMPTY = {clicks: 0, today: 0, by_day: [], offers: {}};
  var PIN ='<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M16 3l5 5-3 1-3 3 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 3-3z"/></svg>';

  function streamUrl(s, tail) { return '/api/streams/' + s.id + tail; }

  function streamStats(s) {
    if (!stats) return null;
    var st = stats.streams[s.keitaro_id] || EMPTY;
    return {
      clicks: st.clicks,
      today: st.today,
      offer: function (offerId) {
        var o = st.offers[offerId];
        return o || {clicks: 0, by_day: stats.days.map(function () { return 0; })};
      }
    };
  }

  function offerRow(s, o, st) {
    var removed = o.state === 'removed';
    var locked = removed || o.disabled;
    var $tr = $('<tr>')
      .toggleClass('removed', removed)
      .toggleClass('disabled', o.disabled && !removed)
      .toggleClass('changed', o.is_dirty && !removed);

    var note = removed ? ' · в архиве' : (o.disabled ? ' · отключён в Keitaro' : '');
    $('<td>')
      .append($('<div class="offer-name">').append(
        $('<a>').attr('href', '/offers/' + o.offer_id).text(o.offer_name || ('Оффер ' + o.offer_id))
      ))
      .append($('<div class="muted small">').text('ID ' + o.offer_id + note))
      .appendTo($tr);

    var $share = $('<td class="share">');
    var $value = $('<span class="share-value">').text(o.share + '%');
    if (!locked) {
      $value.attr('title', 'Нажмите, чтобы задать и закрепить долю').addClass('editable');
      $value.on('click', function () { editShare(s, o, $share); });
    }
    var $pin = $('<button class="pin" type="button">').html(PIN)
      .toggleClass('on', o.pinned)
      .attr('title', o.pinned ? 'Открепить долю' : 'Закрепить долю')
      .prop('disabled', locked)
      .on('click', function () {
        act($pin, s, '/offers/' + o.offer_id + '/pin', {pinned: !o.pinned});
      });
    $share.append($value, $pin).appendTo($tr);

    var $clicks = $('<td class="right num">');
    var $trend = $('<td class="trend">');
    if (st) {
      var os = st.offer(o.offer_id);
      $clicks.text(App.num(os.clicks));
      $trend.append(Charts.spark(stats.days, os.by_day));
    } else {
      $clicks.text('…').addClass('muted');
    }
    $tr.append($clicks, $trend);

    var $btn = removed
      ? $('<button class="btn small">Вернуть</button>').on('click', function () {
          act($btn, s, '/offers/' + o.offer_id + '/bring-back');
        })
      : $('<button class="btn small danger">Удалить</button>').on('click', function () {
          act($btn, s, '/offers/' + o.offer_id + '/remove');
        });
    $('<td class="right">').append($btn).appendTo($tr);
    return $tr;
  }

  function editShare(s, o, $cell) {
    var $input = $('<input type="number" min="0" max="100" class="share-input">').val(o.share);
    $cell.find('.share-value').replaceWith($input);
    $input.trigger('focus').trigger('select');
    var done = false;
    function finish(save) {
      if (done) return;
      done = true;
      var share = parseInt($input.val(), 10);
      if (save && !isNaN(share)) {
        act($input, s, '/offers/' + o.offer_id + '/pin', {pinned: true, share: share}).fail(function () { render(s); });
      } else {
        render(s);
      }
    }
    $input.on('keydown', function (e) {
      if (e.key === 'Enter') finish(true);
      if (e.key === 'Escape') finish(false);
    }).on('blur', function () { finish(false); });
  }

  function streamCard(s) {
    var $card = $('<section class="card stream">').attr('data-id', s.id).toggleClass('dirty', s.is_dirty);
    var title = 'Поток: ' + s.name + ' (#' + s.position + '), stream_id ' + s.keitaro_id;
    var st = streamStats(s);
    var $title = $('<div>').append($('<h3>').text(title));
    if (st) {
      $title.append($('<div class="muted small">').text(
        'Кликов сегодня: ' + App.num(st.today) + ' · за ' + stats.days.length + ' ' +
        App.plural(stats.days.length, 'день', 'дня', 'дней') + ': ' + App.num(st.clicks)
      ));
    }
    var $head = $('<div class="stream-head">').append($title);

    if (s.has_offers) {
      var $push = $('<button class="btn primary small">Опубликовать в Keitaro</button>').prop('disabled', !s.is_dirty);
      var $cancel = $('<button class="btn small">Отменить</button>').prop('disabled', !s.is_dirty);
      $push.on('click', function () {
        act($push, s, '/push').done(function () { App.toast('Опубликовано в Keitaro'); });
      });
      $cancel.on('click', function () { act($cancel, s, '/cancel'); });
      var $actions = $('<div class="actions">');
      if (s.is_dirty) $actions.append('<span class="badge">не опубликовано</span>');
      $head.append($actions.append($push, $cancel));
    }
    $card.append($head);

    if (s.last_error) {
      $card.append($('<div class="error-box">').text('Последняя публикация не прошла: ' + s.last_error));
    }

    if (!s.has_offers) {
      return $card.append('<p class="muted">Поток без офферов: фильтры и действие не разбираем</p>');
    }

    var days = stats ? stats.days.length : 7;
    var $table = $('<table class="table offers"><thead><tr>' +
      '<th>Оффер</th><th>Доля</th><th class="right">Клики, ' + days + ' дн.</th><th>Тренд</th>' +
      '<th class="right">Действия</th></tr></thead><tbody></tbody></table>');
    var $tbody = $table.find('tbody');
    s.offers.forEach(function (o) { $tbody.append(offerRow(s, o, st)); });
    if (!s.offers.length) $tbody.append('<tr><td colspan="5" class="muted">Офферов нет</td></tr>');
    $card.append($('<div class="table-wrap">').append($table));

    var total = s.offers.reduce(function (sum, o) {
      return sum + (o.state === 'active' && !o.disabled ? o.share : 0);
    }, 0);
    $card.append($('<div class="muted small total">').text('Сумма активных: ' + total + '%'));

    var $select = $('<select class="offer-select"></select>');
    var $add = $('<button class="btn small">Добавить</button>');
    $card.append($('<div class="add-offer">').append($('<div class="grow">').append($select), $add));
    App.offerSelect($select, 'Добавить оффер: поиск по названию или ID');
    $add.on('click', function () {
      var offerId = Number($select.val());
      if (!offerId) { App.toast('Выберите оффер', true); return; }
      act($add, s, '/offers', {offer_id: offerId});
    });
    return $card;
  }

  function render(s) {
    known[s.id] = s;
    var $old = $('#streams .stream[data-id="' + s.id + '"]');
    var $new = streamCard(s);
    if ($old.length) $old.replaceWith($new); else $('#streams').append($new);
  }

  function setStats(data) {
    stats = data;
    $.each(known, function (_, s) { render(s); });
  }

  function renderAll(streams) {
    known = {};
    var $root = $('#streams').empty();
    if (!streams.length) $root.append('<p class="muted">Потоков нет. Нажмите «Загрузить потоки из Keitaro»</p>');
    streams.forEach(render);
  }

  function act($btn, s, tail, body) {
    return App.busy($btn, App.api('POST', streamUrl(s, tail), body)).done(render);
  }

  return {renderAll: renderAll, setStats: setStats};
})();

var OfferList = (function () {
  var rows = [];

  function payout(o) {
    return o.payout_type + ' · ' + App.num(o.payout_value) + ' ' + o.payout_currency;
  }

  function render(filter) {
    var q = $.trim(filter || '').toLowerCase();
    var $tb = $('#offers tbody').empty();
    var shown = rows.filter(function (o) {
      return !q || o.name.toLowerCase().indexOf(q) >= 0 || String(o.id).indexOf(q) === 0 ||
        o.group.toLowerCase().indexOf(q) >= 0;
    });
    if (!shown.length) {
      $tb.append($('<tr><td colspan="7" class="muted"></td></tr>').find('td')
        .text(rows.length ? 'Ничего не найдено' : 'Ключу не доступен ни один оффер').end());
    }
    shown.forEach(function (o) {
      var href = '/offers/' + o.id;
      $('<tr>').toggleClass('muted', o.state !== 'active')
        .append($('<td class="num">').text(o.id))
        .append($('<td>').append($('<a>').attr('href', href).text(o.name)))
        .append($('<td>').text(o.group || '—'))
        .append($('<td>').text(o.countries.join(', ') || '—'))
        .append($('<td class="num">').text(payout(o)))
        .append($('<td class="right num">').text(o.clicks_7d === null ? '—' : App.num(o.clicks_7d)))
        .append($('<td class="right num">').text(o.campaigns_count))
        .on('click', function (e) { if (!$(e.target).is('a')) window.location = href; })
        .appendTo($tb);
    });
  }

  function init() {
    App.api('GET', '/api/offers/catalog').done(function (data) {
      rows = data;
      render($('#offer-filter').val());
    });
    $('#offer-filter').on('input', function () { render(this.value); });
  }

  return {init: init};
})();

var OfferCard = (function () {
  var STATES = {active: 'активен', removed: 'в архиве'};

  function usage(rows) {
    var $tb = $('#usage tbody').empty();
    if (!rows.length) {
      $tb.append('<tr><td colspan="4" class="muted">Оффер не используется в потоках кампаний из списка</td></tr>');
    }
    rows.forEach(function (r) {
      var status = r.disabled ? 'отключён в Keitaro' : STATES[r.state];
      if (r.is_dirty) status += ', не опубликовано';
      $('<tr>').toggleClass('removed', r.state === 'removed')
        .append($('<td>').append($('<a>').attr('href', '/campaigns/' + r.campaign_id).text(r.campaign_name)))
        .append($('<td>').text(r.stream_name + ' (stream_id ' + r.stream_keitaro_id + ')'))
        .append($('<td class="num">').text(r.share + '%' + (r.pinned ? ' · закреплено' : '')))
        .append($('<td>').text(status))
        .appendTo($tb);
    });
  }

  function campaigns(data) {
    var $root = $('#stats-campaigns').empty();
    if (!data.campaigns.length) return;
    var $t = $('<table class="table compact"><thead><tr><th>Кампания в Keitaro</th>' +
      '<th class="right">Клики</th><th class="right">Конверсии</th></tr></thead><tbody></tbody></table>');
    data.campaigns.slice(0, 10).forEach(function (c) {
      $t.find('tbody').append($('<tr>')
        .append($('<td>').text(c.name + ' (#' + c.keitaro_id + ')'))
        .append($('<td class="right num">').text(App.num(c.clicks)))
        .append($('<td class="right num">').text(App.num(c.conversions))));
    });
    $root.append($('<div class="chart-title spaced">').text('Кампании с наибольшим числом кликов'), $t);
  }

  function init(id) {
    var url = '/api/offers/' + id + '/stats';
    App.api('GET', '/api/offers/' + id).done(function (o) { usage(o.usage); });
    Stats.load(url, campaigns);
    $('#stats-refresh').on('click', function () { Stats.load(url, campaigns); });
  }

  return {init: init};
})();

var CampaignCard = (function () {
  var campaignId;
  var saved = {};
  var refsLoaded = false;

  function showCampaign(c) {
    saved = {
      name: c.name, geo: c.geo || '',
      domain_id: c.domain_id, group_id: c.group_id, traffic_source_id: c.traffic_source_id
    };
    var $f = $('#main-form');
    App.field($f, 'name').val(saved.name);
    App.field($f, 'geo').val(saved.geo);
    if (refsLoaded) App.setRefs($f, saved);
    $('#title, #crumb-name').text(c.name);
    $('#alias').text(c.alias);
    $('#state-badge').replaceWith(App.stateBadge(c.state).attr('id', 'state-badge'));
    $('#toggle-state').prop('hidden', !c.state)
      .text(c.state === 'active' ? 'Выключить' : 'Включить')
      .data('active', c.state !== 'active');
    $('#campaign-url').val(c.url || '');
    $('#copy-url').prop('disabled', !c.url);
    $('#open-url').attr('href', c.url || null).toggleClass('disabled', !c.url);
    document.title = c.name + ' · Keitaro wrapper';
    $f.find('button[type=submit]').prop('disabled', true);
    Editor.renderAll(c.streams);
  }

  function changes() {
    var $f = $('#main-form');
    var body = {};
    var name = $.trim(App.field($f, 'name').val());
    var geo = $.trim(App.field($f, 'geo').val()).toUpperCase();
    if (name !== saved.name) body.name = name;
    if (geo !== saved.geo) body.geo = geo;
    if (refsLoaded) {
      $.each(App.readRefs($f), function (key, value) {
        if (value !== saved[key]) body[key] = value;
      });
    }
    return body;
  }

  function init(id) {
    campaignId = id;
    var statsUrl = '/api/campaigns/' + id + '/stats';
    App.api('GET', '/api/campaigns/' + id).done(function (c) {
      showCampaign(c);
      Stats.load(statsUrl, Editor.setStats);
    });
    $('#stats-refresh').on('click', function () { Stats.load(statsUrl, Editor.setStats); });

    var $f = $('#main-form');
    App.api('GET', '/api/references').done(function (data) {
      App.fillRefs($f, data);
      refsLoaded = true;
      App.setRefs($f, saved);
    });
    $f.on('input change', 'input, select', function () {
      $f.find('button[type=submit]').prop('disabled', $.isEmptyObject(changes()));
    });
    $f.on('submit', function (e) {
      e.preventDefault();
      var body = changes();
      if ($.isEmptyObject(body)) return;
      App.busy($f.find('button[type=submit]'), App.api('PATCH', '/api/campaigns/' + campaignId, body))
        .done(function (c) { showCampaign(c); App.toast('Сохранено в Keitaro'); });
    });

    $('#fetch').on('click', function () {
      if ($('#streams .stream.dirty').length &&
          !confirm('Есть неопубликованные изменения. Загрузка заменит их данными из Keitaro. Продолжить?')) {
        return;
      }
      App.busy($(this), App.api('POST', '/api/campaigns/' + campaignId + '/fetch')).done(function (c) {
        showCampaign(c);
        App.toast('Потоки обновлены из Keitaro');
      });
    });

    $('#toggle-state').on('click', function () {
      var active = $(this).data('active');
      if (!active && !confirm('Выключить кампанию? Keitaro перестанет обрабатывать по ней трафик')) return;
      App.busy($(this), App.api('POST', '/api/campaigns/' + campaignId + '/state', {active: active}))
        .done(function (c) {
          showCampaign(c);
          App.toast(active ? 'Кампания включена' : 'Кампания выключена');
        });
    });

    $('#copy-url').on('click', function () { App.copy($('#campaign-url').val()); });

    $('#forget').on('click', function () {
      if (!confirm('Убрать кампанию из списка? В Keitaro она останется как есть')) return;
      App.busy($(this), App.api('DELETE', '/api/campaigns/' + campaignId)).done(function () {
        window.location = '/campaigns';
      });
    });
  }

  return {init: init};
})();
