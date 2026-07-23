"""Testes end-to-end da navegação sem recarregar a página (smooth-navigation).

Diferente do resto da suíte, que usa o `test_client` do Flask (sem navegador,
sem JavaScript), estes testes sobem o servidor de verdade e dirigem um Chromium
real com o Playwright. É a única forma de provar o que o `test_client` não
alcança: que clicar num link troca apenas o `#app-main` via `fetch`, sem reload,
e que o diálogo de confirmação intercepta ações destrutivas.

O truque central: antes de navegar, gravamos `window.__spa` na página. Se a
navegação foi PARCIAL (fetch + troca de nó), o objeto `window` sobrevive e o
marcador continua lá. Se houve reload COMPLETO, a `window` é recriada e o
marcador some. É esse marcador que separa uma coisa da outra — a URL, sozinha,
fica igual nos dois casos.

Sem o navegador do Playwright instalado, o módulo inteiro é pulado (não quebra a
suíte). Para instalar: `python -m playwright install chromium`.
"""
import os
import threading

import pytest
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

import db
from tests.conftest import SENHA_TESTE


def _chromium_instalado():
    """True só quando o binário do Chromium do Playwright já foi baixado."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            caminho = p.chromium.executable_path
        return bool(caminho) and os.path.exists(caminho)
    except Exception:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _chromium_instalado(),
        reason="Navegador do Playwright ausente — rode: python -m playwright install chromium",
    ),
]


# ---------------------------------------------------------------------------
# Infraestrutura: servidor Flask de verdade + navegador Chromium
# ---------------------------------------------------------------------------
@pytest.fixture()
def servidor(tmp_path):
    """Sobe o app num servidor WSGI real, numa thread, com banco isolado e
    senha já configurada. Devolve a URL base (porta escolhida pelo SO)."""
    db.DATABASE = str(tmp_path / "e2e.db")
    db.BACKUP_DIR = str(tmp_path / "backups")
    db.INSTANCE_DIR = str(tmp_path / "instance")
    db.SETUP_TOKEN_PATH = str(tmp_path / "instance" / "setup_token")
    db.init_db()
    db.set_senha_hash(generate_password_hash(SENHA_TESTE))

    import app as app_module

    # CSRF fica de fora: aqui o alvo é a navegação no navegador, não o token
    # (isso já é coberto em test_seguranca.py). Rate limit e o marcador diário
    # do perfil são zerados para o teste começar do zero.
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    app_module._login_attempts.clear()
    app_module._perfil_registrado_dia = None

    servidor = make_server("127.0.0.1", 0, app_module.app, threaded=True)
    porta = servidor.server_address[1]
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{porta}"
    finally:
        servidor.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def _playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def navegador(_playwright):
    browser = _playwright.chromium.launch()
    yield browser
    browser.close()


@pytest.fixture()
def pagina(navegador):
    """Contexto de navegador limpo por teste (sem cookies/estado vazando)."""
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    try:
        yield pagina
    finally:
        contexto.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _entrar(pagina, servidor):
    """Faz login pela tela real e espera cair no painel autenticado."""
    pagina.goto(f"{servidor}/login")
    pagina.fill("#senha", SENHA_TESTE)
    pagina.click("button.login-button")
    pagina.wait_for_url(f"{servidor}/")
    pagina.wait_for_selector("#app-main")


def _marcar_janela(pagina):
    """Deixa uma marca no objeto window. Sobrevive à troca parcial; não
    sobrevive a um reload completo."""
    pagina.evaluate("window.__spa = 'vivo'")


def _janela_sobreviveu(pagina):
    return pagina.evaluate("window.__spa") == "vivo"


def _semear_casa_com_paciente(nome="Fulano De Tal"):
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO casas (id, numero_casa, endereco, tipo_imovel) "
        "VALUES (1, 1, 'Rua A, 1', 'domicilio')"
    )
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, nome, status) VALUES (1, 1, ?, 'ativo')",
        (nome,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------
def test_login_leva_ao_painel(pagina, servidor):
    _entrar(pagina, servidor)
    assert pagina.locator("#app-main").is_visible()
    # A sidebar (fora do #app-main) está presente — a casca autenticada montou.
    assert pagina.locator('[data-nav-link][href$="/pacientes"]').count() == 1


def test_navegacao_por_link_e_parcial(pagina, servidor):
    """Clicar num link do menu troca só o conteúdo — a window é preservada,
    prova de que NÃO houve reload da página inteira."""
    _entrar(pagina, servidor)
    _marcar_janela(pagina)

    pagina.click('[data-nav-link][href$="/pacientes"]')
    pagina.wait_for_url("**/pacientes")

    assert _janela_sobreviveu(pagina)  # troca parcial, sem reload
    assert "Pacientes" in pagina.locator("#app-main").inner_text()


def test_submit_get_e_parcial_e_atualiza_conteudo(pagina, servidor):
    """Uma busca (form GET) também navega parcial e reflete o resultado no
    #app-main, sem recarregar a página."""
    _semear_casa_com_paciente(nome="Joaquina Da Busca")
    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/pacientes")
    pagina.wait_for_selector("#app-main")
    _marcar_janela(pagina)

    pagina.fill('input[name="busca"]', "Joaquina")
    pagina.press('input[name="busca"]', "Enter")
    pagina.wait_for_url("**/pacientes?*busca=Joaquina*")

    assert _janela_sobreviveu(pagina)
    assert "Joaquina Da Busca" in pagina.locator("#app-main").inner_text()


