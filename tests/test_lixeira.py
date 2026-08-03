"""Lixeira de pacientes — excluir move para lá, restauração em até 30 dias,
esvaziamento com backup e purga automática dos expirados."""
from datetime import datetime, timedelta

import db
from tests.conftest import criar_casa, criar_paciente


def _total(tabela):
    conn = db.get_db_connection()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM {tabela}").fetchone()["c"]
    conn.close()
    return total


def test_excluir_move_para_a_lixeira(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="VAI PRA LIXEIRA", cpf="11111111111")

    resp = logged_client.post("/paciente/1/excluir")
    assert resp.status_code == 302
    assert _total("pacientes") == 0
    assert _total("lixeira_pacientes") == 1

    body = logged_client.get("/lixeira").get_data(as_text=True)
    assert "VAI PRA LIXEIRA" in body
    assert "Restaurar" in body


def test_restaurar_preserva_id_casa_e_situacao(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="VOLTA INTEIRO", cpf="11111111111")
    logged_client.post("/paciente/1/status", data={"status": "mudou_se"})
    logged_client.post("/paciente/1/excluir")

    resp = logged_client.post("/lixeira/1/restaurar")
    assert resp.status_code == 302
    assert _total("lixeira_pacientes") == 0

    conn = db.get_db_connection()
    row = conn.execute("SELECT id, casa_id, status, cpf FROM pacientes").fetchone()
    conn.close()
    assert row["id"] == 1  # id original preservado
    assert row["casa_id"] == 1
    assert row["status"] == "mudou_se"  # situação da época volta junto
    assert "111" in row["cpf"]


def test_restaurar_com_casa_excluida_volta_sem_casa(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="CASA SUMIU", cpf="11111111111")
    logged_client.post("/paciente/1/excluir")
    logged_client.post("/casa/1/excluir")  # casa some enquanto espera na lixeira

    logged_client.post("/lixeira/1/restaurar")
    conn = db.get_db_connection()
    row = conn.execute("SELECT casa_id FROM pacientes WHERE nome = 'CASA SUMIU'").fetchone()
    conn.close()
    assert row["casa_id"] is None


def test_restaurar_bloqueado_se_cpf_foi_recadastrado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="ORIGINAL", cpf="11111111111")
    logged_client.post("/paciente/1/excluir")
    criar_paciente(logged_client, nome="NOVO DONO DO CPF", cpf="11111111111")

    logged_client.post("/lixeira/1/restaurar")
    # Permanece na lixeira; a regra de documento único não é violada.
    assert _total("lixeira_pacientes") == 1
    assert _total("pacientes") == 1


def test_esvaziar_lixeira_com_backup(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="UM", cpf="11111111111")
    criar_paciente(logged_client, nome="DOIS", cpf="22222222222")
    logged_client.post("/paciente/1/excluir")
    logged_client.post("/paciente/2/excluir")

    resp = logged_client.post("/lixeira/esvaziar")
    assert resp.status_code == 302
    assert _total("lixeira_pacientes") == 0
    assert any("antes_esvaziar_lixeira" in b["nome"] for b in db.listar_backups())


def test_purga_automatica_apos_30_dias(logged_client):
    criar_casa(logged_client)
    conn = db.get_db_connection()
    vencido = (datetime.now() - timedelta(days=31)).isoformat(timespec="seconds")
    no_prazo = (datetime.now() - timedelta(days=29)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO lixeira_pacientes (id, nome, excluido_em) VALUES (1, 'Expirado', ?)",
        (vencido,),
    )
    conn.execute(
        "INSERT INTO lixeira_pacientes (id, nome, excluido_em) VALUES (2, 'No Prazo', ?)",
        (no_prazo,),
    )
    conn.commit()
    conn.close()

    body = logged_client.get("/lixeira").get_data(as_text=True)
    assert "Expirado" not in body  # purgado ao abrir a página
    assert "No Prazo" in body
    assert _total("lixeira_pacientes") == 1


def test_restaurar_registro_inexistente_nao_quebra(logged_client):
    resp = logged_client.post("/lixeira/99/restaurar")
    assert resp.status_code == 302
    assert "/lixeira" in resp.headers["Location"]
