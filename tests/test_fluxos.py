"""Testes funcionais — CRUD de quadras/casas/pacientes, busca, exportação,
integridade de dados (backups, cascata) e estados de erro."""
import os

import db
from tests.conftest import criar_casa, criar_paciente, criar_quadra


# ---------------------------------------------------------------------------
# Quadras
# ---------------------------------------------------------------------------
def test_crud_quadra(logged_client):
    assert criar_quadra(logged_client, "7").status_code == 302
    body = logged_client.get("/").get_data(as_text=True)
    assert "Quadra 7" in body

    resp = logged_client.post("/quadra/1/editar", data={"numero_quadra": "9"})
    assert resp.status_code == 302
    assert "Quadra 9" in logged_client.get("/").get_data(as_text=True)

    resp = logged_client.post("/quadra/1/excluir")
    assert resp.status_code == 302
    assert "Quadra 9" not in logged_client.get("/").get_data(as_text=True)


def test_quadra_numero_invalido_rejeitado(logged_client):
    resp = logged_client.post("/quadra/nova", data={"numero_quadra": "abc"})
    assert resp.status_code == 200  # re-render com erro
    resp = logged_client.post("/quadra/nova", data={"numero_quadra": "0"})
    assert resp.status_code == 200

    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM quadras").fetchone()["c"]
    conn.close()
    assert total == 0  # nada foi gravado


def test_excluir_quadra_preserva_casas(logged_client):
    criar_quadra(logged_client)
    criar_casa(logged_client, quadra_id="1")
    logged_client.post("/quadra/1/excluir")
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Casa 1" in body  # casa sobrevive, sem quadra


# ---------------------------------------------------------------------------
# Casas
# ---------------------------------------------------------------------------
def test_crud_casa(logged_client):
    assert criar_casa(logged_client, endereco="Rua Nova, 42").status_code == 302
    assert "Rua Nova, 42" in logged_client.get("/casa/1").get_data(as_text=True)

    resp = logged_client.post(
        "/casa/1/editar", data={"endereco": "Rua Editada, 43", "numero_casa": "5", "quadra_id": ""}
    )
    assert resp.status_code == 302
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Rua Editada, 43" in body
    assert "Casa 5" in body

    logged_client.post("/casa/1/excluir")
    resp = logged_client.get("/casa/1")
    assert resp.status_code == 302  # não existe mais → volta ao painel


def test_casa_sem_endereco_rejeitada(logged_client):
    resp = logged_client.post("/casa/nova", data={"endereco": "", "numero_casa": "1", "quadra_id": ""})
    assert resp.status_code == 200


def test_casa_quadra_inexistente_rejeitada(logged_client):
    resp = logged_client.post(
        "/casa/nova", data={"endereco": "Rua X", "numero_casa": "1", "quadra_id": "99"}
    )
    assert resp.status_code == 200  # re-render com erro


def test_numeracao_automatica_por_quadra(logged_client):
    criar_quadra(logged_client)
    criar_casa(logged_client, numero="", quadra_id="1")
    criar_casa(logged_client, endereco="Rua B, 2", numero="", quadra_id="1")
    body = logged_client.get("/").get_data(as_text=True)
    assert "Casa 1" in body
    assert "Casa 2" in body


# ---------------------------------------------------------------------------
# Pacientes
# ---------------------------------------------------------------------------
def test_crud_paciente(logged_client):
    criar_casa(logged_client)
    assert criar_paciente(logged_client, nome="Maria de Souza").status_code == 302
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Maria de Souza" in body

    resp = logged_client.post(
        "/paciente/1/editar",
        data={"nome": "Maria Editada", "cpf": "", "telefone": "", "data_nascimento": "",
              "sexo": "", "nome_pai": "", "nome_mae": "", "observacao": ""},
    )
    assert resp.status_code == 302
    assert "Maria Editada" in logged_client.get("/casa/1").get_data(as_text=True)

    logged_client.post("/paciente/1/excluir")
    assert "Maria Editada" not in logged_client.get("/casa/1").get_data(as_text=True)


def test_paciente_sem_nome_rejeitado(logged_client):
    criar_casa(logged_client)
    resp = criar_paciente(logged_client, nome="")
    assert resp.status_code == 200  # re-render com erro


def test_cpf_e_telefone_normalizados(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, cpf="123.456.789-01", telefone="(63) 99999-8888")
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "123.456.789-01" in body
    assert "(63) 99999-8888" in body
    assert "wa.me/5563999998888" in body


