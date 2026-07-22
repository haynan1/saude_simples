"""Testes da gestão do banco — backup manual, exportação, importação e restauração."""
import io
import os
import sqlite3

import db
from tests.conftest import SENHA_TESTE, criar_casa, criar_paciente


def _nomes_backups():
    return [b["nome"] for b in db.listar_backups()]


def _banco_sqlite_valido(tmp_path, com_paciente="Paciente Importado"):
    """Gera um arquivo .db no formato do Saúde Simples para importar."""
    caminho = tmp_path / "para_importar.db"
    conn = sqlite3.connect(caminho)
    conn.execute("CREATE TABLE quadras (id INTEGER PRIMARY KEY, numero_quadra INTEGER NOT NULL)")
    conn.execute(
        "CREATE TABLE casas (id INTEGER PRIMARY KEY, quadra_id INTEGER, numero_casa INTEGER, endereco TEXT NOT NULL)"
    )
    conn.execute(
        """
        CREATE TABLE pacientes (
            id INTEGER PRIMARY KEY, casa_id INTEGER, nome TEXT NOT NULL, cpf TEXT,
            telefone TEXT, data_nascimento TEXT, sexo TEXT, nome_pai TEXT,
            nome_mae TEXT, condicoes_saude TEXT, observacao TEXT
        )
        """
    )
    conn.execute("INSERT INTO casas (numero_casa, endereco) VALUES (1, 'Rua Importada, 9')")
    conn.execute("INSERT INTO pacientes (casa_id, nome) VALUES (1, ?)", (com_paciente,))
    conn.commit()
    conn.close()
    return caminho


# ---------------------------------------------------------------------------
# Página e backup manual
# ---------------------------------------------------------------------------
def test_pagina_banco(logged_client):
    body = logged_client.get("/banco").get_data(as_text=True)
    assert "Exportar banco" in body
    assert "Importar banco" in body
    assert "Backups automáticos" in body


def test_backup_manual_cria_arquivo(logged_client):
    assert _nomes_backups() == []
    resp = logged_client.post("/banco/backup")
    assert resp.status_code == 302
    assert any("manual" in nome for nome in _nomes_backups())


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def test_exportar_banco_baixa_sqlite(logged_client):
    criar_casa(logged_client)
    resp = logged_client.get("/banco/exportar")
    assert resp.status_code == 200
    assert resp.data[:16] == b"SQLite format 3\x00"
    assert "saude_simples_" in resp.headers["Content-Disposition"]

    # O snapshot exportado é um banco funcional com os dados.
    exportado = io.BytesIO(resp.data)
    with open(os.path.join(db.BACKUP_DIR, "..", "reimport.db"), "wb") as arquivo:
        arquivo.write(exportado.read())
    conn = sqlite3.connect(os.path.join(db.BACKUP_DIR, "..", "reimport.db"))
    total = conn.execute("SELECT COUNT(*) FROM casas").fetchone()[0]
    conn.close()
    assert total == 1


def test_baixar_backup_valido(logged_client):
    logged_client.post("/banco/backup")
    nome = _nomes_backups()[0]
    resp = logged_client.get(f"/banco/backup/{nome}/baixar")
    assert resp.status_code == 200
    assert resp.data[:16] == b"SQLite format 3\x00"


def test_baixar_backup_nome_invalido_rejeitado(logged_client):
    resp = logged_client.get("/banco/backup/..%5C..%5Csegredo.db/baixar", follow_redirects=True)
    assert "Backup não encontrado" in resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Restauração
# ---------------------------------------------------------------------------
def test_restaurar_backup_volta_dados_e_preserva_senha(logged_client):
    criar_casa(logged_client, endereco="Rua Original, 1")
    logged_client.post("/banco/backup")
    nome = _nomes_backups()[0]

    # Estraga o estado atual: exclui a casa.
    logged_client.post("/casa/1/excluir")
    assert "Rua Original, 1" not in logged_client.get("/").get_data(as_text=True)

    resp = logged_client.post("/banco/restaurar", data={"nome": nome})
    assert resp.status_code == 302
    assert "Rua Original, 1" in logged_client.get("/").get_data(as_text=True)

    # Backup de segurança do estado pré-restauração foi criado.
    assert any("antes_restaurar" in n for n in _nomes_backups())

    # A senha atual continua valendo.
    logged_client.post("/logout")
    assert logged_client.post("/login", data={"senha": SENHA_TESTE}).status_code == 302


def test_restaurar_nome_invalido_rejeitado(logged_client):
    resp = logged_client.post("/banco/restaurar", data={"nome": "../../etc/passwd"}, follow_redirects=True)
    assert "Backup não encontrado" in resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Importação
# ---------------------------------------------------------------------------
def test_importar_banco_substitui_dados_e_preserva_senha(logged_client, tmp_path):
    criar_casa(logged_client, endereco="Rua Antiga, 1")
    criar_paciente(logged_client, nome="Paciente Antigo")

    caminho = _banco_sqlite_valido(tmp_path)
    with open(caminho, "rb") as arquivo:
        resp = logged_client.post(
            "/banco/importar",
            data={"arquivo": (arquivo, "exportado.db")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 302

    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Paciente Importado" in body
    assert "Paciente Antigo" not in body

    # Backup pré-importação criado; senha local preservada.
    assert any("antes_importar" in n for n in _nomes_backups())
    logged_client.post("/logout")
    assert logged_client.post("/login", data={"senha": SENHA_TESTE}).status_code == 302


def test_importar_arquivo_nao_sqlite_rejeitado(logged_client):
    resp = logged_client.post(
        "/banco/importar",
        data={"arquivo": (io.BytesIO(b"isto nao e um banco"), "falso.db")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "não é um banco de dados SQLite" in resp.get_data(as_text=True)
    # Dados atuais intactos (nenhuma tabela sobrescrita).
    assert db.senha_configurada()


def test_importar_sqlite_sem_esquema_rejeitado(logged_client, tmp_path):
    caminho = tmp_path / "outro_sistema.db"
    conn = sqlite3.connect(caminho)
    conn.execute("CREATE TABLE alheia (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with open(caminho, "rb") as arquivo:
        resp = logged_client.post(
            "/banco/importar",
            data={"arquivo": (arquivo, "outro.db")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    assert "faltam as tabelas" in resp.get_data(as_text=True)


def test_importar_sem_arquivo_rejeitado(logged_client):
    resp = logged_client.post("/banco/importar", data={}, follow_redirects=True)
    assert "Selecione o arquivo" in resp.get_data(as_text=True)


def test_importar_banco_de_versao_antiga_ganha_migracoes(logged_client, tmp_path):
    """Banco importado sem índices/colunas novas passa pelo init_db ao entrar."""
    caminho = _banco_sqlite_valido(tmp_path)
    with open(caminho, "rb") as arquivo:
        logged_client.post(
            "/banco/importar",
            data={"arquivo": (arquivo, "antigo.db")},
            content_type="multipart/form-data",
        )

    conn = db.get_db_connection()
    indices = {
        linha["name"]
        for linha in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    colunas_casas = {linha["name"] for linha in conn.execute("PRAGMA table_info(casas)")}
    conn.close()
    assert "idx_pacientes_casa_id" in indices
    assert "tipo_imovel" in colunas_casas  # coluna nova entra no banco importado
