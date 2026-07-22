document.addEventListener('alpine:init', () => {
  Alpine.data('appShell', () => ({
    open: false,
    get sidebarCollapsed() {
      return this.$store.ui.sidebarCollapsed;
    },
    set sidebarCollapsed(value) {
      this.$store.ui.setSidebarCollapsed(value);
    },
  }));

  Alpine.data('flashMessage', () => ({
    scheduleRemoval() {
      setTimeout(() => this.$el.remove(), 3000);
    },
    remove() {
      this.$el.remove();
    },
  }));

  // Seletor de condições de saúde no formulário de paciente. Getters expõem
  // estado derivado como propriedades simples porque o build CSP do Alpine
  // não avalia expressões inline complexas nos atributos.
  Alpine.data('healthConditions', (initialCount) => ({
    open: false,
    count: initialCount || 0,
    toggle() {
      this.open = !this.open;
    },
    recount() {
      this.count = this.$root.querySelectorAll('input[name="condicoes_saude"]:checked').length;
    },
    get summary() {
      if (this.count === 0) return 'Nenhuma condição selecionada';
      if (this.count === 1) return '1 condição selecionada';
      return this.count + ' condições selecionadas';
    },
    get toggleLabel() {
      return this.open ? 'Ocultar lista' : 'Selecionar condições';
    },
  }));
});
