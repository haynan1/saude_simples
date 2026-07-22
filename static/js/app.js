// Interações próprias do Saúde Simples: modal de exportação em PDF (com prévia
// ao vivo) e cópia rápida dos dados do paciente. Carregado como arquivo externo
// por exigência da CSP (nenhum handler inline).
(() => {
  // ---------------------------------------------------------------------------
  // Modal "Exportar PDF"
  // ---------------------------------------------------------------------------
  const dialog = document.getElementById('export-dialog');
  const form = document.getElementById('exportFilteredPdfForm');
  let previouslyFocused = null;

  function openExportDialog() {
    if (!dialog) return;
    previouslyFocused = document.activeElement;
    dialog.hidden = false;
    dialog.setAttribute('aria-hidden', 'false');
    document.body.classList.add('confirm-dialog-open');
    requestAnimationFrame(() => dialog.classList.add('is-visible'));
    updateExportCount();
  }

  function closeExportDialog() {
    if (!dialog || dialog.hidden) return;
    dialog.classList.remove('is-visible');
    dialog.hidden = true;
    dialog.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('confirm-dialog-open');
    previouslyFocused?.focus();
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-export-open]')) {
      event.preventDefault();
      openExportDialog();
      return;
    }
    if (event.target.closest('[data-export-close]')) {
      closeExportDialog();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && dialog && !dialog.hidden) {
      closeExportDialog();
    }
  });

  function getSelectedExportConditions() {
    return [...document.querySelectorAll('.export-condition:checked')];
  }

  let exportPreviewController = null;

  function renderExportPreview(data) {
    const title = document.querySelector('.export-preview-title');
    const description = document.querySelector('.export-preview-description');
    const mode = document.querySelector('.export-preview-mode');
    const conditions = document.querySelector('.export-preview-conditions');

    Object.entries(data.stats || {}).forEach(([key, value]) => {
      const target = document.querySelector(`[data-preview-stat="${key}"]`);
      if (target) target.textContent = value ?? 0;
    });

    if (data.modo === 'filtrado') {
      if (title) title.textContent = 'Prévia do relatório filtrado';
      if (description) description.textContent = 'A exportação vai incluir somente pacientes com pelo menos uma das comorbidades selecionadas.';
      if (mode) {
        mode.textContent = 'Filtrado';
        mode.className = 'export-preview-mode export-preview-mode-filtered';
      }
      if (conditions) {
        const selected = (data.condicoes || []).map((item) => `${item.label}: ${item.total}`);
        conditions.textContent = selected.length ? selected.join(' | ') : 'Nenhuma comorbidade selecionada.';
      }
    } else {
      if (title) title.textContent = 'Prévia do relatório completo';
      if (description) description.textContent = 'Marque uma ou mais comorbidades para visualizar o recorte filtrado.';
      if (mode) {
        mode.textContent = 'Geral';
        mode.className = 'export-preview-mode export-preview-mode-general';
      }
      if (conditions) conditions.textContent = 'Nenhuma comorbidade selecionada.';
    }
  }

  function setExportPreviewLoading(isLoading) {
    document.querySelectorAll('.export-preview-stats strong').forEach((el) => {
      el.classList.toggle('is-loading', isLoading);
    });
  }

  function updateExportPreview() {
    if (!form?.dataset.previewUrl) return;

    const params = new URLSearchParams();
    getSelectedExportConditions().forEach((option) => params.append('condicoes', option.value));

    exportPreviewController?.abort();
    exportPreviewController = new AbortController();
    setExportPreviewLoading(true);

    const url = params.toString() ? `${form.dataset.previewUrl}?${params}` : form.dataset.previewUrl;
    fetch(url, { signal: exportPreviewController.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then((data) => {
        setExportPreviewLoading(false);
        renderExportPreview(data);
      })
      .catch((error) => {
        if (error?.name === 'AbortError') return;
        setExportPreviewLoading(false);
        const description = document.querySelector('.export-preview-description');
        if (description) description.textContent = 'Não foi possível atualizar a prévia agora.';
      });
  }

  function updateExportCount() {
    const count = getSelectedExportConditions().length;
    const label = document.querySelector('.export-selected-count');
    const submitButton = document.querySelector('.export-selected-submit');

    if (label) label.textContent = `${count} selecionada(s)`;
    if (submitButton) {
      submitButton.disabled = count === 0;
      submitButton.title = count === 0 ? 'Selecione pelo menos uma comorbidade' : '';
    }

    updateExportPreview();
  }

  document.querySelectorAll('.export-condition').forEach((option) => {
    option.addEventListener('change', updateExportCount);
  });

  document.querySelector('.export-select-all')?.addEventListener('click', () => {
    document.querySelectorAll('.export-condition').forEach((option) => {
      option.checked = true;
    });
    updateExportCount();
  });

  document.querySelector('.export-clear')?.addEventListener('click', () => {
    document.querySelectorAll('.export-condition').forEach((option) => {
      option.checked = false;
    });
    updateExportCount();
  });

  form?.addEventListener('submit', (event) => {
    const selected = getSelectedExportConditions();
    event.preventDefault();
    if (selected.length === 0) {
      updateExportCount();
      return;
    }

    const params = new URLSearchParams({ filtrar: '1' });
    selected.forEach((option) => params.append('condicoes', option.value));
    window.location.href = `${form.action}?${params}`;
  });

  // ---------------------------------------------------------------------------
  // Copiar dados do paciente
  // ---------------------------------------------------------------------------
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    return Promise.resolve();
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-copy]');
    if (!button) return;

    copyText(button.dataset.copy).then(() => {
      button.classList.add('is-copied');
      window.setTimeout(() => button.classList.remove('is-copied'), 1500);
    });
  });
})();
