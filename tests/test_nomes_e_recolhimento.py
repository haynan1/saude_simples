"""Nome de pessoa em caixa alta, e "Registros guardados" recolhido.

O e-SUS exporta em caixa alta e é contra ele que a equipe confere lista por
lista. Nome digitado à mão entrava em qualquer caixa, e a mesma pessoa aparecia
"Maria de Souza" aqui e "MARIA DE SOUZA" no arquivo — na hora de bater as duas,
são duas.
"""
import sqlite3

import db
from tests.conftest import criar_casa, criar_paciente, texto_pdf


def _nomes():
    conn = db.get_db_connection()
    linhas = conn.execute("SELECT nome, nome_pai, nome_mae FROM pacientes ORDER BY id").fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------
def test_cadastro_grava_o_nome_em_caixa_alta(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="maria de souza")
    assert _nomes()[0]["nome"] == "MARIA DE SOUZA"


def test_filiacao_tambem_e_padronizada(logged_client):
    """Pai e mãe são pessoas, e a ficha do e-SUS traz os três em caixa alta."""
    criar_casa(logged_client)
    logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "Ana Lima", "cpf": "", "telefone": "", "data_nascimento": "",
              "sexo": "", "nome_pai": "josé lima", "nome_mae": "Benedita Lima",
              "observacao": ""},
    )
    linha = _nomes()[0]
    assert linha["nome_pai"] == "JOSÉ LIMA"
    assert linha["nome_mae"] == "BENEDITA LIMA"


def test_acento_sobrevive_a_caixa_alta(logged_client):
    """`UPPER()` do SQLite só mexe em A-Z e devolveria "JOSé" — por isso a
    transformação é feita em Python."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="joão conceição de assunção")
    assert _nomes()[0]["nome"] == "JOÃO CONCEIÇÃO DE ASSUNÇÃO"


def test_espaco_sobrando_e_colapsado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="   maria    das   dores  ")
    assert _nomes()[0]["nome"] == "MARIA DAS DORES"


def test_edicao_tambem_padroniza(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="MARIA DE SOUZA")
    logged_client.post(
        "/paciente/1/editar",
        data={"nome": "maria de souza lima", "cpf": "", "telefone": "",
              "data_nascimento": "", "sexo": "", "nome_pai": "", "nome_mae": "",
              "observacao": ""},
    )
    assert _nomes()[0]["nome"] == "MARIA DE SOUZA LIMA"


def test_cadastro_pela_lista_tambem_padroniza(logged_client):
    logged_client.post(
        "/pacientes/novo",
        data={"nome": "pedro alves", "casa_id": "", "cpf": "", "telefone": "",
              "data_nascimento": "", "sexo": "", "nome_pai": "", "nome_mae": "",
              "observacao": ""},
    )
    assert _nomes()[0]["nome"] == "PEDRO ALVES"


def test_nome_so_de_espaco_continua_recusado(logged_client):
    """Padronizar não pode virar um jeito de aceitar cadastro sem nome."""
    criar_casa(logged_client)
    resp = criar_paciente(logged_client, nome="   ")
    assert resp.status_code == 200   # re-render com erro, nada gravado
    assert _nomes() == []


# ---------------------------------------------------------------------------
# Migração do que já está gravado
# ---------------------------------------------------------------------------
def test_banco_existente_sobe_para_o_padrao(tmp_path):
    """O banco do posto já tem nome em caixa mista quando esta versão sobe."""
    caminho = tmp_path / "misto.db"
    conn = sqlite3.connect(caminho)
    conn.executescript(
        """
        CREATE TABLE quadras (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_quadra INTEGER NOT NULL);
        CREATE TABLE casas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, quadra_id INTEGER, numero_casa INTEGER,
            endereco TEXT NOT NULL
        );
        CREATE TABLE pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, casa_id INTEGER, nome TEXT NOT NULL,
            cpf TEXT, telefone TEXT, data_nascimento TEXT, sexo TEXT, nome_pai TEXT,
            nome_mae TEXT, condicoes_saude TEXT, observacao TEXT
        );
        INSERT INTO casas (id, numero_casa, endereco) VALUES (1, 7, 'Rua Antiga, 7');
        INSERT INTO pacientes (id, casa_id, nome, nome_mae) VALUES
            (1, 1, 'maria josé da conceição', 'benedita'),
            (2, 1, 'JOAO JA MAIUSCULO', NULL);
        """
    )
    conn.commit()
    conn.close()

    db.DATABASE = str(caminho)
    db.BACKUP_DIR = str(tmp_path / "backups")
    db.init_db()

    conn = db.get_db_connection()
    linhas = conn.execute("SELECT nome, nome_mae FROM pacientes ORDER BY id").fetchall()
    conn.close()
    assert linhas[0]["nome"] == "MARIA JOSÉ DA CONCEIÇÃO"
    assert linhas[0]["nome_mae"] == "BENEDITA"
    assert linhas[1]["nome"] == "JOAO JA MAIUSCULO"
    assert linhas[1]["nome_mae"] is None      # NULL continua NULL, não vira ""


def test_migracao_faz_backup_antes_de_transformar(tmp_path):
    """A transformação não tem volta: de "JOSÉ" não se recupera "José"."""
    import os

    caminho = tmp_path / "misto2.db"
    conn = sqlite3.connect(caminho)
    conn.executescript(
        """
        CREATE TABLE quadras (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_quadra INTEGER NOT NULL);
        CREATE TABLE casas (id INTEGER PRIMARY KEY AUTOINCREMENT, endereco TEXT NOT NULL);
        CREATE TABLE pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, casa_id INTEGER, nome TEXT NOT NULL,
            cpf TEXT, telefone TEXT, data_nascimento TEXT, sexo TEXT, nome_pai TEXT,
            nome_mae TEXT, condicoes_saude TEXT, observacao TEXT
        );
        INSERT INTO pacientes (id, nome) VALUES (1, 'maria minuscula');
        """
    )
    conn.commit()
    conn.close()

    db.DATABASE = str(caminho)
    db.BACKUP_DIR = str(tmp_path / "backups")
    db.init_db()

    backups = os.listdir(db.BACKUP_DIR)
    assert any("antes_padronizar_nomes" in nome for nome in backups)


def test_migracao_e_idempotente(tmp_path):
    """Rodada de novo não acha o que mudar — e não fica criando backup a cada
    boot do servidor."""
    import os

    caminho = tmp_path / "misto3.db"
    conn = sqlite3.connect(caminho)
    conn.executescript(
        """
        CREATE TABLE quadras (id INTEGER PRIMARY KEY AUTOINCREMENT, numero_quadra INTEGER NOT NULL);
        CREATE TABLE casas (id INTEGER PRIMARY KEY AUTOINCREMENT, endereco TEXT NOT NULL);
        CREATE TABLE pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, casa_id INTEGER, nome TEXT NOT NULL,
            cpf TEXT, telefone TEXT, data_nascimento TEXT, sexo TEXT, nome_pai TEXT,
            nome_mae TEXT, condicoes_saude TEXT, observacao TEXT
        );
        INSERT INTO pacientes (id, nome) VALUES (1, 'josé acentuado');
        """
    )
    conn.commit()
    conn.close()

    db.DATABASE = str(caminho)
    db.BACKUP_DIR = str(tmp_path / "backups")
    db.init_db()
    quantos = len(os.listdir(db.BACKUP_DIR))
    db.init_db()
    db.init_db()
    assert len(os.listdir(db.BACKUP_DIR)) == quantos


# ---------------------------------------------------------------------------
# Onde o nome aparece
# ---------------------------------------------------------------------------
def test_nome_sai_em_caixa_alta_na_tela_e_no_pdf(logged_client):
    """Transformar só na exibição deixaria o arquivo exportado com a mistura —
    por isso a caixa alta é da gravação."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="carlos eduardo nunes", data_nascimento="1970-01-01")
    assert "CARLOS EDUARDO NUNES" in logged_client.get("/casa/1").get_data(as_text=True)
    assert "CARLOS EDUARDO NUNES" in texto_pdf(logged_client.get("/exportar/pdf").data)


