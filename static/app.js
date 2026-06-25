const savedTheme = localStorage.getItem("theme");
const preferredTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
const initialTheme = savedTheme || preferredTheme;

document.documentElement.setAttribute("data-bs-theme", initialTheme);

function updateThemeButton(theme) {
    const button = document.querySelector(".theme-toggle");
    if (!button) return;

    const icon = button.querySelector("i");
    if (icon) {
        icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
    }

    button.title = theme === "dark" ? "Modo claro" : "Modo noturno";
    button.setAttribute("aria-label", theme === "dark" ? "Alternar para modo claro" : "Alternar para modo noturno");
}

updateThemeButton(initialTheme);

document.querySelector(".theme-toggle")?.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-bs-theme") || "light";
    const nextTheme = currentTheme === "dark" ? "light" : "dark";

    document.documentElement.setAttribute("data-bs-theme", nextTheme);
    localStorage.setItem("theme", nextTheme);
    updateThemeButton(nextTheme);
});

let pendingDeleteForm = null;
const confirmDeleteModalElement = document.getElementById("confirmDeleteModal");
const confirmDeleteMessage = document.getElementById("confirmDeleteMessage");
const confirmDeleteButton = document.getElementById("confirmDeleteButton");
const confirmDeleteModal = confirmDeleteModalElement ? new bootstrap.Modal(confirmDeleteModalElement) : null;

document.querySelectorAll(".confirm-delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        pendingDeleteForm = form;

        if (confirmDeleteMessage) {
            confirmDeleteMessage.textContent = form.dataset.confirmMessage || "Deseja excluir este registro?";
        }

        confirmDeleteModal?.show();
    });
});

confirmDeleteButton?.addEventListener("click", () => {
    if (!pendingDeleteForm) return;

    confirmDeleteButton.disabled = true;
    confirmDeleteButton.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Excluindo';
    pendingDeleteForm.submit();
});

confirmDeleteModalElement?.addEventListener("hidden.bs.modal", () => {
    pendingDeleteForm = null;
    if (!confirmDeleteButton) return;

    confirmDeleteButton.disabled = false;
    confirmDeleteButton.innerHTML = '<i class="bi bi-trash"></i> Excluir';
});

document.querySelectorAll(".collapse-toggle").forEach((button) => {
    const label = button.querySelector("span");
    const target = document.querySelector(button.dataset.bsTarget);
    if (!label || !target) return;

    target.addEventListener("shown.bs.collapse", () => {
        label.textContent = button.dataset.openLabel || "Ocultar";
    });

    target.addEventListener("hidden.bs.collapse", () => {
        label.textContent = button.dataset.closedLabel || "Mostrar";
    });
});

