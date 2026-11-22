// Responsive administrative tables: keep the same rows, links and form controls.
(() => {
  function prepareTable(table) {
    if (!table.closest('.admin-content') || table.matches('.admin-users-table, [data-mobile-table="scroll"]')) return;
    const headRows = table.tHead?.rows;
    // Matrices with grouped headers/row spans retain their horizontal scroll view.
    if (headRows?.length !== 1 || table.querySelector('[rowspan]')) return;
    const headers = [...headRows[0].cells];
    if (!headers.length || headers.some(cell => cell.colSpan !== 1)) return;
    const labels = headers.map(cell => (cell.textContent || cell.getAttribute('aria-label') || '').replace(/[▲▼↑↓↕↔]/g, '').replace(/\s+/g, ' ').trim());
    const primary = Number(table.dataset.mobilePrimary || 0);
    const wide = new Set((table.dataset.mobileWide || '').split(',').filter(Boolean).map(Number));
    table.classList.add('admin-card-table');
    table.setAttribute('role', 'table');
    table.tHead.setAttribute('role', 'rowgroup');
    headRows[0].setAttribute('role', 'row');
    table.dataset.mobileSortable = String(headers.some(cell => cell.querySelector('a[href], button, input')));
    headers.forEach(cell => cell.setAttribute('role', 'columnheader'));
    if (table.parentElement) table.parentElement.classList.add('admin-card-table-wrap');
    for (const body of table.tBodies) {
      body.setAttribute('role', 'rowgroup');
      for (const row of body.rows) {
        row.setAttribute('role', 'row');
        let column = 0;
        const empty = row.cells.length === 1 && row.cells[0].colSpan >= headers.length;
        for (const cell of row.cells) {
          const span = cell.colSpan || 1;
          const label = labels.slice(column, column + span).filter(Boolean).join(' · ');
          if (cell.dataset.mobileLabel !== label) cell.dataset.mobileLabel = label;
          cell.setAttribute('role', cell.tagName === 'TH' ? 'rowheader' : 'cell');
          cell.toggleAttribute('data-mobile-title', !empty && column === primary);
          cell.toggleAttribute('data-mobile-empty', empty);
          cell.toggleAttribute('data-mobile-wide', empty || span > 1 || wide.has(column) || Boolean(cell.querySelector('button, form, textarea, details')) || cell.textContent.trim().length > 100);
          column += span;
        }
      }
    }
  }

  function prepare(root = document) {
    root.querySelectorAll('.admin-content .border-b').forEach(bar => {
      if (bar.querySelector(':scope > a.border-b-2')) bar.classList.add('admin-tab-strip');
    });
    root.querySelectorAll('.admin-content table').forEach(prepareTable);
  }

  document.addEventListener('DOMContentLoaded', () => {
    prepare();
    document.querySelectorAll('.admin-tab-strip [aria-current="page"], .admin-tab-strip > a.text-primary').forEach(link => {
      link.parentElement.scrollLeft = Math.max(0, link.offsetLeft - link.parentElement.offsetLeft - 16);
    });
    const content = document.querySelector('.admin-content');
    if (!content) return;
    const pending = new Set();
    let scheduled = false;
    // Polling and HTMX replace rows. Observe only inserted content and touch the
    // affected tables, never rebuild the page or duplicate its action handlers.
    new MutationObserver(records => {
      for (const record of records) {
        const table = record.target.closest?.('table');
        if (table) pending.add(table);
        for (const node of record.addedNodes) {
          if (!(node instanceof Element)) continue;
          if (node.matches('table')) pending.add(node);
          node.querySelectorAll('table').forEach(item => pending.add(item));
        }
      }
      if (!pending.size || scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        for (const table of pending) if (table.isConnected) prepareTable(table);
        pending.clear();
      });
    }).observe(content, {childList: true, subtree: true});
  });
  document.addEventListener('htmx:afterSettle', () => prepare());
})();
