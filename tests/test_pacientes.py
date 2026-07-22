"""Página de pacientes — situação cadastral (mudou-se, fora de área, óbito),
transferência de paciente/família entre casas e importação do CSV do e-SUS."""
from io import BytesIO

import db
from tests.conftest import criar_casa, criar_paciente, criar_quadra


def _status_de(paciente_id=1):
    conn = db.get_db_connection()
    row = conn.execute("SELECT status, casa_id FROM pacientes WHERE id = ?", (paciente_id,)).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Migração e página
# ---------------------------------------------------------------------------
def test_status_padrao_e_ativo(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    assert _status_de()["status"] == "ativo"


def test_pagina_pacientes_lista_todos(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Maria Aparecida")
    body = logged_client.get("/pacientes").get_data(as_text=True)
    assert "Maria Aparecida" in body
    assert "Importar e-SUS" in body


def test_filtro_por_status_e_quadra(logged_client):
    criar_quadra(logged_client, "1")
    criar_casa(logged_client, quadra_id="1")
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, casa_id=1, nome="Ana Da Quadra", cpf="11111111111")
    criar_paciente(logged_client, casa_id=2, nome="Bruno Sem Quadra", cpf="22222222222")
    logged_client.post("/paciente/2/status", data={"status": "mudou_se"})
    logged_client.get("/pacientes")  # consome o flash do POST (contém o nome)

    body = logged_client.get("/pacientes?status=ativo").get_data(as_text=True)
    assert "Ana Da Quadra" in body and "Bruno Sem Quadra" not in body

    body = logged_client.get("/pacientes?status=mudou_se").get_data(as_text=True)
    assert "Bruno Sem Quadra" in body and "Ana Da Quadra" not in body

    body = logged_client.get("/pacientes?quadra=1").get_data(as_text=True)
    assert "Ana Da Quadra" in body and "Bruno Sem Quadra" not in body

    body = logged_client.get("/pacientes?quadra=0").get_data(as_text=True)
    assert "Bruno Sem Quadra" in body and "Ana Da Quadra" not in body


# ---------------------------------------------------------------------------
# Situação cadastral
# ---------------------------------------------------------------------------
def test_marcar_mudou_se_preserva_cadastro_fora_das_contagens(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Carlos Mudante")
    resp = logged_client.post("/paciente/1/status", data={"status": "mudou_se"})
    assert resp.status_code == 302

    assert _status_de()["status"] == "mudou_se"
    # Fora da lista de moradores ativos da casa, mas guardado nos registros.
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Registros guardados" in body
    assert "Mudou-se" in body
    # Painel não conta mais o paciente.
    body = logged_client.get("/").get_data(as_text=True)
    assert "vazia" in body


def test_obito_guardado_e_sem_transferencia(logged_client):
    criar_casa(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, nome="Dona Falecida")
    logged_client.post("/paciente/1/status", data={"status": "obito"})
    assert _status_de()["status"] == "obito"

    # Transferir um óbito é rejeitado — nada muda.
    logged_client.post("/paciente/1/transferir", data={"casa_destino_id": "2"})
    row = _status_de()
    assert row["status"] == "obito"
    assert row["casa_id"] == 1


def test_status_invalido_rejeitado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    logged_client.post("/paciente/1/status", data={"status": "qualquer_coisa"})
    assert _status_de()["status"] == "ativo"


def test_reativar_paciente(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    logged_client.post("/paciente/1/status", data={"status": "fora_de_area"})
    logged_client.post("/paciente/1/status", data={"status": "ativo"})
    assert _status_de()["status"] == "ativo"


# ---------------------------------------------------------------------------
# Unicidade de CPF/CNS
# ---------------------------------------------------------------------------
def test_cpf_duplicado_rejeitado_no_cadastro(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Titular Do CPF", cpf="12345678901")
    resp = criar_paciente(logged_client, nome="Impostor", cpf="123.456.789-01")
    assert resp.status_code == 200  # re-render com erro, nada gravado

    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 1


def test_cpf_duplicado_rejeitado_na_edicao(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Primeiro", cpf="12345678901")
    criar_paciente(logged_client, nome="Segundo", cpf="98765432100")

    resp = logged_client.post(
        "/paciente/2/editar",
        data={"nome": "Segundo", "cpf": "12345678901"},
    )
    assert resp.status_code == 200  # re-render com erro

    conn = db.get_db_connection()
    cpf = conn.execute("SELECT cpf FROM pacientes WHERE id = 2").fetchone()["cpf"]
    conn.close()
    assert "987" in cpf  # documento original preservado


def test_editar_mantendo_o_proprio_cpf_permitido(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Titular", cpf="12345678901")
    resp = logged_client.post(
        "/paciente/1/editar",
        data={"nome": "Titular Renomeado", "cpf": "123.456.789-01"},
    )
    assert resp.status_code == 302  # o próprio documento não conta como duplicado

    conn = db.get_db_connection()
    nome = conn.execute("SELECT nome FROM pacientes WHERE id = 1").fetchone()["nome"]
    conn.close()
    assert nome == "Titular Renomeado"


def test_pacientes_sem_documento_podem_coexistir(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Bebê Um", cpf="")
    resp = criar_paciente(logged_client, nome="Bebê Dois", cpf="")
    assert resp.status_code == 302  # sem documento não há como colidir

    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 2


# ---------------------------------------------------------------------------
# Transferências
# ---------------------------------------------------------------------------
def test_transferir_paciente_muda_de_casa_e_reativa(logged_client):
    criar_casa(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, nome="Eva Transferida")
    logged_client.post("/paciente/1/status", data={"status": "mudou_se"})

    resp = logged_client.post("/paciente/1/transferir", data={"casa_destino_id": "2"})
    assert resp.status_code == 302
    row = _status_de()
    assert row["casa_id"] == 2
    assert row["status"] == "ativo"  # novo endereço na área → volta a ativo


def test_transferir_para_casa_inexistente_rejeitado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    logged_client.post("/paciente/1/transferir", data={"casa_destino_id": "99"})
    assert _status_de()["casa_id"] == 1


def test_transferir_familia_move_apenas_ativos(logged_client):
    criar_casa(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, nome="Pai Ativo", cpf="11111111111")
    criar_paciente(logged_client, nome="Filha Ativa", cpf="22222222222")
    criar_paciente(logged_client, nome="Avó Que Ja Mudou", cpf="33333333333")
    logged_client.post("/paciente/3/status", data={"status": "mudou_se"})

    resp = logged_client.post("/casa/1/transferir", data={"casa_destino_id": "2"})
    assert resp.status_code == 302

    conn = db.get_db_connection()
    casas = {
        row["nome"]: row["casa_id"]
        for row in conn.execute("SELECT nome, casa_id FROM pacientes").fetchall()
    }
    conn.close()
    assert casas["Pai Ativo"] == 2
    assert casas["Filha Ativa"] == 2
    assert casas["Avó Que Ja Mudou"] == 1  # registro guardado fica na casa antiga


def test_transferir_familia_para_mesma_casa_rejeitado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    logged_client.post("/casa/1/transferir", data={"casa_destino_id": "1"})
    assert _status_de()["casa_id"] == 1


# ---------------------------------------------------------------------------
# Importação do CSV do e-SUS
# ---------------------------------------------------------------------------
CSV_ESUS = """e-SUS - Atenção Primária
MINISTÉRIO DA SAÚDE

RELATÓRIO GERADO A PARTIR DO ACOMPANHAMENTO DE CONDIÇÕES DE SAÚDE

FILTROS
Microárea(s);13

Gerado em ;22/07/2026; às ;14:10; por ;Fulano

Nome;Data de nascimento;Idade;Sexo;Identidade de gênero;Raça/cor;CPF;CNS;Telefone celular;Telefone residencial;Telefone de contato;Microárea;Rua;Número;Complemento;Bairro;Município;UF;CEP;
MARIA IMPORTADA;01/03/1980;46 anos;Feminino;-;PARDA;123.456.789-01;-;(64) 99999-0001;-;-;"13";Rua das Flores;10;QD 5 LT 2;CENTRO;Cidade;GO;76050-000;
JOAO IMPORTADO;15/07/2010;15 anos;Masculino;-;BRANCA;-;700000000000001;-;(64) 3671-0002;-;"13";Rua das Flores;10;QD 5 LT 2;CENTRO;Cidade;GO;76050-000;
PEDRO SEM CASA;20/12/1955;70 anos;Masculino;-;PRETA;987.654.321-00;-;(64) 99999-0003;-;-;"13";-;-;-;-;-;-;-;
"""


def _enviar_csv(client, conteudo=CSV_ESUS):
    return client.post(
        "/pacientes/importar",
        data={"arquivo": (BytesIO(conteudo.encode("cp1252")), "relatorio.csv")},
        content_type="multipart/form-data",
    )


def test_importacao_esus_importa_todos_sem_casa(logged_client):
    """Importar nunca vincula a casa nem cria casas/quadras — o vínculo é
    decisão do operador ("Definir casa"). O endereço do arquivo vai para a
    observação como referência."""
    resp = _enviar_csv(logged_client)
    assert resp.status_code == 302

    conn = db.get_db_connection()
    pacientes = conn.execute("SELECT * FROM pacientes ORDER BY nome").fetchall()
    total_casas = conn.execute("SELECT COUNT(*) AS c FROM casas").fetchone()["c"]
    total_quadras = conn.execute("SELECT COUNT(*) AS c FROM quadras").fetchone()["c"]
    conn.close()

    assert [p["nome"] for p in pacientes] == ["JOAO IMPORTADO", "MARIA IMPORTADA", "PEDRO SEM CASA"]
    assert total_casas == 0
    assert total_quadras == 0
    assert all(p["casa_id"] is None for p in pacientes)

    maria = next(p for p in pacientes if p["nome"] == "MARIA IMPORTADA")
    assert maria["cpf"] == "123.456.789-01"
    assert maria["data_nascimento"] == "1980-03-01"
    assert maria["sexo"] == "Feminino"
    assert maria["telefone"] == "(64) 99999-0001"
    assert "Rua das Flores, 10" in maria["observacao"]  # endereço preservado

    joao = next(p for p in pacientes if p["nome"] == "JOAO IMPORTADO")
    assert joao["cpf"] == "700 0000 0000 0001"  # CNS quando não há CPF
    assert joao["telefone"] == "(64) 3671-0002"  # residencial como alternativa

    pedro = next(p for p in pacientes if p["nome"] == "PEDRO SEM CASA")
    assert pedro["observacao"] == "Importado do e-SUS"  # sem endereço no arquivo


def test_definir_casa_de_paciente_importado(logged_client):
    _enviar_csv(logged_client)
    criar_casa(logged_client)

    resp = logged_client.post("/paciente/1/transferir", data={"casa_destino_id": "1"})
    assert resp.status_code == 302
    conn = db.get_db_connection()
    casa_id = conn.execute("SELECT casa_id FROM pacientes WHERE id = 1").fetchone()["casa_id"]
    conn.close()
    assert casa_id == 1


def test_importacao_esus_nao_duplica_em_reimportacao(logged_client):
    _enviar_csv(logged_client)
    _enviar_csv(logged_client)

    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    casas = conn.execute("SELECT COUNT(*) AS c FROM casas").fetchone()["c"]
    conn.close()
    assert total == 3
    assert casas == 0


def test_importacao_rejeita_arquivo_sem_cabecalho(logged_client):
    resp = _enviar_csv(logged_client, "só um texto qualquer\nsem cabeçalho nenhum\n")
    assert resp.status_code == 302
    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 0


def test_importacao_cria_backup_antes(logged_client):
    _enviar_csv(logged_client)
    assert any("antes_importar_pacientes" in b["nome"] for b in db.listar_backups())


def test_restaurar_backup_de_versao_antiga_reaplica_migracoes(logged_client):
    """Backup criado antes da coluna status existir: restaurar precisa migrar
    o esquema na hora — senão o painel quebraria com 'no such column'."""
    import os
    import sqlite3

    os.makedirs(db.BACKUP_DIR, exist_ok=True)
    caminho = os.path.join(db.BACKUP_DIR, "database_20240101_000000_000000_legado.db")
    conn = sqlite3.connect(caminho)
    conn.execute(
        "CREATE TABLE quadras (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_quadra INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE casas (id INTEGER PRIMARY KEY AUTOINCREMENT, quadra_id INTEGER,"
        " numero_casa INTEGER, endereco TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE pacientes (id INTEGER PRIMARY KEY AUTOINCREMENT, casa_id INTEGER,"
        " nome TEXT NOT NULL, cpf TEXT, telefone TEXT, data_nascimento TEXT, sexo TEXT,"
        " nome_pai TEXT, nome_mae TEXT, condicoes_saude TEXT, observacao TEXT)"
    )
    conn.execute("INSERT INTO casas (numero_casa, endereco) VALUES (1, 'Rua Antiga, 1')")
    conn.execute("INSERT INTO pacientes (casa_id, nome) VALUES (1, 'Paciente Legado')")
    conn.commit()
    conn.close()

    resp = logged_client.post("/banco/restaurar", data={"nome": os.path.basename(caminho)})
    assert resp.status_code == 302
    # Painel e página de pacientes funcionam sobre o banco restaurado.
    assert logged_client.get("/").status_code == 200
    assert "Paciente Legado" in logged_client.get("/pacientes").get_data(as_text=True)
