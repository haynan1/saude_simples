(() => {
  function onlyDigits(value) {
    return String(value || '').replace(/\D/g, '');
  }

  function formatCpf(value) {
    const digits = onlyDigits(value).slice(0, 11);
    return digits
      .replace(/^(\d{3})(\d)/, '$1.$2')
      .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
      .replace(/^(\d{3})\.(\d{3})\.(\d{3})(\d)/, '$1.$2.$3-$4');
  }

  function formatCns(value) {
    const digits = onlyDigits(value).slice(0, 15);
    return digits
      .replace(/^(\d{3})(\d)/, '$1 $2')
      .replace(/^(\d{3})\s(\d{4})(\d)/, '$1 $2 $3')
      .replace(/^(\d{3})\s(\d{4})\s(\d{4})(\d)/, '$1 $2 $3 $4');
  }

  function formatCpfOrCns(value) {
    const digits = onlyDigits(value).slice(0, 15);
    if (digits.length > 11) return formatCns(digits);
    return formatCpf(digits);
  }

  function formatPatientSearch(value) {
    const text = String(value || '');
    // Campo multiuso: nome, CPF, CNS ou data. So aplicamos mascara de documento
    // quando o valor e claramente numerico; nome (com letras) passa intacto.
    if (!/^[\d.\-\s\/]*$/.test(text)) return text;
    // Data sendo digitada: dd/mm/aaaa (com barras) ou aaaa-mm-dd (ano + hifen).
    // Nao viram documento.
    if (text.includes('/')) return text;
    if (/^\d{4}-/.test(text)) return text;

    const digits = onlyDigits(text);
    // Permite digitar um ano de 4 digitos (inicio de data) antes de assumir que
    // e um documento — exceto quando o valor ja carrega a mascara de CPF, para
    // manter a formatacao estavel durante o backspace.
    if (digits.length < 5 && !text.includes('.')) return text;

    // Progressivo: ate 11 digitos formata como CPF (000.000.000-00); acima disso
    // como CNS (000 0000 0000 000), limitado a 15 digitos — a quantidade certa
    // de cada documento, com o excedente descartado automaticamente.
    return formatCpfOrCns(digits);
  }

  function formatPhone(value) {
    const digits = onlyDigits(value).slice(0, 11);
    if (digits.length <= 10) {
      return digits
        .replace(/^(\d{2})(\d)/, '($1) $2')
        .replace(/(\d{4})(\d)/, '$1-$2');
    }
    return digits
      .replace(/^(\d{2})(\d)/, '($1) $2')
      .replace(/(\d{5})(\d)/, '$1-$2');
  }

  function isValidDateParts(year, month, day) {
    const parsed = new Date(Date.UTC(year, month - 1, day));
    return parsed.getUTCFullYear() === year
      && parsed.getUTCMonth() === month - 1
      && parsed.getUTCDate() === day;
  }

  function toIsoDate(year, month, day) {
    if (!isValidDateParts(year, month, day)) return '';
    return [
      String(year).padStart(4, '0'),
      String(month).padStart(2, '0'),
      String(day).padStart(2, '0'),
    ].join('-');
  }

  function normalizeDateValue(value) {
    const text = String(value || '').trim();
    if (!text) return '';

    let match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
      return toIsoDate(Number(match[1]), Number(match[2]), Number(match[3]));
    }

    match = text.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);
    if (match) {
      return toIsoDate(Number(match[3]), Number(match[2]), Number(match[1]));
    }

    const digits = onlyDigits(text);
    if (digits.length === 8) {
      const firstFour = Number(digits.slice(0, 4));
      if (firstFour >= 1900 && firstFour <= 2200) {
        return toIsoDate(firstFour, Number(digits.slice(4, 6)), Number(digits.slice(6, 8)));
      }
      return toIsoDate(Number(digits.slice(4, 8)), Number(digits.slice(2, 4)), Number(digits.slice(0, 2)));
    }

    return '';
  }

  function maskFor(input) {
    const name = (input.name || '').toLowerCase();
    const id = (input.id || '').toLowerCase();
    const autocomplete = input.autocomplete || '';

    // Campo multiuso do Saúde Simples: aceita CPF (11 dígitos) ou CNS (15).
    if (input.dataset.mask === 'cpf-cns') return formatCpfOrCns;
    if (name.includes('cns') || id.includes('cns')) return formatCns;
    if (name.includes('cpf') || id.includes('cpf')) return formatCpf;
    if (input.type === 'tel' || name.includes('phone') || name.includes('telefone') || autocomplete === 'tel') return formatPhone;
    return null;
  }

  function applyMask(input) {
    const formatter = maskFor(input);
    if (!formatter) return;

    const update = () => {
      input.value = formatter(input.value);
    };

    update();
    input.addEventListener('input', update);
    input.addEventListener('blur', update);
  }

  function applyDatePaste(input) {
    if (input.dataset.datePasteReady === 'true') return;
    input.dataset.datePasteReady = 'true';

    input.addEventListener('paste', (event) => {
      const pasted = event.clipboardData?.getData('text') || '';
      const normalized = normalizeDateValue(pasted);
      if (!normalized) return;

      event.preventDefault();
      input.value = normalized;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  function applyPatientSearchMask(input) {
    if (input.dataset.patientSearchMaskReady === 'true') return;
    input.dataset.patientSearchMaskReady = 'true';

    const update = () => {
      const formatted = formatPatientSearch(input.value);
      if (formatted === input.value) return;
      input.value = formatted;
      input.setSelectionRange?.(formatted.length, formatted.length);
    };

    update();
    // Captura garante que Alpine e a busca AJAX recebam o valor ja formatado.
    input.addEventListener('input', update, { capture: true });
    input.addEventListener('blur', update);
  }

  function initMasks(root = document) {
    root
      .querySelectorAll('input[name*="cpf"], input[name*="cns"], input[name*="phone"], input[name*="telefone"], input[data-mask], input[type="tel"]')
      .forEach(applyMask);
    root
      .querySelectorAll('input[type="date"]')
      .forEach(applyDatePaste);
    root
      .querySelectorAll('input[data-patient-search]')
      .forEach(applyPatientSearchMask);
  }

  document.addEventListener('DOMContentLoaded', () => initMasks());
  window.applyInputMasks = initMasks;
  window.formatPatientSearchValue = formatPatientSearch;
})();
