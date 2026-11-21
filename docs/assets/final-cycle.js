const base = {
  id: 'EXAMPLE-ONLY', for: '2026-11-16', order_type: 'lmt', action: 'SHT',
  qty: 1, underlying: 272093, contract: 'put', expiry: '21DTE+',
  strike: 445, ref: 'prev_close', lmt_prc: 2.62
};
const examples = {
  put: {
    description: 'With $50,000 in cash and a stock close of $523.88, the cash limit brings the put strike down to $445. The order reserves $44,500 plus $0.65 for fees. The minimum premium rounds up to $2.62.',
    orders: [base]
  },
  call: {
    description: 'With 100 shares bought at $600, $1,000 in cash, and a stock close of $523.88, the call strike is $600 to meet the cost-basis floor.',
    orders: [{...base, contract: 'call', strike: 600}]
  },
  wait: {
    description: 'With an option already open, the strategy waits. The script does not add another option order.',
    orders: []
  }
};
function showExample(key) {
  document.getElementById('example-description').textContent = examples[key].description;
  document.getElementById('sample-order').textContent = JSON.stringify(examples[key].orders, null, 2);
  document.querySelectorAll('[data-example]').forEach(button => {
    const active = button.dataset.example === key;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}
document.querySelectorAll('[data-example]').forEach(button => {
  button.addEventListener('click', () => showExample(button.dataset.example));
});
showExample('put');

Promise.all(['status.json', 'open_orders.json'].map(async name => {
  const response = await fetch('final-cycle/' + name, {cache: 'no-store'});
  if (!response.ok) throw Error('Cannot read ' + name);
  return response.json();
})).then(([status, orders]) => {
  const badge = document.getElementById('run-badge');
  badge.className = 'badge ' + status.status;
  badge.textContent = status.status + ' · ' + (status.execution_context === 'github_actions' ? 'GitHub Actions' : 'local run');
  const awaitingPositions = status.reason.startsWith('awaiting_server_book');
  const titles = {
    new_wheel_commitment: 'New order saved',
    same_session_commitment_reused: 'Same order kept for this session'
  };
  document.getElementById('run-reason').textContent = titles[status.reason] || (awaitingPositions ? 'Waiting for a positions update' : status.reason);
  document.getElementById('signal-date').textContent = status.signal_session || 'Not available';
  document.getElementById('target-date').textContent = status.target_session || 'Not available';
  document.getElementById('order-count').textContent = String(status.orders_count);
  document.getElementById('price-lag').textContent = status.price_lag_sessions === undefined ? 'Not available' : status.price_lag_sessions + ' trading session(s)';
  const active = status.active_orders_count ?? status.orders_count;
  document.getElementById('active-count').textContent = String(active);
  document.getElementById('run-time').textContent = status.generated_at.replace(/\.\d+/, '').replace('T', ' ').replace('+00:00', ' UTC');
  document.getElementById('actual-orders').textContent = JSON.stringify(orders, null, 2);
  const target = status.target_session || 'the next session';
  const earlierDates = [...new Set(orders.filter(order => order.for !== target).map(order => order.for))];
  document.getElementById('order-state-note').textContent = active
    ? 'There ' + (active === 1 ? 'is 1 order' : 'are ' + active + ' orders') + ' for ' + target + '.'
    : 'There are no orders for ' + target + '.' + (earlierDates.length ? ' The file below still includes the earlier order dated ' + earlierDates.join(', ') + '.' : '');
  if (status.workflow_run_url) document.getElementById('verified-run-link').href = status.workflow_run_url;
  let explanation;
  if (status.status === 'ready') {
    explanation = 'The script saved the order below. Sanji still needs to process it.';
    if (status.price_lag_sessions) explanation += ' The order uses prices from ' + status.signal_session + ', ' + status.price_lag_sessions + ' trading session behind.';
  } else if (awaitingPositions) {
    explanation = 'An updated positions file has not arrived. The earlier order’s cash stays reserved, and new trades remain on hold.';
  } else if (status.status === 'waiting') {
    explanation = 'The script did not add a new order on this run. Earlier orders keep their original dates.';
  } else {
    explanation = 'The run stopped because an input or check failed. The GitHub log has the details.';
  }
  document.getElementById('run-explanation').textContent = explanation;
}).catch(() => {
  document.getElementById('run-badge').textContent = 'Status unavailable';
  document.getElementById('run-reason').textContent = 'The run details could not be loaded.';
  document.getElementById('run-explanation').textContent = 'Use the order-file and GitHub links below to check the output.';
});
