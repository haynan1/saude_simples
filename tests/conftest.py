import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A chave precisa existir ANTES do import do app (o módulo valida no import).
os.environ.setdefault("SAUDE_SIMPLES_SECRET_KEY", "chave-de-teste-nao-usar-em-producao-1234")

import db  # noqa: E402

SENHA_TESTE = "senha-de-teste-123"


@pytest.fixture()
def app(tmp_path):
    """App com banco isolado por teste e estado de rate-limit limpo."""
    from werkzeug.security import generate_password_hash

    import app as app_module

    db.DATABASE = str(tmp_path / "test.db")
    db.BACKUP_DIR = str(tmp_path / "backups")
    db.init_db()
    db.set_senha_hash(generate_password_hash(SENHA_TESTE))

    app_module._login_attempts.clear()
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    yield app_module.app
    app_module.app.config["WTF_CSRF_ENABLED"] = False


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def logged_client(client):
    resp = client.post("/login", data={"senha": SENHA_TESTE})
    assert resp.status_code == 302
    return client


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
