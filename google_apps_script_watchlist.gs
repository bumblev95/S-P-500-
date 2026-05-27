/**
 * @OnlyCurrentDoc
 */

function doPost(e) {
  const sheetName = 'custom_tickers';
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(sheetName);
  if (!sh) sh = ss.insertSheet(sheetName);

  const header = ['symbol', 'name', 'sector', 'subIndustry', 'addedAt', 'source'];
  if (sh.getLastRow() === 0) {
    sh.appendRow(header);
  }

  const p = e && e.parameter ? e.parameter : {};
  const symbol = String(p.symbol || '').trim().toUpperCase().replace('-', '.');
  if (!symbol) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false, error: 'missing symbol' }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  const name = String(p.name || symbol).trim();
  const sector = String(p.sector || 'Watchlist').trim();
  const subIndustry = String(p.subIndustry || 'Watchlist').trim();
  const addedAt = String(p.addedAt || new Date().toISOString()).trim();
  const source = String(p.source || 'dashboard').trim();

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

  return ContentService.createTextOutput(JSON.stringify({ ok: true, symbol: symbol }))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({ ok: true, message: 'Watchlist endpoint is running' }))
    .setMimeType(ContentService.MimeType.JSON);
}
