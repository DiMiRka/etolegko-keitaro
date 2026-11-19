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

  return {toast: toast, api: api, busy: busy, offerSelect: offerSelect};
})();

var Editor = (function () {
  var campaignId;
  var PIN = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M16 3l5 5-3 1-3 3 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 3-3z"/></svg>';

  function streamUrl(s, tail) { return '/api/streams/' + s.id + tail; }

  function offerRow(s, o) {
    var removed = o.state === 'removed';
    var $tr = $('<tr>').toggleClass('removed', removed).toggleClass('changed', o.is_dirty && !removed);

    $('<td>')
      .append($('<div class="offer-name">').text(o.offer_name || ('Offer ' + o.offer_id)))
      .append($('<div class="muted small">').text('ID ' + o.offer_id + (removed ? ' · archived' : '')))
      .appendTo($tr);

    var $share = $('<td class="share">');
    var $value = $('<span class="share-value">').text(o.share + '%');
    if (!removed) {
      $value.attr('title', 'Нажмите, чтобы задать и закрепить долю').addClass('editable');
      $value.on('click', function () { editShare(s, o, $share); });
    }
    var $pin = $('<button class="pin" type="button">').html(PIN)
      .toggleClass('on', o.pinned)
      .attr('title', o.pinned ? 'Открепить долю' : 'Закрепить долю')
      .prop('disabled', removed)
      .on('click', function () {
        act($pin, s, '/offers/' + o.offer_id + '/pin', {pinned: !o.pinned});
      });
    $share.append($value, $pin).appendTo($tr);

    var $btn = removed
      ? $('<button class="btn small">Bring back</button>').on('click', function () {
          act($btn, s, '/offers/' + o.offer_id + '/bring-back');
        })
      : $('<button class="btn small danger">Remove</button>').on('click', function () {
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
    var title = 'Stream: ' + s.name + ' (#' + s.position + '), stream_id ' + s.keitaro_id;
    var $head = $('<div class="stream-head">').append($('<h3>').text(title));

    if (s.has_offers) {
      var $push = $('<button class="btn primary small">Push to KT</button>').prop('disabled', !s.is_dirty);
      var $cancel = $('<button class="btn small">Cancel</button>').prop('disabled', !s.is_dirty);
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
      $card.append($('<div class="error-box">').text('Последний push не прошёл: ' + s.last_error));
    }

    if (!s.has_offers) {
      return $card.append('<p class="muted">Поток без офферов: фильтры и действие не разбираем</p>');
    }

    var $table = $('<table class="table offers"><thead><tr><th>Name</th><th>Share</th><th class="right">Actions</th></tr></thead><tbody></tbody></table>');
    var $tbody = $table.find('tbody');
    s.offers.forEach(function (o) { $tbody.append(offerRow(s, o)); });
    if (!s.offers.length) $tbody.append('<tr><td colspan="3" class="muted">Офферов нет</td></tr>');
    $card.append($table);

    var total = s.offers.reduce(function (sum, o) { return sum + (o.state === 'active' ? o.share : 0); }, 0);
    $card.append($('<div class="muted small total">').text('Сумма активных: ' + total + '%'));

    var $select = $('<select class="offer-select"></select>');
    var $add = $('<button class="btn small">Add</button>');
    var $form = $('<div class="add-offer">').append($('<div class="grow">').append($select), $add);
    $card.append($form);
    App.offerSelect($select, 'Add offer: search by name or ID');
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

  function renderAll(c) {
    var $root = $('#streams').empty();
    if (!c.streams.length) $root.append('<p class="muted">Потоков нет. Нажмите Fetch streams from KT</p>');
    c.streams.forEach(render);
  }

  function act($btn, s, tail, body) {
    return App.busy($btn, App.api('POST', streamUrl(s, tail), body)).done(render);
  }

  function init(id) {
    campaignId = id;
    App.api('GET', '/api/campaigns/' + id).done(renderAll);
    $('#fetch').on('click', function () {
      if ($('#streams .stream.dirty').length &&
          !confirm('Есть неопубликованные изменения. Fetch заменит их данными из Keitaro. Продолжить?')) {
        return;
      }
      App.busy($(this), App.api('POST', '/api/campaigns/' + campaignId + '/fetch')).done(function (c) {
        renderAll(c);
        App.toast('Потоки обновлены из Keitaro');
      });
    });
  }

  return {init: init};
})();
