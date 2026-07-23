"""Testes de segurança — auth, CSRF, rate limit, open redirect, XSS, headers.

Estes testes são a especificação executável das propriedades de segurança do
sistema. Se uma mudança quebrar uma delas, são eles que acusam.
"""
import pytest

import db
from tests.conftest import SENHA_TESTE, criar_casa, criar_paciente

ROTAS_PROTEGIDAS_GET = [
    "/",
    "/quadra/nova",
    "/quadra/1/editar",
    "/casa/nova",
    "/casa/1",
    "/casa/1/editar",
    "/casa/1/paciente/novo",
    "/paciente/1/editar",
    "/pacientes",
    "/pacientes/novo",
    "/pacientes/importar",
    "/exportar",
    "/exportar/preview",
    "/exportar/pdf",
    "/conta/senha",
    "/banco",
    "/banco/exportar",
    "/banco/backup/database_x.db/baixar",
]

ROTAS_PROTEGIDAS_POST = [
    "/banco/backup",
    "/banco/restaurar",
    "/banco/importar",
    "/quadra/nova",
    "/quadra/1/editar",
    "/quadra/1/excluir",
    "/casa/nova",
    "/casa/1/editar",
    "/casa/1/excluir",
    "/casa/1/paciente/novo",
    "/paciente/1/editar",
    "/paciente/1/excluir",
    "/paciente/1/status",
    "/paciente/1/transferir",
    "/pacientes/status-em-massa",
    "/casa/1/transferir",
    "/pacientes/importar",
    "/pacientes/novo",
    "/conta/senha",
]


@pytest.mark.parametrize("rota", ROTAS_PROTEGIDAS_GET)
def test_rotas_get_exigem_login(client, rota):
    resp = client.get(rota)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


@pytest.mark.parametrize("rota", ROTAS_PROTEGIDAS_POST)
def test_rotas_post_exigem_login(client, rota):
    resp = client.post(rota, data={})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_csrf_obrigatorio_em_post(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    resp = client.post("/login", data={"senha": SENHA_TESTE})
    # Sem token CSRF o POST é rejeitado — nunca autenticado.
    assert resp.status_code == 400


def test_login_senha_errada_nao_autentica(client):
    client.post("/login", data={"senha": "senha-errada-999"})
    resp = client.get("/")
    assert resp.status_code == 302  # continua deslogado


def test_rate_limit_login(client):
    for _ in range(5):
        client.post("/login", data={"senha": "senha-errada-999"})
    # Mesmo com a senha CORRETA, a 6ª tentativa dentro da janela é bloqueada.
    resp = client.post("/login", data={"senha": SENHA_TESTE})
    assert resp.status_code == 429
    assert client.get("/").status_code == 302  # não autenticou


def test_open_redirect_bloqueado(client):
    resp = client.post("/login?next=https://evil.example.com", data={"senha": SENHA_TESTE})
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]

    client.post("/logout")


def test_protocolo_relativo_bloqueado(client):
    resp = client.post("/login?next=//evil.example.com", data={"senha": SENHA_TESTE})
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_next_relativo_e_seguido(client):
    resp = client.post("/login?next=/casa/nova", data={"senha": SENHA_TESTE})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/casa/nova")


def test_headers_de_seguranca(client):
    resp = client.get("/login")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "nonce-" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_hsts_apenas_sob_https(app, client):
    # HTTP local: sem HSTS (não faz sentido e travaria o navegador no host).
    resp = client.get("/login")
    assert "Strict-Transport-Security" not in resp.headers

    # Sob TLS (run.py liga FORCE_HTTPS → cookie Secure), HSTS entra.
    app.config["SESSION_COOKIE_SECURE"] = True
    try:
        resp = client.get("/login")
        assert resp.headers.get("Strict-Transport-Security") == "max-age=31536000"
    finally:
        app.config["SESSION_COOKIE_SECURE"] = False


def test_nonce_do_csp_bate_com_html(client):
    resp = client.get("/login")
    csp = resp.headers["Content-Security-Policy"]
    nonce = csp.split("nonce-")[1].split("'")[0]
    assert nonce  # não vazio
    assert f'nonce="{nonce}"' in resp.get_data(as_text=True)