def test_logout_no_smooth_recarrega_a_pagina(pagina, servidor):
    """O form de logout tem data-no-smooth: precisa ser navegação completa
    (a window é recriada), senão a sessão não é descartada de fato."""
    _entrar(pagina, servidor)
    _marcar_janela(pagina)

    pagina.click('aside form[action$="/logout"] button[type="submit"]')
    pagina.wait_for_url("**/login")

    assert pagina.evaluate("window.__spa") is None  # reload completo


def test_voltar_do_navegador_e_parcial(pagina, servidor):
    """O botão Voltar do navegador (popstate) também usa a troca parcial —
    volta ao painel sem reload."""
    _entrar(pagina, servidor)
    _marcar_janela(pagina)

    pagina.click('[data-nav-link][href$="/pacientes"]')
    pagina.wait_for_url("**/pacientes")
    pagina.go_back()
    pagina.wait_for_url(f"{servidor}/")

    assert _janela_sobreviveu(pagina)


def test_dialogo_de_confirmacao_intercepta_exclusao(pagina, servidor):
    """Ação destrutiva (excluir paciente) abre o diálogo de confirmação em vez
    de disparar na hora; cancelar não exclui nada."""
    _semear_casa_com_paciente(nome="Nao Me Exclua")
    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/casa/1")
    pagina.wait_for_selector("#app-main")

    # O submit do form com data-confirm é interceptado — nada é enviado ainda.
    pagina.click('form[action$="/paciente/1/excluir"] button[type="submit"]')
    dialogo = pagina.locator("#confirm-dialog")
    dialogo.wait_for(state="visible")
    assert dialogo.is_visible()

    # Cancelar fecha o diálogo e mantém o paciente — nenhuma requisição saiu.
    # (O botão, não o backdrop, que também é [data-confirm-cancel] mas fica
    # atrás do painel.)
    pagina.locator("#confirm-dialog button[data-confirm-cancel]").click()
    dialogo.wait_for(state="hidden")
    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes WHERE id = 1").fetchone()["c"]
    conn.close()
    assert total == 1


def test_dialogo_confirmado_executa_exclusao(pagina, servidor):
    """Confirmando o diálogo, a exclusão realmente acontece: o paciente vai
    para a lixeira (some da tabela ativa)."""
    _semear_casa_com_paciente(nome="Pode Excluir")
    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/casa/1")
    pagina.wait_for_selector("#app-main")

    pagina.click('form[action$="/paciente/1/excluir"] button[type="submit"]')
    pagina.locator("#confirm-dialog").wait_for(state="visible")
    pagina.locator("#confirm-dialog [data-confirm-submit]").click()

    # A exclusão envia o form (navegação parcial) e mostra o flash de sucesso.
    pagina.wait_for_selector("text=Lixeira")
    conn = db.get_db_connection()
    ativos = conn.execute("SELECT COUNT(*) AS c FROM pacientes WHERE id = 1").fetchone()["c"]
    na_lixeira = conn.execute(
        "SELECT COUNT(*) AS c FROM lixeira_pacientes WHERE id = 1"
    ).fetchone()["c"]
    conn.close()
    assert ativos == 0
    assert na_lixeira == 1
