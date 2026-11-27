// 在 Node 裡模擬 Google Apps Script（SpreadsheetApp 等），測 magic/etching/apps_script.gs。
// 用法：node apps_script_harness.js serve <port> <seed.json>   → 開一個本機 HTTP 伺服器，POST 的內容交給 doPost
//       GET /__state 回傳目前的工作表內容（測試用）
'use strict';
const fs = require('fs');
const path = require('path');
const http = require('http');
const vm = require('vm');

function makeSheet(name, id, rows, maxRows, maxCols) {
  const sh = {
    name, id, grid: rows.map(r => r.map(String)), maxRows: maxRows || 1000, maxCols: maxCols || 26,
    getName() { return this.name; },
    getSheetId() { return this.id; },
    getMaxRows() { return this.maxRows; },
    getMaxColumns() { return this.maxCols; },
    insertRowsAfter(after, n) { this.maxRows += n; },
    insertColumnsAfter(after, n) { this.maxCols += n; },
    cell(i, j) { return (this.grid[i] && this.grid[i][j] !== undefined) ? this.grid[i][j] : ''; },
    getLastRow() {
      for (let i = this.grid.length - 1; i >= 0; i--) if (this.grid[i].some(c => c !== '')) return i + 1;
      return 0;
    },
    getLastColumn() {
      let m = 0;
      this.grid.forEach(r => r.forEach((c, j) => { if (c !== '') m = Math.max(m, j + 1); }));
      return m;
    },
    getDataRange() { return this.getRange(1, 1, Math.max(1, this.getLastRow()), Math.max(1, this.getLastColumn())); },
    deleteRow(r) { this.grid.splice(r - 1, 1); },
    insertColumnsBefore(c, n) {
      this.grid.forEach(row => { while (row.length < c - 1) row.push(''); row.splice(c - 1, 0, ...Array(n).fill('')); });
      this.maxCols += n;
    },
    getRange(r, c, nr, nc) {
      const sheet = this;
      if (r + nr - 1 > sheet.maxRows || c + nc - 1 > sheet.maxCols) {
        throw new Error('範圍超出工作表（' + r + ',' + c + ',' + nr + ',' + nc + '）');
      }
      return {
        getDisplayValues() {
          const out = [];
          for (let i = 0; i < nr; i++) {
            const row = [];
            for (let j = 0; j < nc; j++) row.push(sheet.cell(r - 1 + i, c - 1 + j));
            out.push(row);
          }
          return out;
        },
        setValues(vals) {
          if (vals.length !== nr || vals.some(v => v.length !== nc)) throw new Error('setValues 大小不對');
          for (let i = 0; i < nr; i++) {
            while (sheet.grid.length <= r - 1 + i) sheet.grid.push([]);
            const row = sheet.grid[r - 1 + i];
            for (let j = 0; j < nc; j++) {
              while (row.length <= c - 1 + j) row.push('');
              let v = vals[i][j];
              if (v instanceof Date) v = 'DATE';
              v = String(v === null || v === undefined ? '' : v);
              if (v.startsWith("'")) v = v.slice(1);
              row[c - 1 + j] = v;
            }
          }
        },
      };
    },
  };
  return sh;
}

function loadScript(state) {
  const props = {};
  const ctx = {
    console,
    JSON,
    String, Number, Math, Date, Error,
    SpreadsheetApp: { getActiveSpreadsheet: () => state.ss },
    PropertiesService: { getScriptProperties: () => ({
      getProperty: k => (k in props ? props[k] : null),
      setProperty: (k, v) => { props[k] = v; },
      deleteProperty: k => { delete props[k]; },
    }) },
    LockService: { getScriptLock: () => ({ waitLock() { state.locks++; }, releaseLock() { state.locks--; } }) },
    ContentService: { MimeType: { JSON: 'json' },
      createTextOutput: t => ({ text: t, setMimeType() { return this; } }) },
    Utilities: { getUuid: () => '0123456789abcdef0123456789abcdef' },
    Logger: { log: m => { state.log.push(m); } },
  };
  vm.createContext(ctx);
  const code = fs.readFileSync(path.join(__dirname, '..', 'magic', 'etching', 'apps_script.gs'), 'utf8');
  vm.runInContext(code, ctx);
  return ctx;
}

function makeState(seed) {
  const sheets = seed.sheets.map((s, k) => makeSheet(s.name, s.id || k, s.rows, s.maxRows, s.maxCols));
  const state = { log: [], locks: 0 };
  state.ss = {
    sheets,
    getName: () => seed.title || '測試試算表',
    getSheets: () => sheets,
    getSheetByName: n => sheets.find(s => s.name === n) || null,
    insertSheet(n) { const s = makeSheet(n, 900 + sheets.length, []); sheets.push(s); return s; },
  };
  return state;
}

if (require.main === module && process.argv[2] === 'serve') {
  const port = Number(process.argv[3]);
  const seed = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
  const state = makeState(seed);
  const gs = loadScript(state);
  const token = gs.setupToken();
  const echo = {};
  const srv = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/__state') {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ token, locks: state.locks,
        sheets: state.ss.sheets.map(s => ({ name: s.name, rows: s.getDataRange().getDisplayValues() })) }));
      return;
    }
    if (req.method === 'GET' && req.url.startsWith('/__echo/')) {      // 像 Google 一樣：POST 的結果用轉址後的 GET 拿
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(echo[req.url.slice(8)] || '{}');
      return;
    }
    if (req.method === 'GET') {
      res.setHeader('Content-Type', 'application/json');
      res.end(gs.doGet({}).text);
      return;
    }
    let body = '';
    req.on('data', c => { body += c; });
    req.on('end', () => {
      const out = gs.doPost({ postData: { contents: body } });
      if (req.url === '/redirect') {
        const id = String(Object.keys(echo).length + 1);
        echo[id] = out.text;
        res.statusCode = 302;
        res.setHeader('Location', '/__echo/' + id);
        res.end();
        return;
      }
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(out.text);
    });
  });
  srv.listen(port, '127.0.0.1', () => { process.stdout.write('ready ' + token + '\n'); });
}

module.exports = { makeState, loadScript };
