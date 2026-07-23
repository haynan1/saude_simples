(() => {
  const MAIN_SELECTOR = '#app-main';
  const NAV_SELECTOR = '[data-nav-link]';
  const DOWNLOAD_PATHS = ['/exportar/pdf'];
  let isNavigating = false;

  function currentCspNonce() {
    return document.querySelector('script[nonce]')?.nonce || '';
  }

  function isModifiedClick(event) {
    return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0;
  }

  function sameOriginUrl(rawUrl) {
    try {
      const url = new URL(rawUrl, window.location.href);
      return url.origin === window.location.origin ? url : null;
    } catch {
      return null;
    }
  }

  function shouldSkipLink(link, event) {
    if (!link || isModifiedClick(event)) return true;
    if (link.target || link.hasAttribute('download') || link.dataset.noSmooth !== undefined) return true;

    const url = sameOriginUrl(link.href);
    if (!url) return true;
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return true;
    return false;
  }

  function shouldSkipForm(form) {
    const action = sameOriginUrl(form.action || window.location.href);
    if (!action) return true;
    if (form.target || form.dataset.noSmooth !== undefined) return true;
    if ((form.enctype || '').toLowerCase() === 'multipart/form-data') return true;
    return DOWNLOAD_PATHS.some((path) => action.pathname.endsWith(path));
  }

  function buildFormRequest(form, submitter) {
    const method = (form.method || 'GET').toUpperCase();
    const action = sameOriginUrl(form.action || window.location.href);
    const formData = new FormData(form);

    if (submitter?.name) {
      formData.append(submitter.name, submitter.value || '');
    }

    if (method === 'GET') {
      const params = new URLSearchParams(formData);
      for (const [key, value] of [...params.entries()]) {
        if (!value) params.delete(key);
      }
      action.search = params.toString();
      return { url: action, options: { method: 'GET' } };
    }

    return {
      url: action,
      options: {
        method,
        body: formData,
      },
    };
  }

  function setLoading(loading) {
    const main = document.querySelector(MAIN_SELECTOR);
    document.documentElement.classList.toggle('smooth-loading', loading);
    main?.classList.toggle('is-navigating', loading);
  }

  function executeScripts(root) {
    root.querySelectorAll('script').forEach((oldScript) => {
      const script = document.createElement('script');
      for (const attr of oldScript.attributes) {
        script.setAttribute(attr.name, attr.value);
      }
      const nonce = currentCspNonce();
      if (nonce) script.nonce = nonce;
      script.textContent = oldScript.textContent;
      oldScript.replaceWith(script);
    });
  }

  function parseResponseDocument(html) {
    // O HTML completo traz o nonce da nova resposta. Em uma navegação parcial,
    // a política ativa ainda é a da página atual; blocos de estilo globais não
    // serão usados e precisam ser removidos antes do DOMParser para não gerar
    // violações CSP. Scripts pertencentes ao novo conteúdo recebem o nonce atual.
    const withoutGlobalStyles = html.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '');
    const nextDocument = new DOMParser().parseFromString(withoutGlobalStyles, 'text/html');
    const nonce = currentCspNonce();
    if (nonce) {
      nextDocument.querySelectorAll('script[nonce]').forEach((script) => {
        script.nonce = nonce;
      });
    }
    return nextDocument;
  }

  function syncInner(selector, nextDocument) {
    const cur = document.querySelector(selector);
    const next = nextDocument.querySelector(selector);
    if (cur && next && cur.innerHTML !== next.innerHTML) {
      cur.innerHTML = next.innerHTML;
    }
  }

  // Atualiza a "casca" (identidade do ambiente) sem recarregar a página:
  // trocar a classe do .app-shell recolore tudo via tokens CSS, com as
  // transições de 260ms já definidas — entrada/saída da UBS fica fluida.
  function syncShell(nextDocument) {
    const currentShell = document.querySelector('.app-shell');
    const nextShell = nextDocument.querySelector('.app-shell');
    if (!currentShell || !nextShell) return;

    if (currentShell.className !== nextShell.className) {
      currentShell.className = nextShell.className;
    }

    // Rótulo de identidade na sidebar (wrapper Alpine permanece intacto).
    syncInner('[data-shell-brand]', nextDocument);
  }

  function syncNav(nextDocument) {
    const nextLinks = [...nextDocument.querySelectorAll(NAV_SELECTOR)];
    document.querySelectorAll(NAV_SELECTOR).forEach((link) => {
      const url = sameOriginUrl(link.href);
      const nextLink = nextLinks.find((candidate) => {
        const candidateUrl = sameOriginUrl(candidate.href);
        return candidateUrl?.pathname === url?.pathname;
      });
      if (!nextLink) return;

      const isActive = nextLink.classList.contains('nav-active');
      link.classList.toggle('nav-active', isActive);
      link.classList.toggle('text-white', isActive);
    });
  }

  function initNewContent(main) {
    window.applyInputMasks?.(main);
    window.applyWhatsAppLinks?.(main);
    window.applyWhatsAppTemplateEditors?.(main);
    window.Alpine?.initTree?.(main);
    executeScripts(main);
  }

  async function navigate(url, options = {}, updateHistory = true) {
    if (isNavigating) return;
    isNavigating = true;
    setLoading(true);

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'X-Requested-With': 'fetch',
          ...(options.headers || {}),
        },
      });

      const contentType = response.headers.get('content-type') || '';
      if (!response.ok || !contentType.includes('text/html')) {
        window.location.href = response.url || url;
        return;
      }

      const html = await response.text();
      const nextDocument = parseResponseDocument(html);
      const nextMain = nextDocument.querySelector(MAIN_SELECTOR);
      const currentMain = document.querySelector(MAIN_SELECTOR);

      if (!nextMain || !currentMain) {
        window.location.href = response.url || url;
        return;
      }

      document.title = nextDocument.title;
      syncShell(nextDocument);
      syncNav(nextDocument);
      currentMain.replaceWith(nextMain);
      initNewContent(nextMain);

      if (updateHistory) {
        history.pushState({}, '', response.url || url);
      }
      nextMain.scrollIntoView({ block: 'start' });
    } catch {
      window.location.href = url;
    } finally {
      isNavigating = false;
      setLoading(false);
    }
  }

  document.addEventListener('click', (event) => {
    if (!document.querySelector(MAIN_SELECTOR)) return;
    if (event.defaultPrevented) return;
    const link = event.target.closest('a[href]');
    if (shouldSkipLink(link, event)) return;
    const url = sameOriginUrl(link.href);
    if (!url) return;
    event.preventDefault();
    navigate(url);
  });

  document.addEventListener('submit', (event) => {
    if (!document.querySelector(MAIN_SELECTOR)) return;
    if (event.defaultPrevented) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || shouldSkipForm(form)) return;
    event.preventDefault();
    const request = buildFormRequest(form, event.submitter);
    navigate(request.url, request.options);
  });

  window.addEventListener('popstate', () => {
    navigate(window.location.href, {}, false);
  });
})();
