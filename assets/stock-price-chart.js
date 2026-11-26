(function (root) {
  'use strict';

  function historyTicks(points, asOf, count, compact) {
    if (!points[0]?.date) {
      return points.map(point => ({
        offset: point.offset, label: point.offset === 0 ? asOf || '기준일' : point.label,
        date: point.offset === 0 ? asOf : null,
      }));
    }
    let previousYear;
    const size = Math.min(count, points.length);
    return Array.from({length:size}, (_, i) => {
      const point = points[Math.round(i * (points.length - 1) / Math.max(1, size - 1))];
      const year = point.date.slice(0, 4);
      const label = year === previousYear
        ? point.date.slice(5)
        : compact ? point.date.slice(2) : point.date;
      previousYear = year;
      return {offset:point.offset, date:point.date, label:label.replaceAll('-', '.')};
    });
  }

  function render({symbol, asOf, past, anchor = 0, forecast = [], sampled = false,
    plan, horizon, compact, format, escape}) {
    const hist = past.points;
    const show = forecast.length > 0;
    const w = compact ? 440 : 930;
    const h = compact ? 320 : 454;
    const left = compact ? 63 : 76;
    const right = show ? (compact ? 20 : 110) : 22;
    const top = 24, bottom = compact ? 66 : 60;
    const plotRight = w - right, plotBottom = h - bottom;
    const pastDays = Math.max(1, -hist[0]?.offset || 0);
    const values = hist.map(point => point.close);
    if (show) values.push(plan.buyLow, plan.buyHigh, plan.stop, plan.target1, plan.target2,
      ...forecast.flatMap(point => [point.base, point.bear, point.bull]));
    const prices = values.filter(value => Number.isFinite(value) && value > 0);
    if (!prices.length) return {svg:'', actual:past.actual, show:false, sampled:false, points:[]};
    const min = Math.log(Math.min(...prices)), max = Math.log(Math.max(...prices));
    const pad = Math.max((max - min) * .09, .025);
    const lo = min - pad, hi = max + pad;
    const futureEnd = show ? forecast.at(-1).t + anchor : 0;
    const x = offset => left + (offset + pastDays) / (pastDays + futureEnd) * (plotRight - left);
    const y = value => top + (hi - Math.log(value)) / (hi - lo) * (plotBottom - top);
    const coord = (offset, price) => x(offset).toFixed(1) + ',' + y(price).toFixed(1);
    const modelX = show ? x(anchor) : 0;
    const label = show ? '일별 주가와 전망' : '일별 주가';
    const font = compact ? 13 : 12;
    let svg = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${escape(symbol)} ${label}" data-price-plot="${show ? 'forecast' : 'history'}" data-plot-bottom="${plotBottom}">`;
    if (show) {
      svg += `<rect x="${modelX}" y="${top}" width="${plotRight-modelX}" height="${plotBottom-top}" fill="#72bbdb" opacity=".045"/>`;
    }
    for (let i = 0; i < 4; i++) {
      const value = Math.exp(lo + (hi - lo) * i / 3);
      const yy = y(value);
      const amount = compact && value >= 1000 ? '$' + Math.round(value).toLocaleString('en-US') : format(value);
      svg += `<line x1="${left}" x2="${plotRight}" y1="${yy}" y2="${yy}" stroke="#293747"/>
        <text x="${left-9}" y="${yy+4}" text-anchor="end" fill="#acbdce" font-size="${font}">${amount}</text>`;
    }

    const tickCount = compact ? (show ? 3 : 4) : (show ? 5 : 7);
    const ticks = historyTicks(hist, asOf, tickCount, compact);
    const shortHistory = show && compact && x(0) - left < 165;
    for (const [i, tick] of ticks.entries()) {
      if (!tick.label || (shortHistory && i > 0 && i < ticks.length - 1)) continue;
      const xx = x(tick.offset);
      const align = i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle';
      svg += `<line x1="${xx}" x2="${xx}" y1="${top}" y2="${plotBottom+5}" stroke="#293747" stroke-dasharray="2 4"/>
        <text x="${xx}" y="${h-15}" text-anchor="${align}" fill="#b8c6d4" font-size="${font}"${tick.date ? ` data-price-date="${escape(tick.date)}"` : ''}>${escape(tick.label)}</text>`;
    }

    if (show && plan.buyHigh > 0 && plan.buyLow > 0) {
      const buyTop = Math.min(y(plan.buyHigh), y(plan.buyLow));
      const buyHeight = Math.abs(y(plan.buyLow) - y(plan.buyHigh));
      svg += `<rect x="${left}" y="${buyTop}" width="${plotRight-left}" height="${buyHeight}" fill="#6ee7b7" opacity=".10"/>`;
      if (!compact) svg += `<text x="${left+9}" y="${buyTop+buyHeight/2+4}" fill="#6ee7b7" font-size="11">매수구간</text>`;
    }

    if (show) {
      const upper = forecast.map(point => coord(point.t + anchor, point.bull));
      const lower = forecast.slice().reverse().map(point => coord(point.t + anchor, point.bear));
      svg += `<polygon points="${upper.concat(lower).join(' ')}" fill="#58d5f7" opacity=".15"/>
        <line x1="${modelX}" x2="${modelX}" data-forecast-anchor="${anchor}" y1="${top}" y2="${plotBottom}" stroke="#6a889f" stroke-dasharray="3 5"/>`;
      svg += `<polyline points="${forecast.map(point => coord(point.t + anchor, point.base)).join(' ')}" fill="none" stroke="#58d5f7" stroke-width="2.5" stroke-dasharray="7 5" stroke-linecap="round"/>`;
      for (const [value, color, text] of [[plan.target1,'#f9cf6b','1차 목표'],[plan.stop,'#ff7f91','손절 기준']]) {
        if (!(value > 0)) continue;
        const yy = y(value);
        svg += `<line x1="${left}" x2="${plotRight}" y1="${yy}" y2="${yy}" stroke="${color}" stroke-dasharray="5 5" opacity=".75"/>`;
        if (!compact) svg += `<text x="${plotRight+12}" y="${yy+4}" fill="${color}" font-size="11">${text} ${format(value)}</text>`;
      }
      svg += `<text x="${plotRight}" y="${h-15}" text-anchor="end" fill="#a1ccdf" font-size="${font}">${horizon === 126 ? '+6개월' : '+1년'}</text>`;
    }

    svg += `<polyline points="${hist.map(point => coord(point.offset, point.close)).join(' ')}" fill="none" stroke="#eff6fb" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>`;
    if (!past.actual) {
      svg += hist.map(point => `<circle cx="${x(point.offset)}" cy="${y(point.close)}" r="3" fill="#eff6fb"/>`).join('');
    }
    const last = hist[hist.length - 1];
    if (last) svg += `<circle cx="${x(last.offset)}" cy="${y(last.close)}" r="4" fill="#eff6fb" stroke="#547d92" stroke-width="1.5"/>`;
    return {svg:svg+'</svg>', show, actual:past.actual, sampled, points:past.actual ? hist : [], x, y};
  }

  root.StockPriceChart = {render};
})(window);
