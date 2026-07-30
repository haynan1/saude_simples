import os
import sys
from io import BytesIO

import pytest
from pypdf import PdfReader

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A chave precisa existir ANTES do import do app (o módulo valida no import).
os.environ.setdefault("SAUDE_SIMPLES_SECRET_KEY", "chave-de-teste-nao-usar-em-producao-1234")

import db  # noqa: E402

SENHA_TESTE = "senha-de-teste-123"


@pytest.fixture()
def app_sem_senha(tmp_path):
    """App recém-instalado: banco isolado criado, nenhuma senha configurada."""
    import app as app_module

    db.DATABASE = str(tmp_path / "test.db")
    db.BACKUP_DIR = str(tmp_path / "backups")
    db.INSTANCE_DIR = str(tmp_path / "instance")
    db.SETUP_TOKEN_PATH = str(tmp_path / "instance" / "setup_token")
    db.init_db()

    app_module._login_attempts.clear()
    # Cada teste tem banco novo — o marcador diário do perfil não pode vazar
    # de um teste para o outro.
    app_module._perfil_registrado_dia = None
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    yield app_module.app
    app_module.app.config["WTF_CSRF_ENABLED"] = False


@pytest.fixture()
def app(app_sem_senha):
    """App já configurado (senha definida) — o estado normal de operação."""
    from werkzeug.security import generate_password_hash

    db.set_senha_hash(generate_password_hash(SENHA_TESTE))
    return app_sem_senha


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def logged_client(client):
    resp = client.post("/login", data={"senha": SENHA_TESTE})
    assert resp.status_code == 302
    return client


def texto_pdf(data):
    """Texto de todas as páginas do PDF, na ordem.

    Extração de verdade (pypdf), não regex sobre os content streams: o decoder
    caseiro perdia páginas em silêncio, e afirmação negativa sobre página que
    não foi lida passa por acidente."""
    leitor = PdfReader(BytesIO(data))
    return "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)


def criar_quadra(client, numero="1"):
    return client.post("/quadra/nova", data={"numero_quadra": numero})


def criar_casa(client, endereco="Rua A, 1", numero="1", quadra_id=""):
    return client.post(
        "/casa/nova", data={"endereco": endereco, "numero_casa": numero, "quadra_id": quadra_id}
    )


def criar_paciente(client, casa_id=1, **overrides):
    data = {
        "nome": "Paciente Teste",
        "cpf": "12345678901",
        "telefone": "63999998888",
        "data_nascimento": "1990-05-10",
        "sexo": "Feminino",
        "observacao": "",
    }
    data.update(overrides)
    return client.post(f"/casa/{casa_id}/paciente/novo", data=data)


# ---------------------------------------------------------------------------
# Infraestrutura end-to-end (Playwright)
#
# Mora aqui, e não dentro de um módulo de teste, porque `_playwright` é de
# escopo de sessão: definido num módulo e importado noutro, o pytest registra
# DUAS instâncias e a segunda chama sync_playwright() com o loop da primeira
# ainda rodando — "Sync API inside the asyncio loop". No conftest existe uma só,
# compartilhada por todos os arquivos e2e.
# ---------------------------------------------------------------------------
def chromium_instalado():
    """True só quando o binário do Chromium do Playwright já foi baixado."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            caminho = p.chromium.executable_path
        return bool(caminho) and os.path.exists(caminho)
    except Exception:
        return False


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


@pytest.fixture()
def servidor(tmp_path):
    """Sobe o app num servidor WSGI real, numa thread, com banco isolado e
    senha já configurada. Devolve a URL base (porta escolhida pelo SO)."""
    import threading

    from werkzeug.security import generate_password_hash
    from werkzeug.serving import make_server

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


def entrar(pagina, servidor):
    """Faz login pela tela real e espera cair no painel autenticado."""
    pagina.goto(f"{servidor}/login")
    pagina.fill("#senha", SENHA_TESTE)
    pagina.click("button.login-button")
    pagina.wait_for_url(f"{servidor}/")
    pagina.wait_for_selector("#app-main")
