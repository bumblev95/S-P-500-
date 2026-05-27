/**
 * @OnlyCurrentDoc
 * Family stock-dashboard watchlist endpoint v19.
 * This version accepts both GET and POST so the GitHub Pages dashboard can save
 * tickers without CORS problems.
 */

function upsertTicker_(p) {
  const sheetName = 'custom_tickers';
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(sheetName);
  if (!sh) sh = ss.insertSheet(sheetName);

  const header = ['symbol', 'name', 'sector', 'subIndustry', 'addedAt', 'source'];
  if (sh.getLastRow() === 0) sh.appendRow(header);

  const symbol = String((p && p.symbol) || '').trim().toUpperCase().replace('-', '.');
  if (!symbol) return { ok: false, error: 'missing symbol' };

  const name = String((p && p.name) || symbol).trim();
  const sector = String((p && p.sector) || 'Watchlist').trim();
  const subIndustry = String((p && p.subIndustry) || 'Watchlist').trim();
  const addedAt = String((p && p.addedAt) || new Date().toISOString()).trim();
  const source = String((p && p.source) || 'dashboard').trim();

  const values = sh.getDataRange().getValues();
  let existingRow = -1;
  for (let i = 1; i < values.length; i++) {
    if (String(values[i][0]).trim().toUpperCase().replace('-', '.') === symbol) {
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

  return { ok: true, symbol: symbol };
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  const p = e && e.parameter ? e.parameter : {};
  if (p && p.symbol) return json_(upsertTicker_(p));
  return json_({ ok: true, message: 'Watchlist endpoint is running. Add ?symbol=SOFI to test saving.' });
}

function doPost(e) {
  const p = e && e.parameter ? e.parameter : {};
  return json_(upsertTicker_(p));
}