def test_busca_continua_achando_por_minuscula(logged_client):
    """O agente digita como quiser — a busca já normaliza caixa dos dois lados."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Carlos Eduardo Nunes")
    body = logged_client.get("/?busca=carlos eduardo").get_data(as_text=True)
    assert "CARLOS EDUARDO NUNES" in body


# ---------------------------------------------------------------------------
# Registros guardados recolhido
# ---------------------------------------------------------------------------
def test_registros_guardados_e_recolhivel_e_comeca_fechado(logged_client):
    """Quem abre a casa vai ver quem mora nela — estes são os que não moram
    mais. <details> nativo: teclado e leitor de tela sem JavaScript nenhum."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="quem se mudou", cpf="11111111111")
    logged_client.post("/paciente/1/status", data={"status": "mudou_se"})
    logged_client.get("/casa/1")  # consome o flash

    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert '<details class="registros-guardados">' in body
    assert "<details open" not in body
    assert "</details>" in body


def test_o_rotulo_recolhido_diz_quantos_sao(logged_client):
    """Recolher não pode esconder que existe algo ali."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="primeiro que saiu", cpf="11111111111")
    criar_paciente(logged_client, nome="segundo que saiu", cpf="22222222222")
    logged_client.post("/paciente/1/status", data={"status": "mudou_se"})
    logged_client.post("/paciente/2/status", data={"status": "fora_de_area"})
    logged_client.get("/casa/1")

    body = logged_client.get("/casa/1").get_data(as_text=True)
    recolhido = body[body.index("registros-guardados"):]
    assert '<span class="filter-count">2</span>' in recolhido


def test_sem_registro_guardado_nao_ha_bloco(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="mora aqui")
    assert "registros-guardados" not in logged_client.get("/casa/1").get_data(as_text=True)
