/**
 * @OnlyCurrentDoc
 * Family stock-dashboard watchlist endpoint v20.
 * PIN-protected and limited to this spreadsheet only.
 *
 * SET THIS PIN before deploying.
 */

const FAMILY_PIN = 'CHANGE_ME_TO_YOUR_FAMILY_PIN';
const SHEET_NAME = 'custom_tickers';

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function cleanSymbol_(value) {
  return String(value || '').trim().toUpperCase().replace(/-/g, '.');
}

function validate_(p) {
  const expected = String(FAMILY_PIN || '').trim();
  const provided = String((p && p.pin) || '').trim();

  if (!expected || expected === 'CHANGE_ME_TO_YOUR_FAMILY_PIN') {
    return { ok: false, error: 'server_pin_not_configured' };
  }
  if (provided !== expected) {
    return { ok: false, error: 'unauthorized_pin' };
  }

  const symbol = cleanSymbol_(p && p.symbol);
  if (!symbol) return { ok: false, error: 'missing_symbol' };
  if (!/^[A-Z0-9.]{1,15}$/.test(symbol)) return { ok: false, error: 'invalid_symbol', symbol: symbol };

  return { ok: true, symbol: symbol };
}

function upsertTicker_(p) {
  const check = validate_(p || {});
  if (!check.ok) return check;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);

  const header = ['symbol', 'name', 'sector', 'subIndustry', 'addedAt', 'source'];
  if (sh.getLastRow() === 0) sh.appendRow(header);

  const symbol = check.symbol;
  const name = String((p && p.name) || symbol).trim().slice(0, 120);
  const sector = String((p && p.sector) || 'Watchlist').trim().slice(0, 80);
  const subIndustry = String((p && p.subIndustry) || 'Watchlist').trim().slice(0, 120);
  const addedAt = String((p && p.addedAt) || new Date().toISOString()).trim();
  const source = String((p && p.source) || 'dashboard-v20').trim().slice(0, 60);

  const values = sh.getDataRange().getValues();
  let existingRow = -1;
  for (let i = 1; i < values.length; i++) {
    if (cleanSymbol_(values[i][0]) === symbol) {
      existingRow = i + 1;
      break;
    }
  }

  const row = [symbol, name, sector, subIndustry, addedAt, source];
  if (existingRow > 0) {
    sh.getRange(existingRow, 1, 1, row.length).setValues([row]);
  } else {
    sh.appendRow(row);
  }

  return {
    ok: true,
    symbol: symbol,
    action: existingRow > 0 ? 'updated' : 'inserted',
    sheet: SHEET_NAME
  };
}

function doGet(e) {
  const p = e && e.parameter ? e.parameter : {};
  if (p && p.symbol) return json_(upsertTicker_(p));
  return json_({
    ok: true,
    version: 'v20-pin-protected',
    message: 'Watchlist endpoint is running. Add ?symbol=SOFI&pin=YOUR_PIN to test saving.'
  });
}

function doPost(e) {
  const p = e && e.parameter ? e.parameter : {};
  return json_(upsertTicker_(p));
}
