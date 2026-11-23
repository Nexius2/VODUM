(() => {
  const modal = document.querySelector('[data-renewal-modal]');
  const open = document.querySelector('[data-renewal-open]');
  if (!modal || !open) return;
  const close = () => { modal.classList.add('hidden'); modal.classList.remove('flex'); };
  open.addEventListener('click', () => { modal.classList.remove('hidden'); modal.classList.add('flex'); });
  modal.querySelectorAll('[data-renewal-close]').forEach((button) => button.addEventListener('click', close));
  modal.addEventListener('click', (event) => { if (event.target === modal) close(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
  modal.querySelectorAll('[data-copy-value]').forEach((button) => button.addEventListener('click', async () => {
    await navigator.clipboard.writeText(button.dataset.copyValue || '');
    button.textContent = '✓';
  }));
})();
