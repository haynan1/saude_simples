(() => {
  const dialog = document.getElementById('confirm-dialog');
  const dialogTitle = document.getElementById('confirm-dialog-title');
  const dialogMessage = document.getElementById('confirm-dialog-message');
  const dialogSubmit = dialog?.querySelector('[data-confirm-submit]');
  const dialogCancel = dialog?.querySelector('.confirm-dialog-cancel');
  const bypassedForms = new WeakSet();
  const bypassedControls = new WeakSet();
  let pendingAction = null;
  let previouslyFocused = null;

  function closeConfirmDialog(confirmed = false) {
    if (!dialog || dialog.hidden) return;

    const action = pendingAction;
    pendingAction = null;
    dialog.classList.remove('is-visible');
    dialog.hidden = true;
    dialog.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('confirm-dialog-open');

    if (confirmed && action) {
      action();
      return;
    }

    previouslyFocused?.focus();
  }

  function openConfirmDialog(source, action) {
    const message = source.dataset.confirm;
    if (!dialog || !message) return false;

    const destructive = source.dataset.confirmVariant === 'danger'
      || /excluir|remover|apagar|definitiv/i.test(message);

    previouslyFocused = document.activeElement;
    pendingAction = action;
    dialogTitle.textContent = source.dataset.confirmTitle
      || (destructive ? 'Confirmar exclusão?' : 'Confirmar ação?');
    dialogMessage.textContent = message;
    dialogSubmit.textContent = source.dataset.confirmLabel
      || (destructive ? 'Sim, excluir' : 'Sim, confirmar');
    dialog.classList.toggle('is-danger', destructive);
    dialog.hidden = false;
    dialog.setAttribute('aria-hidden', 'false');
    document.body.classList.add('confirm-dialog-open');
    requestAnimationFrame(() => dialog.classList.add('is-visible'));
    dialogCancel.focus();
    return true;
  }

  dialogSubmit?.addEventListener('click', () => closeConfirmDialog(true));
  dialog?.querySelectorAll('[data-confirm-cancel]').forEach((control) => {
    control.addEventListener('click', () => closeConfirmDialog(false));
  });

  document.addEventListener('click', (event) => {
    const themeButton = event.target.closest('[data-theme-toggle]');
    if (themeButton && typeof window.toggleTheme === 'function') {
      window.toggleTheme();
    }

    const confirmControl = event.target.closest('[data-confirm]');
    if (!confirmControl || confirmControl.tagName === 'FORM') return;
    if (bypassedControls.delete(confirmControl)) return;

    const opened = openConfirmDialog(confirmControl, () => {
      bypassedControls.add(confirmControl);
      confirmControl.click();
    });
    if (opened) event.preventDefault();
  });

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!form.dataset.confirm || bypassedForms.delete(form)) return;

    const submitter = event.submitter;
    const opened = openConfirmDialog(form, () => {
      bypassedForms.add(form);
      form.requestSubmit(submitter || undefined);
    });
    if (opened) event.preventDefault();
  });

  document.addEventListener('keydown', (event) => {
    if (!dialog || dialog.hidden) return;

    if (event.key === 'Escape') {
      event.preventDefault();
      closeConfirmDialog(false);
      return;
    }

    if (event.key === 'Tab') {
      const controls = [...dialog.querySelectorAll('button:not([disabled])')];
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  document.addEventListener('change', (event) => {
    const control = event.target.closest('[data-submit-on-change]');
    if (control?.form) {
      control.form.requestSubmit();
    }
  });
})();