def test_nonce_muda_a_cada_resposta(client):
    def nonce_de(resp):
        return resp.headers["Content-Security-Policy"].split("nonce-")[1].split("'")[0]

    assert nonce_de(client.get("/login")) != nonce_de(client.get("/login"))


def test_xss_nome_de_paciente_escapado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="<script>alert('xss')</script>", observacao="<img src=x onerror=alert(1)>")
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "<script>alert('xss')</script>" not in body
    assert "&lt;script&gt;" in body
    assert "<img src=x onerror" not in body


def test_recuperar_senha_bloqueada_para_ip_remoto(client):
    resp = client.get("/recuperar-senha", environ_base={"REMOTE_ADDR": "10.0.0.55"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    resp = client.post(
        "/recuperar-senha",
        data={"nova_senha": "nova-senha-12345", "confirmar_senha": "nova-senha-12345"},
        environ_base={"REMOTE_ADDR": "10.0.0.55"},
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_recuperar_senha_local_funciona(client):
    resp = client.get("/recuperar-senha", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200

    resp = client.post(
        "/recuperar-senha",
        data={"nova_senha": "nova-senha-12345", "confirmar_senha": "nova-senha-12345"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 302
    # A senha antiga deixa de funcionar; a nova entra.
    assert client.post("/login", data={"senha": SENHA_TESTE}).status_code == 200  # re-render com erro
    resp = client.post("/login", data={"senha": "nova-senha-12345"})
    assert resp.status_code == 302


def test_logout_invalida_sessao(logged_client):
    assert logged_client.get("/").status_code == 200
    logged_client.post("/logout")
    assert logged_client.get("/").status_code == 302


def test_logout_exige_post(logged_client):
    # GET /logout não existe — logout via link seria vulnerável a CSRF de logout.
    assert logged_client.get("/logout").status_code == 405


def test_alterar_senha_exige_senha_atual_correta(logged_client):
    resp = logged_client.post(
        "/conta/senha",
        data={
            "senha_atual": "senha-errada",
            "nova_senha": "nova-senha-12345",
            "confirmar_senha": "nova-senha-12345",
        },
    )
    assert resp.status_code == 200  # re-render com erro, sem trocar
    logged_client.post("/logout")
    assert logged_client.post("/login", data={"senha": SENHA_TESTE}).status_code == 302


def test_alterar_senha_politica_minima(logged_client):
    resp = logged_client.post(
        "/conta/senha",
        data={"senha_atual": SENHA_TESTE, "nova_senha": "curta", "confirmar_senha": "curta"},
    )
    assert resp.status_code == 200
    logged_client.post("/logout")
    assert logged_client.post("/login", data={"senha": SENHA_TESTE}).status_code == 302


# ---------------------------------------------------------------------------
# Configuração inicial (/setup)
# ---------------------------------------------------------------------------
def test_setup_sem_senha_login_redireciona_para_setup(app_sem_senha):
    client = app_sem_senha.test_client()
    resp = client.get("/login")
    assert resp.status_code == 302
    assert "/setup" in resp.headers["Location"]


def test_setup_tela_disponivel_e_gera_codigo(app_sem_senha):
    import os

    client = app_sem_senha.test_client()
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "Código de segurança" in resp.get_data(as_text=True)
    assert os.path.exists(db.SETUP_TOKEN_PATH)


def test_setup_codigo_errado_nao_define_senha(app_sem_senha):
    client = app_sem_senha.test_client()
    db.ensure_setup_token()
    resp = client.post(
        "/setup",
        data={"codigo": "AAAA-AAAA", "nova_senha": "senha-nova-12345", "confirmar_senha": "senha-nova-12345"},
    )
    assert resp.status_code == 200  # re-render com erro
    assert not db.senha_configurada()


def test_setup_codigo_correto_define_senha_e_e_uso_unico(app_sem_senha):
    import os

    client = app_sem_senha.test_client()
    codigo = db.ensure_setup_token()

    # Digitação tolerante: minúsculas e sem hífen também valem.
    resp = client.post(
        "/setup",
        data={
            "codigo": codigo.replace("-", "").lower(),
            "nova_senha": "senha-nova-12345",
            "confirmar_senha": "senha-nova-12345",
        },
    )
    assert resp.status_code == 302
    assert db.senha_configurada()
    assert not os.path.exists(db.SETUP_TOKEN_PATH)  # código destruído após o uso

    # Uso único e irreversível: /setup vira redirect permanente para o login.
    assert "/login" in client.get("/setup").headers["Location"]

    # A senha definida funciona.
    resp = client.post("/login", data={"senha": "senha-nova-12345"})
    assert resp.status_code == 302


def test_setup_politica_de_senha_valida_antes_do_codigo(app_sem_senha):
    client = app_sem_senha.test_client()
    codigo = db.ensure_setup_token()
    resp = client.post(
        "/setup",
        data={"codigo": codigo, "nova_senha": "curta", "confirmar_senha": "curta"},
    )
    assert resp.status_code == 200
    assert not db.senha_configurada()


def test_setup_com_rate_limit(app_sem_senha):
    client = app_sem_senha.test_client()
    codigo = db.ensure_setup_token()
    for _ in range(5):
        client.post(
            "/setup",
            data={"codigo": "XXXX-XXXX", "nova_senha": "senha-nova-12345", "confirmar_senha": "senha-nova-12345"},
        )
    # Mesmo com o código CERTO, a 6ª tentativa na janela é bloqueada.
    resp = client.post(
        "/setup",
        data={"codigo": codigo, "nova_senha": "senha-nova-12345", "confirmar_senha": "senha-nova-12345"},
    )
    assert resp.status_code == 429
    assert not db.senha_configurada()


def test_setup_desativado_com_senha_configurada(client):
    resp = client.get("/setup")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_payload_gigante_rejeitado_com_413(logged_client):
    # Limite global de 1MB: um POST de 2MB nem chega ao parsing do form.
    resp = logged_client.post(
        "/quadra/nova",
        data={"numero_quadra": "1", "lixo": "x" * (2 * 1024 * 1024)},
    )
    assert resp.status_code == 302  # handler amigável redireciona com flash
    assert not db.get_db_connection().execute(
        "SELECT 1 FROM quadras"
    ).fetchone()  # nada foi gravado


def test_next_do_status_de_paciente_nao_faz_open_redirect(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    resp = logged_client.post(
        "/paciente/1/status",
        data={"status": "mudou_se", "next": "https://evil.example.com"},
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]

    resp = logged_client.post(
        "/paciente/1/transferir",
        data={"casa_destino_id": "1", "next": "//evil.example.com"},
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_xss_via_csv_importado_escapado(logged_client):
    from io import BytesIO

    csv_malicioso = (
        "Nome;Data de nascimento;Sexo;CPF;CNS;Telefone celular;Telefone residencial;"
        "Telefone de contato;Rua;Número;Complemento;Bairro\n"
        "<script>alert('xss')</script>;01/01/1990;Feminino;123.456.789-01;-;-;-;-;"
        "<img src=x onerror=alert(1)>;1;-;-\n"
    )
    resp = logged_client.post(
        "/pacientes/importar",
        data={"arquivo": (BytesIO(csv_malicioso.encode("cp1252")), "r.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302

    body = logged_client.get("/pacientes").get_data(as_text=True)
    assert "<script>alert('xss')</script>" not in body
    assert "&lt;script&gt;" in body
    body_casa = logged_client.get("/").get_data(as_text=True)
    assert "<img src=x onerror" not in body_casa


def test_csv_gigante_rejeitado_com_413(logged_client):
    from io import BytesIO

    # Acima do limite de 20MB da rota: rejeitado antes do parsing.
    resp = logged_client.post(
        "/pacientes/importar",
        data={"arquivo": (BytesIO(b"x" * (21 * 1024 * 1024)), "grande.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302  # handler amigável
    assert "/pacientes/importar" in resp.headers["Location"]
    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 0


def test_pagina_login_nao_referencia_cdn(client):
    body = client.get("/login").get_data(as_text=True)
    assert "cdn.jsdelivr" not in body
    assert "http://" not in body.replace("http://www.w3.org", "")  # só namespace SVG