function formatCpfOrCns(value) {
    const digits = value.replace(/\D/g, "").slice(0, 15);

    if (digits.length <= 11) {
        if (digits.length <= 3) return digits;
        if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`;
        if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`;
        return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`;
    }

    const parts = [
        digits.slice(0, 3),
        digits.slice(3, 7),
        digits.slice(7, 11),
        digits.slice(11, 15),
    ].filter(Boolean);

    return parts.join(" ");
}

document.querySelectorAll(".cpf-cns-mask").forEach((field) => {
    field.value = formatCpfOrCns(field.value);

    field.addEventListener("input", () => {
        field.value = formatCpfOrCns(field.value);
    });
});

function formatPhone(value) {
    const digits = value.replace(/\D/g, "").slice(0, 11);

    if (digits.length <= 2) return digits;
    if (digits.length <= 6) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
    if (digits.length <= 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
    return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
}

document.querySelectorAll(".phone-mask").forEach((field) => {
    field.value = formatPhone(field.value);

    field.addEventListener("input", () => {
        field.value = formatPhone(field.value);
    });
});

function updateHealthDropdown(dropdown) {
    const label = dropdown.querySelector(".health-dropdown-label");
    const selected = [...dropdown.querySelectorAll(".health-option:checked")].map((item) => item.dataset.label || item.value);
    if (!label) return;

    if (selected.length === 0) {
        label.textContent = "Selecionar condições";
    } else if (selected.length === 1) {
        label.textContent = selected[0];
    } else {
        label.textContent = `${selected.length} condições selecionadas`;
    }
}

document.querySelectorAll(".health-dropdown").forEach((dropdown) => {
    updateHealthDropdown(dropdown);

    dropdown.querySelectorAll(".health-option").forEach((option) => {
        option.addEventListener("change", () => updateHealthDropdown(dropdown));
    });
});

let exportPreviewController = null;

function getSelectedExportConditions() {
    return [...document.querySelectorAll(".export-condition:checked")];
}

function renderExportPreview(data) {
    const title = document.querySelector(".export-preview-title");
    const description = document.querySelector(".export-preview-description");
    const mode = document.querySelector(".export-preview-mode");
    const conditions = document.querySelector(".export-preview-conditions");

    Object.entries(data.stats || {}).forEach(([key, value]) => {
        const target = document.querySelector(`[data-preview-stat="${key}"]`);
        if (target) target.textContent = value ?? 0;
    });

    if (data.modo === "filtrado") {
        if (title) title.textContent = "Prévia do relatório filtrado";
        if (description) description.textContent = "A exportação vai incluir somente pacientes com pelo menos uma das comorbidades selecionadas.";
        if (mode) {
            mode.innerHTML = '<i class="bi bi-funnel"></i> Filtrado';
            mode.className = "export-preview-mode export-preview-mode-filtered";
        }
        if (conditions) {
            const selected = (data.condicoes || []).map((item) => `${item.label}: ${item.total}`);
            conditions.textContent = selected.length ? selected.join(" | ") : "Nenhuma comorbidade selecionada.";
        }
    } else {
        if (title) title.textContent = "Prévia do relatório completo";
        if (description) description.textContent = "Marque uma ou mais comorbidades para visualizar o recorte filtrado.";
        if (mode) {
            mode.innerHTML = '<i class="bi bi-layers"></i> Geral';
            mode.className = "export-preview-mode export-preview-mode-general";
        }
        if (conditions) conditions.textContent = "Nenhuma comorbidade selecionada.";
    }
}

function updateExportPreview() {
    const form = document.getElementById("exportFilteredPdfForm");
    if (!form?.dataset.previewUrl) return;

    const params = new URLSearchParams();
    getSelectedExportConditions().forEach((option) => params.append("condicoes", option.value));

    if (exportPreviewController) {
        exportPreviewController.abort();
    }
    exportPreviewController = new AbortController();

    const url = params.toString() ? `${form.dataset.previewUrl}?${params}` : form.dataset.previewUrl;
    fetch(url, { signal: exportPreviewController.signal })
        .then((response) => response.ok ? response.json() : Promise.reject())
        .then(renderExportPreview)
        .catch((error) => {
            if (error?.name === "AbortError") return;
            const description = document.querySelector(".export-preview-description");
            if (description) description.textContent = "Não foi possível atualizar a prévia agora.";
        });
}

function updateExportCount() {
    const count = getSelectedExportConditions().length;
    const label = document.querySelector(".export-selected-count");
    const submitButton = document.querySelector(".export-selected-submit");

    if (label) {
        label.textContent = `${count} selecionada(s)`;
    }

    if (submitButton) {
        submitButton.disabled = count === 0;
        submitButton.title = count === 0 ? "Selecione pelo menos uma comorbidade" : "";
    }

    updateExportPreview();
}

document.querySelectorAll(".export-condition").forEach((option) => {
    option.addEventListener("change", updateExportCount);
});

document.querySelector(".export-select-all")?.addEventListener("click", () => {
    document.querySelectorAll(".export-condition").forEach((option) => {
        option.checked = true;
    });
    updateExportCount();
});

document.querySelector(".export-clear")?.addEventListener("click", () => {
    document.querySelectorAll(".export-condition").forEach((option) => {
        option.checked = false;
    });
    updateExportCount();
});

document.getElementById("exportFilteredPdfForm")?.addEventListener("submit", (event) => {
    const selected = getSelectedExportConditions();
    if (selected.length === 0) {
        event.preventDefault();
        updateExportCount();
        return;
    }

    event.preventDefault();
    const params = new URLSearchParams({ filtrar: "1" });
    selected.forEach((option) => params.append("condicoes", option.value));
    window.location.href = `${event.currentTarget.action}?${params}`;
});

updateExportCount();

function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
    return Promise.resolve();
}

document.querySelectorAll(".copy-patient").forEach((button) => {
    button.addEventListener("click", () => {
        const originalText = button.textContent;

        copyText(button.dataset.copy).then(() => {
            button.textContent = "Copiado";
            button.classList.remove("btn-outline-primary");
            button.classList.add("btn-success");

            window.setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove("btn-success");
                button.classList.add("btn-outline-primary");
            }, 1500);
        });
    });
});