def test_condicoes_de_saude_persistem(logged_client):
    criar_casa(logged_client)
    logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "Com Condicoes", "cpf": "", "telefone": "", "data_nascimento": "",
              "sexo": "", "nome_pai": "", "nome_mae": "", "observacao": "",
              "condicoes_saude": ["gestante", "diabetes"]},
    )
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Está gestante" in body
    assert "Tem diabetes" in body


def test_excluir_casa_cascateia_pacientes(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    logged_client.post("/casa/1/excluir")
    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 0


# ---------------------------------------------------------------------------
# Busca e painel
# ---------------------------------------------------------------------------
def test_busca_por_nome_aproximado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="José Aparecido da Silva")
    body = logged_client.get("/?busca=jose aparecido").get_data(as_text=True)
    assert "José Aparecido da Silva" in body


def test_busca_por_cpf(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, cpf="98765432100")
    body = logged_client.get("/?busca=98765432100").get_data(as_text=True)
    assert "Paciente Teste" in body


def test_busca_sem_resultado(logged_client):
    body = logged_client.get("/?busca=inexistente-zzz").get_data(as_text=True)
    assert "Nenhum paciente encontrado" in body


def test_painel_estatisticas(logged_client):
    criar_casa(logged_client)
    logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "Gestante Teste", "cpf": "", "telefone": "", "data_nascimento": "1995-01-01",
              "sexo": "Feminino", "nome_pai": "", "nome_mae": "", "observacao": "",
              "condicoes_saude": ["gestante"]},
    )
    body = logged_client.get("/").get_data(as_text=True)
    assert "Gestantes" in body


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def test_preview_geral_e_filtrado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    geral = logged_client.get("/exportar/preview").get_json()
    assert geral["modo"] == "geral"
    assert geral["stats"]["total_pacientes"] == 1

    filtrado = logged_client.get("/exportar/preview?condicoes=gestante").get_json()
    assert filtrado["modo"] == "filtrado"
    assert filtrado["stats"]["total_pacientes"] == 0  # paciente não é gestante


def test_exportar_pdf_completo(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    resp = logged_client.get("/exportar/pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:4] == b"%PDF"


def test_exportar_pdf_filtrado(logged_client):
    criar_casa(logged_client)
    logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "Diabetico", "cpf": "", "telefone": "", "data_nascimento": "",
              "sexo": "", "nome_pai": "", "nome_mae": "", "observacao": "",
              "condicoes_saude": ["diabetes"]},
    )
    resp = logged_client.get("/exportar/pdf?filtrar=1&condicoes=diabetes")
    assert resp.status_code == 200
    assert resp.data[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Integridade de dados
# ---------------------------------------------------------------------------
def test_migracao_de_banco_legado_na_raiz(app, tmp_path, monkeypatch):
    """Banco da v1 (raiz do projeto) é movido para instance/ sem perder dados."""
    import sqlite3

    legado = tmp_path / "legado" / "database.db"
    legado.parent.mkdir()
    conn = sqlite3.connect(legado)
    conn.execute("CREATE TABLE marca (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO marca (id) VALUES (42)")
    conn.commit()
    conn.close()

    destino = tmp_path / "instance" / "database.db"
    monkeypatch.setattr(db, "_LEGACY_DATABASE", str(legado))
    monkeypatch.setattr(db, "DATABASE", str(destino))

    conn = db.get_db_connection()
    valor = conn.execute("SELECT id FROM marca").fetchone()["id"]
    conn.close()
    assert valor == 42
    assert destino.exists()
    assert not legado.exists()


def test_exclusao_cria_backup_antes(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    assert not os.path.isdir(db.BACKUP_DIR) or not os.listdir(db.BACKUP_DIR)
    logged_client.post("/paciente/1/excluir")
    backups = os.listdir(db.BACKUP_DIR)
    assert any("antes_excluir_paciente" in nome for nome in backups)


# ---------------------------------------------------------------------------
# Estados de erro
# ---------------------------------------------------------------------------
def test_404_pagina_amigavel(logged_client):
    resp = logged_client.get("/rota-que-nao-existe")
    assert resp.status_code == 404
    assert "Página não encontrada" in resp.get_data(as_text=True)


def test_casa_inexistente_redireciona_com_aviso(logged_client):
    resp = logged_client.get("/casa/999", follow_redirects=True)
    assert "Casa não encontrada" in resp.get_data(as_text=True)


def test_paciente_inexistente_redireciona(logged_client):
    resp = logged_client.get("/paciente/999/editar")
    assert resp.status_code == 302
