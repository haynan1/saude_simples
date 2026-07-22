"""Testes de segurança — auth, CSRF, rate limit, open redirect, XSS, headers.

Estes testes são a especificação executável das propriedades de segurança do
sistema. Se uma mudança quebrar uma delas, são eles que acusam.
"""
import pytest

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
    "/exportar/preview",
    "/exportar/pdf",
    "/conta/senha",
]

ROTAS_PROTEGIDAS_POST = [
    "/quadra/nova",
    "/quadra/1/editar",
    "/quadra/1/excluir",
    "/casa/nova",
    "/casa/1/editar",
    "/casa/1/excluir",
    "/casa/1/paciente/novo",
    "/paciente/1/editar",
    "/paciente/1/excluir",
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


def test_pagina_login_nao_referencia_cdn(client):
    body = client.get("/login").get_data(as_text=True)
    assert "cdn.jsdelivr" not in body
    assert "http://" not in body.replace("http://www.w3.org", "")  # só namespace SVG
