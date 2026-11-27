/**
 * Magic Tool ↔ Google Sheet（蝕刻紀錄、樣品試算表）寫入程式　version 2
 *
 * 裝法（只要做一次，試算表的擁有者做就好）：
 *   1. 打開試算表 → 擴充功能 → Apps Script → 把原本的程式全部刪掉，貼上這整份 → 💾 儲存
 *   2. 上面的函式選單選 setupToken → ▶ 執行 → 授權（進階 → 前往…（不安全））
 *      → 下方「執行記錄」會出現「Magic Tool 通行碼：…」
 *   3. 部署 → 新增部署作業 → ⚙ 選「網頁應用程式」
 *      執行身分：我　／　誰可以存取：所有人　→ 部署 → 複製「網頁應用程式網址」（…/exec 結尾）
 *   4. Magic Tool：⚙ 設定 → 蝕刻紀錄 → 貼上 Apps Script 網址和通行碼 → 測試連線
 *      → 📋 複製團隊設定碼，私下傳給同事（裡面有通行碼，不要貼在公開的地方）
 *
 * 安全
 *   ‧ 沒有通行碼的請求一律拒絕；想換通行碼就執行 resetToken（同事要重新貼設定碼）
 *   ‧ 修改、刪除前，舊的那一列會先複製到「MagicTool 修改紀錄」工作表
 *   ‧ 只寫 Magic Tool 指定的格子；其他欄位、公式、格式都不動
 *   ‧ 改了這份程式以後：部署 → 管理部署作業 → ✎ → 版本選「新版本」→ 部署（網址不變）
 */
var VERSION = 2;
var HISTORY_SHEET = 'MagicTool 修改紀錄';

function setupToken() {
  var p = PropertiesService.getScriptProperties();
  var t = p.getProperty('TOKEN');
  if (!t) {
    t = Utilities.getUuid().replace(/-/g, '').slice(0, 24);
    p.setProperty('TOKEN', t);
  }
  SpreadsheetApp.getActiveSpreadsheet();          // 順便要到試算表的權限
  Logger.log('Magic Tool 通行碼：' + t);
  return t;
}

function resetToken() {
  PropertiesService.getScriptProperties().deleteProperty('TOKEN');
  return setupToken();
}

function doGet(e) {
  return json_({ok: true, app: 'MagicTool', version: VERSION,
                message: 'Magic Tool 寫入程式已經部署好了。請把這個網址貼到 Magic Tool 的 ⚙ 設定 → 蝕刻紀錄。'});
}

function doPost(e) {
  var req;
  try {
    req = JSON.parse(e.postData.contents);
  } catch (err) {
    return json_({ok: false, error: '請求的格式不對'});
  }
  var token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token) return json_({ok: false, error: '還沒有設定通行碼：請在 Apps Script 執行一次 setupToken'});
  if (String(req.token || '') !== token) return json_({ok: false, error: '通行碼不對（試算表擁有者可能換過通行碼，請重新貼上團隊設定碼）'});
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(30000);
  } catch (err) {
    return json_({ok: false, error: '有其他人正在寫入，請稍後再試'});
  }
  try {
    return json_(handle_(req));
  } catch (err) {
    return json_({ok: false, error: String((err && err.message) || err)});
  } finally {
    lock.releaseLock();
  }
}

function handle_(req) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = pickSheet_(ss, req.sheet, req.gid);
  var act = req.action;
  var out = {ok: true, title: ss.getName(), sheet: sh.getName(), version: VERSION};
  if (act === 'ping' || act === 'read') {
    var vals = sh.getDataRange().getDisplayValues();
    out.rows = vals.length;
    if (act === 'read') out.values = vals; else out.header = vals[0] || [];
    return out;
  }
  if (req.header) writeHeader_(sh, req.header[0], req.header[1]);
  if (act === 'append') {
    out.rows = appendRows_(sh, req.rows || [], req.key_cols || []);
  } else if (act === 'update') {
    check_(sh, req.row, req.expect || []);
    backup_(ss, sh, req.row, '修改');
    writeCells_(sh, req.row, req.cells || []);
    out.row = req.row;
  } else if (act === 'insert_cols') {
    // 樣品試算表：Process 格子不夠時，在「備註」欄前面插入空白欄（整欄插入，其他列的資料一起往右移，不會錯位）
    var before = Number(req.before), count = Math.min(Number(req.count) || 0, 30);
    if (!(before >= 1) || !(count >= 1)) throw new Error('插入欄的位置不對');
    var hv = sh.getRange(1, before + 1, 1, 1).getDisplayValues()[0][0];
    if (String(req.expect_header || '') !== String(hv).trim()) throw new Error('標題列和預期的不一樣，為了不插錯位置，沒有插入');
    sh.insertColumnsBefore(before + 1, count);
    out.cols = count;
  } else if (act === 'delete') {
    check_(sh, req.row, req.expect || []);
    backup_(ss, sh, req.row, '刪除');
    sh.deleteRow(req.row);
    out.row = req.row;
  } else {
    throw new Error('不認得的動作：' + act);
  }
  return out;
}

