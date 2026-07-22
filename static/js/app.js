// Interações próprias do Saúde Simples: página de exportação em PDF (prévia
// ao vivo) e cópia rápida dos dados do paciente. Tudo por delegação no
// document — os handlers sobrevivem às trocas parciais de página do
// smooth-navigation. Carregado como arquivo externo por exigência da CSP.
(() => {
  // ---------------------------------------------------------------------------
  // Página "Exportar PDF"
  // ---------------------------------------------------------------------------
  let exportPreviewController = null;

  function exportForm() {
    return document.getElementById('exportFilteredPdfForm');
  }

  function getSelectedExportConditions() {
    return [...document.querySelectorAll('.export-condition:checked')];
  }

  function getSelectedExportGroups() {
    return [...document.querySelectorAll('.export-group:checked')];
  }

  function renderExportPreview(data) {
    const title = document.querySelector('.export-preview-title');
    const description = document.querySelector('.export-preview-description');
    const mode = document.querySelector('.export-preview-mode');
    const groups = document.querySelector('.export-preview-groups');
    const conditions = document.querySelector('.export-preview-conditions');

    Object.entries(data.stats || {}).forEach(([key, value]) => {
      const target = document.querySelector(`[data-preview-stat="${key}"]`);
      if (target) target.textContent = value ?? 0;
    });

    if (groups) {
      const selected = (data.grupos || []).map((item) => `${item.label}: ${item.total}`);
      groups.textContent = selected.length ? `Grupos — ${selected.join(' | ')}` : 'Nenhum grupo selecionado.';
    }

    if (data.modo === 'filtrado') {
      if (title) title.textContent = 'Prévia do relatório filtrado';
      if (description) description.textContent = 'A exportação vai incluir somente os pacientes do recorte selecionado.';
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
      if (description) description.textContent = 'Marque grupos ou comorbidades para visualizar o recorte filtrado.';
      if (mode) {
        mode.textContent = 'Geral';
        mode.className = 'export-preview-mode export-preview-mode-general';
      }
      if (conditions) conditions.textContent = 'Nenhuma comorbidade selecionada.';
    }
  }

  function setExportPreviewLoading(isLoading) {
    document.querySelectorAll('[data-preview-stat]').forEach((el) => {
      el.classList.toggle('is-loading', isLoading);
    });
  }

  function updateExportPreview() {
    const form = exportForm();
    if (!form?.dataset.previewUrl) return;

    const params = new URLSearchParams();
    getSelectedExportGroups().forEach((option) => params.append('grupos', option.value));
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
    if (!exportForm()) return;

    const conditionCount = getSelectedExportConditions().length;
    const groupCount = getSelectedExportGroups().length;
    const total = conditionCount + groupCount;
    const label = document.querySelector('.export-selected-count');
    const groupLabel = document.querySelector('.export-group-count');
    const submitButton = document.querySelector('.export-selected-submit');

    if (label) label.textContent = `${conditionCount} selecionada(s)`;
    if (groupLabel) groupLabel.textContent = `${groupCount} selecionado(s)`;
    if (submitButton) {
      submitButton.disabled = total === 0;
      submitButton.title = total === 0 ? 'Selecione pelo menos um grupo ou comorbidade' : '';
      // O CTA diz exatamente o que vai acontecer.
      submitButton.textContent = total > 0 ? `Exportar recorte (${total})` : 'Exportar recorte';
    }

    updateExportPreview();
  }

  document.addEventListener('change', (event) => {
    if (event.target.closest('.export-condition') || event.target.closest('.export-group')) {
      updateExportCount();
    }
  });

  document.addEventListener('click', (event) => {
    if (event.target.closest('.export-select-all')) {
      document.querySelectorAll('.export-condition').forEach((option) => {
        option.checked = true;
      });
      updateExportCount();
      return;
    }
    if (event.target.closest('.export-clear')) {
      document.querySelectorAll('.export-condition').forEach((option) => {
        option.checked = false;
      });
      updateExportCount();
    }
  });

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (form.id !== 'exportFilteredPdfForm') return;

    event.preventDefault();
    const selectedGroups = getSelectedExportGroups();
    const selectedConditions = getSelectedExportConditions();
    if (selectedGroups.length === 0 && selectedConditions.length === 0) {
      updateExportCount();
      return;
    }

    const params = new URLSearchParams({ filtrar: '1' });
    selectedGroups.forEach((option) => params.append('grupos', option.value));
    selectedConditions.forEach((option) => params.append('condicoes', option.value));
    window.location.href = `${form.action}?${params}`;
  });

  // Prévia inicial: no carregamento completo e, via window.initExportPage,
  // quando o smooth-navigation troca para a página de exportação (o script
  // inline do template é reexecutado a cada troca).
  window.initExportPage = updateExportCount;
  document.addEventListener('DOMContentLoaded', updateExportCount);

  // ---------------------------------------------------------------------------
  // Modal "Filtrar casas" (painel) — delegação: o markup vive dentro do
  // #app-main e é recriado a cada navegação suave.
  // ---------------------------------------------------------------------------
  function filterDialog() {
    return document.getElementById('filter-dialog');
  }

  function openFilterDialog() {
    const dialog = filterDialog();
    if (!dialog) return;
    dialog.hidden = false;
    dialog.setAttribute('aria-hidden', 'false');
    document.body.classList.add('confirm-dialog-open');
    requestAnimationFrame(() => dialog.classList.add('is-visible'));
  }

  function closeFilterDialog() {
    const dialog = filterDialog();
    if (!dialog || dialog.hidden) return;
    dialog.classList.remove('is-visible');
    dialog.hidden = true;
    dialog.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('confirm-dialog-open');
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-filter-open]')) {
      event.preventDefault();
      openFilterDialog();
      return;
    }
    if (event.target.closest('[data-filter-close]')) {
      closeFilterDialog();
      return;
    }
    // Link dentro do modal (ex.: "Limpar filtro"): a navegação suave troca o
    // conteúdo sem recarregar — libera o scroll travado pelo overlay.
    if (event.target.closest('#filter-dialog a')) {
      document.body.classList.remove('confirm-dialog-open');
    }
  });

  // Aplicar filtro: o form GET é levado pelo smooth-navigation; o modal some
  // junto com o conteúdo antigo, então só o scroll precisa ser destravado.
  document.addEventListener('submit', (event) => {
    if (event.target.closest('#filter-dialog')) {
      document.body.classList.remove('confirm-dialog-open');
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeFilterDialog();
  });

  // ---------------------------------------------------------------------------
  // Modal "Transferir" (paciente ou família) — um único modal por página; o
  // botão que abre define o destino do POST e o título via data-attributes.
  // ---------------------------------------------------------------------------
  function transferDialog() {
    return document.getElementById('transfer-dialog');
  }

  function openTransferDialog(trigger) {
    const dialog = transferDialog();
    if (!dialog) return;

    const form = dialog.querySelector('[data-transfer-form]');
    if (form) {
      form.setAttribute('action', trigger.dataset.transferAction || '');
      const select = form.querySelector('select[name="casa_destino_id"]');
      if (select) select.value = '';
    }
    const title = dialog.querySelector('[data-transfer-title-target]');
    if (title) title.textContent = trigger.dataset.transferTitle || 'Transferir';

    dialog.hidden = false;
    dialog.setAttribute('aria-hidden', 'false');
    document.body.classList.add('confirm-dialog-open');
    requestAnimationFrame(() => dialog.classList.add('is-visible'));
  }

  function closeTransferDialog() {
    const dialog = transferDialog();
    if (!dialog || dialog.hidden) return;
    dialog.classList.remove('is-visible');
    dialog.hidden = true;
    dialog.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('confirm-dialog-open');
  }

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-transfer-open]');
    if (trigger) {
      event.preventDefault();
      openTransferDialog(trigger);
      return;
    }
    if (event.target.closest('[data-transfer-close]')) {
      closeTransferDialog();
      return;
    }
    // Link dentro do modal (ex.: "Cadastrar casa"): navegação suave troca o
    // conteúdo sem recarregar — libera o scroll travado pelo overlay.
    if (event.target.closest('#transfer-dialog a')) {
      document.body.classList.remove('confirm-dialog-open');
    }
  });

  // O POST é levado pelo smooth-navigation; o modal some junto com o conteúdo
  // antigo, então só o scroll precisa ser destravado.
  document.addEventListener('submit', (event) => {
    if (event.target.closest('#transfer-dialog')) {
      document.body.classList.remove('confirm-dialog-open');
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeTransferDialog();
  });

  // ---------------------------------------------------------------------------
  // Seleção em massa (lista de pacientes) — os checkboxes das linhas pertencem
  // ao form #bulk-form via form=""; a barra aparece quando há seleção.
  // ---------------------------------------------------------------------------
  function bulkForm() {
    return document.getElementById('bulk-form');
  }

  function updateBulkBar() {
    const bar = bulkForm();
    if (!bar) return;

    const checks = [...document.querySelectorAll('[data-bulk-check]')];
    const count = checks.filter((check) => check.checked).length;

    const label = bar.querySelector('[data-bulk-count]');
    if (label) label.textContent = count === 1 ? '1 selecionado' : `${count} selecionados`;
    bar.dataset.confirmTitle = `Alterar situação de ${count} paciente(s)?`;
    bar.hidden = count === 0;

    const all = document.querySelector('[data-bulk-check-all]');
    if (all) {
      all.checked = count > 0 && count === checks.length;
      all.indeterminate = count > 0 && count < checks.length;
    }
  }

  document.addEventListener('change', (event) => {
    if (event.target.closest('[data-bulk-check-all]')) {
      const marcado = event.target.checked;
      document.querySelectorAll('[data-bulk-check]').forEach((check) => {
        check.checked = marcado;
      });
      updateBulkBar();
      return;
    }
    if (event.target.closest('[data-bulk-check]')) updateBulkBar();
  });

  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-bulk-clear]')) {
      document.querySelectorAll('[data-bulk-check]').forEach((check) => {
        check.checked = false;
      });
      updateBulkBar();
    }
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
