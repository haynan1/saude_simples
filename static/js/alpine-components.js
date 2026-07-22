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

  // Upload nas telas de importação (banco .db, CSV do e-SUS): mostra o nome do
  // arquivo escolhido e mantém o botão de envio travado até existir arquivo.
  Alpine.data('dbImport', (placeholder) => ({
    fileName: '',
    placeholder: placeholder || 'Escolher arquivo .db',
    onChange() {
      const file = this.$refs.input.files[0];
      this.fileName = file ? file.name : '';
    },
    get label() {
      return this.fileName || this.placeholder;
    },
    get noFile() {
      return this.fileName === '';
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