function pickSheet_(ss, name, gid) {
  if (name) {
    var s = ss.getSheetByName(name);
    if (!s) throw new Error('找不到工作表「' + name + '」');
    return s;
  }
  if (gid !== undefined && gid !== null && String(gid) !== '') {
    var all = ss.getSheets();
    for (var i = 0; i < all.length; i++) if (String(all[i].getSheetId()) === String(gid)) return all[i];
  }
  return ss.getSheets()[0];
}

function blank_(v) {
  return String(v === null || v === undefined ? '' : v).trim() === '';
}

function ensureSize_(sh, rows, cols) {
  var mr = sh.getMaxRows(), mc = sh.getMaxColumns();
  if (rows > mr) sh.insertRowsAfter(mr, rows - mr);
  if (cols > mc) sh.insertColumnsAfter(mc, cols - mc);
}

function writeHeader_(sh, start, names) {
  if (!names || !names.length) return;
  ensureSize_(sh, 1, start + names.length);
  var rng = sh.getRange(1, start + 1, 1, names.length);
  var cur = rng.getDisplayValues()[0];
  for (var i = 0; i < cur.length; i++) {
    if (!blank_(cur[i]) && String(cur[i]).trim() !== names[i]) {
      throw new Error('標題列第 ' + (start + i + 1) + ' 欄已經有別的名稱（' + cur[i] + '），為了不寫錯位置，沒有寫入');
    }
  }
  rng.setValues([names]);
}

function lastContentRow_(sh, keyCols) {
  var vals = sh.getDataRange().getDisplayValues();
  for (var i = vals.length - 1; i >= 1; i--) {
    for (var k = 0; k < keyCols.length; k++) {
      var j = keyCols[k];
      if (j < vals[i].length && !blank_(vals[i][j])) return i + 1;
    }
  }
  return 1;
}

function appendRows_(sh, rows, keyCols) {
  var start = lastContentRow_(sh, keyCols) + 1;
  var out = [];
  for (var k = 0; k < rows.length; k++) {
    writeCells_(sh, start + k, rows[k]);
    out.push(start + k);
  }
  return out;
}

// cells = [[欄(0 起算), 值], …]；只寫這些格子（連續的一段一次寫），其他格子不動
function writeCells_(sh, row, cells) {
  if (!cells.length) return;
  cells = cells.slice().sort(function (a, b) { return a[0] - b[0]; });
  ensureSize_(sh, row, cells[cells.length - 1][0] + 1);
  var runStart = cells[0][0], vals = [cells[0][1]];
  for (var i = 1; i <= cells.length; i++) {
    if (i < cells.length && cells[i][0] === runStart + vals.length) {
      vals.push(cells[i][1]);
      continue;
    }
    sh.getRange(row, runStart + 1, 1, vals.length).setValues([vals]);
    if (i < cells.length) {
      runStart = cells[i][0];
      vals = [cells[i][1]];
    }
  }
}

function check_(sh, row, expect) {
  if (!row || row < 2 || row > sh.getLastRow()) throw new Error('Google Sheet 沒有第 ' + row + ' 列');
  var cur = sh.getRange(row, 1, 1, sh.getLastColumn()).getDisplayValues()[0];
  for (var k = 0; k < expect.length; k++) {
    var j = expect[k][0];
    var have = j < cur.length ? String(cur[j]).trim() : '';
    if (have !== String(expect[k][1]).trim()) {
      throw new Error('Google Sheet 第 ' + row + ' 列剛剛被別人改過，為了不改錯列，沒有寫入。請按 ↻ 再試一次');
    }
  }
}

function backup_(ss, sh, row, action) {
  var h = ss.getSheetByName(HISTORY_SHEET);
  var width = sh.getLastColumn();
  var head = sh.getRange(1, 1, 1, width).getDisplayValues()[0];
  var cur = sh.getRange(row, 1, 1, width).getDisplayValues()[0];
  if (!h) {
    h = ss.insertSheet(HISTORY_SHEET);
    ensureSize_(h, 1, 4 + head.length);
    h.getRange(1, 1, 1, 4 + head.length).setValues([['時間', '動作', '工作表', '原本第幾列'].concat(head)]);
  }
  var line = [new Date(), action, sh.getName(), row].concat(cur.map(function (v) { return v === '' ? '' : "'" + v; }));
  ensureSize_(h, h.getLastRow() + 1, line.length);
  h.getRange(h.getLastRow() + 1, 1, 1, line.length).setValues([line]);
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
