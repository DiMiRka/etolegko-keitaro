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

  return {toast: toast, api: api, busy: busy, offerSelect: offerSelect, field: field};
})();

var CampaignList = (function () {
  function load() {
    App.api('GET', '/api/campaigns').done(function (rows) {
      var $tb = $('#campaigns tbody').empty();
      if (!rows.length) {
        $tb.append('<tr><td colspan="3" class="muted">Пока пусто: создайте новую кампанию или подключите существующую</td></tr>');
      }
      rows.forEach(function (c) {
        var href = '/campaigns/' + c.id;
        $('<tr>')
          .append($('<td>').append($('<a>').attr('href', href).text(c.name)))
          .append($('<td>').text(c.geo || '—'))
          .append($('<td>').text(c.keitaro_id))
          .on('click', function (e) { if (!$(e.target).is('a')) window.location = href; })
          .appendTo($tb);
      });
    });
  }

  function init() {
    load();
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
    $f.on('submit', function (e) {
      e.preventDefault();
      var body = {
        name: App.field($f, 'name').val(),
        geo: App.field($f, 'geo').val(),
        offer_id: Number(App.field($f, 'offer_id').val())
      };
      if (!body.offer_id) { App.toast('Выберите оффер', true); return; }
      App.busy($f.find('button[type=submit]'), App.api('POST', '/api/campaigns', body)).done(function (c) {
        window.location = '/campaigns/' + c.id;
      });
    });
  }

  return {init: init};
})();

var Editor = (function () {
  var PIN = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M16 3l5 5-3 1-3 3 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 3-3z"/></svg>';

  function streamUrl(s, tail) { return '/api/streams/' + s.id + tail; }

  function offerRow(s, o) {
    var removed = o.state === 'removed';
    var locked = removed || o.disabled;
    var $tr = $('<tr>')
      .toggleClass('removed', removed)
      .toggleClass('disabled', o.disabled && !removed)
      .toggleClass('changed', o.is_dirty && !removed);

    var note = removed ? ' · в архиве' : (o.disabled ? ' · отключён в Keitaro' : '');
    $('<td>')
      .append($('<div class="offer-name">').text(o.offer_name || ('Оффер ' + o.offer_id)))
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
    var $head = $('<div class="stream-head">').append($('<h3>').text(title));

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

    var $table = $('<table class="table offers"><thead><tr><th>Оффер</th><th>Доля</th><th class="right">Действия</th></tr></thead><tbody></tbody></table>');
    var $tbody = $table.find('tbody');
    s.offers.forEach(function (o) { $tbody.append(offerRow(s, o)); });
    if (!s.offers.length) $tbody.append('<tr><td colspan="3" class="muted">Офферов нет</td></tr>');
    $card.append($table);

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
    var $old = $('#streams .stream[data-id="' + s.id + '"]');
    var $new = streamCard(s);
    if ($old.length) $old.replaceWith($new); else $('#streams').append($new);
  }

  function renderAll(streams) {
    var $root = $('#streams').empty();
    if (!streams.length) $root.append('<p class="muted">Потоков нет. Нажмите «Загрузить потоки из Keitaro»</p>');
    streams.forEach(render);
  }

  function act($btn, s, tail, body) {
    return App.busy($btn, App.api('POST', streamUrl(s, tail), body)).done(render);
  }

  return {renderAll: renderAll};
})();

var CampaignCard = (function () {
  var campaignId;
  var saved = {};

  function showCampaign(c) {
    saved = {name: c.name, geo: c.geo || ''};
    var $f = $('#main-form');
    App.field($f, 'name').val(saved.name);
    App.field($f, 'geo').val(saved.geo);
    $('#title, #crumb-name').text(c.name);
    $('#alias').text(c.alias);
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
    return body;
  }

  function init(id) {
    campaignId = id;
    App.api('GET', '/api/campaigns/' + id).done(showCampaign);

    var $f = $('#main-form');
    $f.on('input', 'input', function () {
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

    $('#forget').on('click', function () {
      if (!confirm('Убрать кампанию из списка? В Keitaro она останется как есть')) return;
      App.busy($(this), App.api('DELETE', '/api/campaigns/' + campaignId)).done(function () {
        window.location = '/campaigns';
      });
    });
  }

  return {init: init};
})();
