"""Núcleo familiar dentro do domicílio.

Um endereço pode abrigar mais de uma família — dois núcleos partilhando a
moradia, ou as duas construções do mesmo lote. O que estes testes seguram é a
fronteira: repartir a casa não pode mexer em quem já estava lá, e uma ação de
UMA família não pode alcançar a outra que mora no mesmo endereço.
"""
import pytest

import db
from tests.conftest import criar_casa, criar_paciente, criar_quadra


def _familias(casa_id=1):
    conn = db.get_db_connection()
    linhas = conn.execute(
        "SELECT * FROM familias WHERE casa_id = ? ORDER BY id", (casa_id,)
    ).fetchall()
    conn.close()
    return linhas


def _moradores():
    conn = db.get_db_connection()
    linhas = conn.execute(
        "SELECT nome, casa_id, familia_id, status FROM pacientes ORDER BY id"
    ).fetchall()
    conn.close()
    return {linha["nome"]: linha for linha in linhas}


def _casa_com_dois_moradores(client):
    criar_casa(client, endereco="Rua A, 1")
    criar_paciente(client, nome="Pai Da Frente", cpf="11111111111")
    criar_paciente(client, nome="Filha Da Frente", cpf="22222222222")


def _casa_repartida(client):
    """Casa 1 com "Frente" (2 moradores) e "Fundos" (1 morador)."""
    _casa_com_dois_moradores(client)
    client.post("/casa/1/familia/nova", data={"nome_atual": "Frente", "nome": "Fundos"})
    fundos = _familias()[1]["id"]
    criar_paciente(client, nome="Vizinho Do Fundo", cpf="33333333333")
    conn = db.get_db_connection()
    conn.execute("UPDATE pacientes SET familia_id = ? WHERE nome = 'Vizinho Do Fundo'", (fundos,))
    conn.commit()
    conn.close()
    return fundos


# ---------------------------------------------------------------------------
# Migração de um banco que já roda em produção
# ---------------------------------------------------------------------------
def test_banco_anterior_ganha_a_estrutura_sem_perder_morador(tmp_path):
    """O banco do posto de saúde já tem gente dentro quando esta versão sobe.

    Reproduz o esquema ANTERIOR (sem `familias`, sem `familia_id`), grava um
    morador e roda o `init_db` por cima. O cadastro tem de sobreviver intacto,
    e a casa tem de continuar sendo de família única — migração que "só" zera
    um vínculo já seria perda de dado de campo."""
    import sqlite3

    caminho = tmp_path / "antigo.db"
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
        INSERT INTO pacientes (id, casa_id, nome, cpf) VALUES (1, 1, 'MORADOR ANTIGO', '111');
        """
    )
    conn.commit()
    conn.close()

    db.DATABASE = str(caminho)
    db.init_db()

    conn = db.get_db_connection()
    paciente = conn.execute("SELECT * FROM pacientes WHERE id = 1").fetchone()
    tabelas = {
        linha["name"] for linha in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    total_familias = conn.execute("SELECT COUNT(*) AS c FROM familias").fetchone()["c"]
    conn.close()

    assert paciente["nome"] == "MORADOR ANTIGO"
    assert paciente["casa_id"] == 1
    assert "familias" in tabelas
    assert paciente["familia_id"] is None   # casa de família única, como antes
    assert total_familias == 0              # ninguém foi repartido por conta própria


def test_lixeira_antiga_ganha_a_coluna_sem_perder_registro(tmp_path):
    """A lixeira espelha as colunas de pacientes — se ela ficar para trás na
    migração, o INSERT do próximo "excluir" quebra em produção."""
    import sqlite3

    caminho = tmp_path / "antigo2.db"
    conn = sqlite3.connect(caminho)
    conn.executescript(
        """
        CREATE TABLE casas (id INTEGER PRIMARY KEY AUTOINCREMENT, endereco TEXT NOT NULL);
        CREATE TABLE pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, casa_id INTEGER, nome TEXT NOT NULL,
            cpf TEXT, telefone TEXT, data_nascimento TEXT, sexo TEXT, nome_pai TEXT,
            nome_mae TEXT, condicoes_saude TEXT, observacao TEXT
        );
        CREATE TABLE lixeira_pacientes (
            id INTEGER PRIMARY KEY, casa_id INTEGER, nome TEXT NOT NULL, cpf TEXT,
            telefone TEXT, data_nascimento TEXT, sexo TEXT, nome_pai TEXT, nome_mae TEXT,
            condicoes_saude TEXT, observacao TEXT, status TEXT NOT NULL DEFAULT 'ativo',
            excluido_em TEXT NOT NULL
        );
        INSERT INTO lixeira_pacientes (id, nome, excluido_em)
        VALUES (9, 'ESPERANDO NA LIXEIRA', '2026-01-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()

    db.DATABASE = str(caminho)
    db.init_db()

    conn = db.get_db_connection()
    item = conn.execute("SELECT * FROM lixeira_pacientes WHERE id = 9").fetchone()
    conn.close()
    assert item["nome"] == "ESPERANDO NA LIXEIRA"
    assert item["familia_id"] is None


# ---------------------------------------------------------------------------
# A casa de família única não muda
# ---------------------------------------------------------------------------
def test_casa_sem_reparticao_nao_mostra_agrupamento(logged_client):
    """O normal do território é uma família por casa — a tela dela é a lista
    simples de sempre, sem cabeçalho de grupo nenhum."""
    _casa_com_dois_moradores(logged_client)
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "família(s) neste endereço" not in body
    assert "Pai Da Frente" in body
    assert _familias() == []


def test_morador_de_casa_nao_repartida_fica_sem_nucleo(logged_client):
    _casa_com_dois_moradores(logged_client)
    assert _moradores()["Pai Da Frente"]["familia_id"] is None


def test_select_de_situacao_tem_as_opcoes_nas_duas_telas(logged_client):
    """A tabela de moradores virou macro, e macro Jinja importado sem
    `with context` não enxerga variável de context processor: o Jinja não falha,
    resolve como indefinido, e o <select> sai com ZERO opções — a tela continua
    bonita e o agente perde a troca de situação. Vale para as duas telas, porque
    as duas passam pelo mesmo macro."""
    _casa_com_dois_moradores(logged_client)
    simples = logged_client.get("/casa/1").get_data(as_text=True)
    assert 'value="mudou_se"' in simples
    assert 'name="next" value="/casa/1"' in simples

    logged_client.post("/casa/1/familia/nova", data={"nome_atual": "Frente", "nome": "Fundos"})
    repartida = logged_client.get("/casa/1").get_data(as_text=True)
    assert 'value="mudou_se"' in repartida
    assert 'name="next" value="/casa/1"' in repartida


# ---------------------------------------------------------------------------
# Repartir
# ---------------------------------------------------------------------------
def test_primeira_reparticao_cria_dois_nucleos(logged_client):
    _casa_com_dois_moradores(logged_client)
    resp = logged_client.post(
        "/casa/1/familia/nova", data={"nome_atual": "Frente", "nome": "Fundos"}
    )
    assert resp.status_code == 302

    familias = _familias()
    assert [f["nome"] for f in familias] == ["Frente", "Fundos"]


def test_moradores_existentes_vao_para_o_primeiro_nucleo(logged_client):
    """Quem já morava aqui não pode cair num limbo "sem família" ao lado do
    núcleo novo — seria trabalho manual nascido de uma decisão nossa."""
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome_atual": "Frente", "nome": "Fundos"})

    frente = _familias()[0]["id"]
    moradores = _moradores()
    assert moradores["Pai Da Frente"]["familia_id"] == frente
    assert moradores["Filha Da Frente"]["familia_id"] == frente


def test_nucleo_novo_nasce_vazio(logged_client):
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome_atual": "Frente", "nome": "Fundos"})
    fundos = _familias()[1]["id"]
    assert all(m["familia_id"] != fundos for m in _moradores().values())


def test_morador_guardado_acompanha_o_nucleo_de_origem(logged_client):
    """Quem se mudou ou faleceu fez parte daquele núcleo. Deixá-lo de fora
    reescreveria a história da casa."""
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/paciente/2/status", data={"status": "mudou_se"})
    logged_client.post("/casa/1/familia/nova", data={"nome_atual": "Frente", "nome": "Fundos"})

    frente = _familias()[0]["id"]
    assert _moradores()["Filha Da Frente"]["familia_id"] == frente


def test_terceira_familia_nao_remexe_nas_anteriores(logged_client):
    fundos = _casa_repartida(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome": "Puxadinho"})

    assert [f["nome"] for f in _familias()] == ["Frente", "Fundos", "Puxadinho"]
    assert _moradores()["Vizinho Do Fundo"]["familia_id"] == fundos


def test_repartir_casa_vazia(logged_client):
    criar_casa(logged_client)
    resp = logged_client.post("/casa/1/familia/nova", data={"nome": "Fundos"})
    assert resp.status_code == 302
    assert len(_familias()) == 2


def test_nome_em_branco_cai_no_padrao(logged_client):
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome_atual": "", "nome": ""})
    assert [f["nome"] for f in _familias()] == ["Família 1", "Família 2"]


def test_nome_gigante_e_cortado(logged_client):
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome": "F" * 500})
    assert len(_familias()[1]["nome"]) == 60


def test_a_casa_repartida_lista_as_familias(logged_client):
    _casa_repartida(logged_client)
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "2 família(s) neste endereço" in body
    assert "Frente" in body and "Fundos" in body


# ---------------------------------------------------------------------------
# Cadastrar e mover moradores
# ---------------------------------------------------------------------------
def test_cadastrar_morador_ja_dentro_de_uma_familia(logged_client):
    fundos = _casa_repartida(logged_client)
    resp = logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "Nova Do Fundo", "cpf": "44444444444", "telefone": "",
              "data_nascimento": "", "sexo": "", "nome_pai": "", "nome_mae": "",
              "observacao": "", "familia_id": str(fundos)},
    )
    assert resp.status_code == 302
    assert _moradores()["Nova Do Fundo"]["familia_id"] == fundos


def test_botao_da_familia_abre_o_cadastro_com_ela_escolhida(logged_client):
    fundos = _casa_repartida(logged_client)
    body = logged_client.get(f"/casa/1/paciente/novo?familia={fundos}").get_data(as_text=True)
    assert f'value="{fundos}" selected' in body


def test_editar_move_o_morador_entre_familias_da_casa(logged_client):
    fundos = _casa_repartida(logged_client)
    resp = logged_client.post(
        "/paciente/1/editar",
        data={"nome": "Pai Da Frente", "cpf": "", "telefone": "", "data_nascimento": "",
              "sexo": "", "nome_pai": "", "nome_mae": "", "observacao": "",
              "familia_id": str(fundos)},
    )
    assert resp.status_code == 302
    assert _moradores()["Pai Da Frente"]["familia_id"] == fundos


def test_familia_de_outra_casa_e_recusada(logged_client):
    """Fronteira de segurança: o id vem do cliente. Sem a conferência, um POST
    forjado prenderia o morador ao núcleo de outro domicílio, e a tela da outra
    casa passaria a listar gente que não mora nela."""
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    logged_client.post("/casa/2/familia/nova", data={"nome_atual": "Outra A", "nome": "Outra B"})
    intrusa = _familias(casa_id=2)[0]["id"]

    logged_client.post(
        "/paciente/1/editar",
        data={"nome": "Pai Da Frente", "cpf": "", "telefone": "", "data_nascimento": "",
              "sexo": "", "nome_pai": "", "nome_mae": "", "observacao": "",
              "familia_id": str(intrusa)},
    )
    assert _moradores()["Pai Da Frente"]["familia_id"] != intrusa


def test_familia_inexistente_no_cadastro_nao_explode(logged_client):
    _casa_repartida(logged_client)
    resp = logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "Sem Nucleo", "cpf": "", "telefone": "", "data_nascimento": "",
              "sexo": "", "nome_pai": "", "nome_mae": "", "observacao": "",
              "familia_id": "9999"},
    )
    assert resp.status_code == 302
    assert _moradores()["Sem Nucleo"]["familia_id"] is None


# ---------------------------------------------------------------------------
# Ações que precisam parar na fronteira do núcleo
# ---------------------------------------------------------------------------
def test_situacao_atinge_so_a_familia_escolhida(logged_client):
    fundos = _casa_repartida(logged_client)
    resp = logged_client.post(
        "/casa/1/status-familia", data={"status": "mudou_se", "familia_id": str(fundos)}
    )
    assert resp.status_code == 302

    moradores = _moradores()
    assert moradores["Vizinho Do Fundo"]["status"] == "mudou_se"
    assert moradores["Pai Da Frente"]["status"] == "ativo"


def test_situacao_sem_familia_continua_valendo_para_a_casa(logged_client):
    """A casa de família única não manda `familia_id` — o alvo segue sendo a
    casa inteira, como sempre foi."""
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/casa/1/status-familia", data={"status": "mudou_se"})
    assert all(m["status"] == "mudou_se" for m in _moradores().values())


def test_transferir_familia_leva_so_o_nucleo(logged_client):
    fundos = _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")

    resp = logged_client.post(
        "/casa/1/transferir", data={"casa_destino_id": "2", "familia_id": str(fundos)}
    )
    assert resp.status_code == 302

    moradores = _moradores()
    assert moradores["Vizinho Do Fundo"]["casa_id"] == 2
    assert moradores["Pai Da Frente"]["casa_id"] == 1


def test_transferir_limpa_o_nucleo_da_casa_de_origem(logged_client):
    """O núcleo é da casa de origem: levá-lo junto deixaria o morador vinculado
    a um núcleo de OUTRO domicílio, e a casa antiga listaria quem se mudou."""
    fundos = _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    logged_client.post("/casa/1/transferir", data={"casa_destino_id": "2", "familia_id": str(fundos)})
    assert _moradores()["Vizinho Do Fundo"]["familia_id"] is None


def test_transferir_paciente_sozinho_tambem_limpa_o_nucleo(logged_client):
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    logged_client.post("/paciente/1/transferir", data={"casa_destino_id": "2"})
    assert _moradores()["Pai Da Frente"]["familia_id"] is None


def test_familia_de_outra_casa_nao_transfere(logged_client):
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    logged_client.post("/casa/2/familia/nova", data={"nome_atual": "Outra A", "nome": "Outra B"})
    intrusa = _familias(casa_id=2)[0]["id"]

    logged_client.post(
        "/casa/1/transferir", data={"casa_destino_id": "2", "familia_id": str(intrusa)}
    )
    assert _moradores()["Pai Da Frente"]["casa_id"] == 1


# ---------------------------------------------------------------------------
# Transferir PARA uma família
# ---------------------------------------------------------------------------
def test_transferir_paciente_direto_para_uma_familia_do_destino(logged_client):
    """Sem isso, o agente transferia e depois tinha de abrir a casa de destino e
    editar o morador — dois passos para uma decisão que ele já tinha tomado."""
    fundos = _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, casa_id=2, nome="Recem Chegado", cpf="88888888888")

    resp = logged_client.post(
        "/paciente/4/transferir", data={"casa_destino_id": f"1:{fundos}"}
    )
    assert resp.status_code == 302

    morador = _moradores()["Recem Chegado"]
    assert morador["casa_id"] == 1
    assert morador["familia_id"] == fundos


def test_transferir_familia_inteira_para_uma_familia_do_destino(logged_client):
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, casa_id=2, nome="Vem Da Outra", cpf="88888888888")
    frente = _familias()[0]["id"]

    resp = logged_client.post(
        "/casa/2/transferir", data={"casa_destino_id": f"1:{frente}"}
    )
    assert resp.status_code == 302

    morador = _moradores()["Vem Da Outra"]
    assert morador["casa_id"] == 1
    assert morador["familia_id"] == frente


def test_mover_morador_entre_familias_do_mesmo_endereco(logged_client):
    """Onde o agente procura esse movimento é no botão Transferir — e não em
    Editar. Mudar da família da frente para a dos fundos é mudança de moradia
    de verdade: a casa de origem sair da lista de destinos tirava o movimento
    do alcance dele."""
    fundos = _casa_repartida(logged_client)
    resp = logged_client.post(
        "/paciente/1/transferir", data={"casa_destino_id": f"1:{fundos}"}
    )
    assert resp.status_code == 302

    morador = _moradores()["Pai Da Frente"]
    assert morador["casa_id"] == 1
    assert morador["familia_id"] == fundos


def test_a_propria_casa_aparece_na_lista_de_destinos_quando_repartida(logged_client):
    _casa_repartida(logged_client)
    body = logged_client.get("/casa/1").get_data(as_text=True)
    frente, fundos = (f["id"] for f in _familias())
    assert f'value="1:{frente}"' in body
    assert f'value="1:{fundos}"' in body


def test_casa_de_familia_unica_nao_e_destino_dela_mesma(logged_client):
    """Sem núcleos não há para onde ir dentro do próprio endereço — oferecer a
    própria casa seria oferecer um no-op."""
    _casa_com_dois_moradores(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert 'value="1"' not in body
    assert 'value="2"' in body


def test_mesma_familia_e_recusada_como_destino(logged_client):
    fundos = _casa_repartida(logged_client)
    logged_client.post("/paciente/3/transferir", data={"casa_destino_id": f"1:{fundos}"})
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "já está nessa família" in body


def test_juntar_duas_familias_do_mesmo_endereco(logged_client):
    """O inverso do "acrescentar família": eram duas no cadastro e é uma só."""
    fundos = _casa_repartida(logged_client)
    frente = _familias()[0]["id"]
    resp = logged_client.post(
        "/casa/1/transferir",
        data={"casa_destino_id": f"1:{frente}", "familia_id": str(fundos)},
    )
    assert resp.status_code == 302
    assert _moradores()["Vizinho Do Fundo"]["familia_id"] == frente


def test_confirmacao_diz_a_familia_de_destino(logged_client):
    """Num endereço de duas famílias, dizer só a casa não confere nada: as duas
    respostas possíveis teriam o mesmo texto."""
    fundos = _casa_repartida(logged_client)
    logged_client.post("/paciente/1/transferir", data={"casa_destino_id": f"1:{fundos}"})
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "família Fundos" in body


def test_destino_sem_familia_continua_valendo(logged_client):
    """A casa não repartida manda só o id da casa — o formato antigo segue de pé."""
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    logged_client.post("/paciente/1/transferir", data={"casa_destino_id": "2"})

    morador = _moradores()["Pai Da Frente"]
    assert morador["casa_id"] == 2
    assert morador["familia_id"] is None


def test_familia_de_destino_de_outra_casa_e_ignorada(logged_client):
    """O par casa:família é conferido junto. Um POST forjado com o núcleo de um
    terceiro domicílio não pode prender o morador lá."""
    fundos = _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, casa_id=2, nome="Alvo Do Forjado", cpf="88888888888")

    # Casa de destino 2, mas núcleo da casa 1.
    logged_client.post("/paciente/4/transferir", data={"casa_destino_id": f"2:{fundos}"})

    morador = _moradores()["Alvo Do Forjado"]
    assert morador["casa_id"] == 2
    assert morador["familia_id"] is None


def test_destino_malformado_e_recusado(logged_client):
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    logged_client.post("/paciente/1/transferir", data={"casa_destino_id": "2:abc"})
    assert _moradores()["Pai Da Frente"]["casa_id"] == 1


@pytest.mark.parametrize(
    "destino",
    ["2:abc", "1:2:3", "-1:5", "2:-5", ":5", "<script>alert(1)</script>", "1' OR '1",
     "99999999999999999999", "2:99999999999999999999"],
)
def test_destino_hostil_nao_derruba_a_requisicao(logged_client, destino):
    """O último par é o que interessa: o SQLite recusa inteiro fora de 64 bits
    com OverflowError, e o id vem do cliente. Sem o teto, um número absurdo na
    querystring não dava "não encontrado" — dava 500."""
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    resp = logged_client.post("/paciente/1/transferir", data={"casa_destino_id": destino})
    assert resp.status_code == 302
    assert _moradores()["Pai Da Frente"]["casa_id"] == 1


def test_id_gigante_em_qualquer_rota_nao_derruba(logged_client):
    """O teto vive no `parse_positive_int`, então vale para todo id do sistema —
    não só para o destino da transferência."""
    _casa_com_dois_moradores(logged_client)
    for rota in ("/casa/1/transferir", "/paciente/1/transferir"):
        resp = logged_client.post(rota, data={"casa_destino_id": "9" * 25})
        assert resp.status_code == 302
    assert logged_client.get("/?quadra=" + "9" * 25).status_code == 200


def test_lista_de_destino_oferece_as_familias(logged_client):
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    body = logged_client.get("/casa/2").get_data(as_text=True)
    frente, fundos = (f["id"] for f in _familias())
    assert f'value="1:{frente}"' in body
    assert f'value="1:{fundos}"' in body
    assert "sem família definida" in body


def test_cada_destino_se_identifica_sozinho(logged_client):
    """Fechado, o <select> mostra só o texto da opção escolhida. "Frente"
    sozinho não diz de qual endereço é, e transferir para a casa errada não
    deixa rastro de que foi engano — a mesma razão do `rotulo_casa`."""
    _casa_repartida(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    body = logged_client.get("/casa/2").get_data(as_text=True)
    assert "Casa 1 · Sem quadra — Rua A, 1 · Frente" in body
    assert "Casa 1 · Sem quadra — Rua A, 1 · Fundos" in body


# ---------------------------------------------------------------------------
# Óbito sai da tela da casa, não do sistema
# ---------------------------------------------------------------------------
def test_obito_nao_fica_listado_na_casa(logged_client):
    """A tela da casa é de quem bate na porta. O falecido listado ali visita
    após visita é ruído para o agente e desnecessário para a família."""
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/paciente/2/status", data={"status": "obito"})
    logged_client.get("/casa/1")  # consome o flash da mudança (contém o nome)

    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Filha Da Frente" not in body


def test_quem_se_mudou_continua_guardado_na_casa(logged_client):
    """Só o óbito sai — mudou-se e fora de área continuam onde sempre estiveram."""
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/paciente/2/status", data={"status": "mudou_se"})

    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Registros guardados" in body
    assert "Filha Da Frente" in body


def test_a_casa_diz_onde_o_obito_foi_parar(logged_client):
    """Sem o rastro, o registro pareceria apagado — que é o oposto do que
    acontece: ele continua inteiro no sistema."""
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/paciente/2/status", data={"status": "obito"})

    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "registro(s) de óbito" in body
    assert "status=obito" in body


def test_obito_continua_inteiro_no_banco_e_na_lista(logged_client):
    _casa_com_dois_moradores(logged_client)
    logged_client.post("/paciente/2/status", data={"status": "obito"})

    morador = _moradores()["Filha Da Frente"]
    assert morador["casa_id"] == 1        # o vínculo com a casa é preservado
    assert morador["status"] == "obito"
    assert "Filha Da Frente" in logged_client.get("/pacientes?status=obito").get_data(as_text=True)


def test_obito_sai_tambem_do_cartao_da_familia(logged_client):
    _casa_repartida(logged_client)
    logged_client.post("/paciente/3/status", data={"status": "obito"})
    logged_client.get("/casa/1")  # consome o flash da mudança (contém o nome)
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Vizinho Do Fundo" not in body
    assert "registro(s) de óbito" in body


# ---------------------------------------------------------------------------
# Renomear e desfazer
# ---------------------------------------------------------------------------
def test_renomear_familia(logged_client):
    _casa_repartida(logged_client)
    familia = _familias()[0]["id"]
    resp = logged_client.post(f"/familia/{familia}/renomear", data={"nome": "Casa de cima"})
    assert resp.status_code == 302
    assert _familias()[0]["nome"] == "Casa de cima"


def test_renomear_para_vazio_e_recusado(logged_client):
    _casa_repartida(logged_client)
    familia = _familias()[0]["id"]
    logged_client.post(f"/familia/{familia}/renomear", data={"nome": "   "})
    assert _familias()[0]["nome"] == "Frente"


def test_desfazer_nucleo_nao_apaga_morador(logged_client):
    """Desfazer um agrupamento nunca pode apagar gente."""
    _casa_repartida(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome": "Terceira"})
    fundos = _familias()[1]["id"]

    resp = logged_client.post(f"/familia/{fundos}/excluir")
    assert resp.status_code == 302

    morador = _moradores()["Vizinho Do Fundo"]
    assert morador["casa_id"] == 1
    assert morador["familia_id"] is None


def test_desfazer_a_penultima_devolve_a_casa_a_familia_unica(logged_client):
    """Sobrando um núcleo só, ele não agrupa nada — a casa volta a ser a lista
    simples, sem um cabeçalho de grupo órfão na tela."""
    _casa_repartida(logged_client)
    fundos = _familias()[1]["id"]
    logged_client.post(f"/familia/{fundos}/excluir")

    assert _familias() == []
    assert all(m["familia_id"] is None for m in _moradores().values())
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "família(s) neste endereço" not in body


def test_moradores_sem_nucleo_aparecem_na_tela(logged_client):
    """Quem ficou por realocar tem de ser visível — não um vazio mudo."""
    _casa_repartida(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome": "Terceira"})
    fundos = _familias()[1]["id"]
    logged_client.post(f"/familia/{fundos}/excluir")

    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Sem família" in body
    assert "Vizinho Do Fundo" in body


def test_registro_guardado_diz_de_qual_familia_era(logged_client):
    """Numa casa repartida, "quem se mudou" sem dizer de qual família obriga o
    agente a adivinhar qual das duas esvaziou."""
    fundos = _casa_repartida(logged_client)
    logged_client.post(
        "/casa/1/status-familia", data={"status": "mudou_se", "familia_id": str(fundos)}
    )
    body = logged_client.get("/casa/1").get_data(as_text=True)
    guardados = body[body.index("Registros guardados"):]
    assert "Vizinho Do Fundo" in guardados
    assert "Fundos" in guardados


def test_ordem_das_familias_e_a_mesma_na_tela_e_no_pdf(logged_client):
    """Ordenadas por nome num lugar e por criação no outro, o agente que confere
    a folha contra a tela perde a correspondência."""
    from tests.conftest import texto_pdf

    criar_quadra(logged_client)
    _casa_com_dois_moradores(logged_client)
    # "Zebra" nasce primeiro: por nome ela viria depois, por criação vem antes.
    logged_client.post("/casa/1/familia/nova", data={"nome_atual": "Zebra", "nome": "Abelha"})
    abelha = _familias()[1]["id"]
    criar_paciente(logged_client, nome="Morador Da Abelha", cpf="99999999999")
    conn = db.get_db_connection()
    conn.execute("UPDATE pacientes SET familia_id = ? WHERE nome = 'Morador Da Abelha'", (abelha,))
    conn.commit()
    conn.close()

    tela = logged_client.get("/casa/1").get_data(as_text=True)
    texto = texto_pdf(logged_client.get("/exportar/pdf").data)
    assert tela.index("Zebra") < tela.index("Abelha")
    assert texto.index("Zebra") < texto.index("Abelha")


def test_excluir_casa_leva_as_familias_junto(logged_client):
    _casa_repartida(logged_client)
    logged_client.post("/casa/1/excluir")
    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM familias").fetchone()["c"]
    conn.close()
    assert total == 0


# ---------------------------------------------------------------------------
# Lixeira
# ---------------------------------------------------------------------------
def test_lixeira_devolve_o_morador_a_familia_de_origem(logged_client):
    fundos = _casa_repartida(logged_client)
    logged_client.post("/paciente/3/excluir")
    logged_client.post("/lixeira/3/restaurar")
    assert _moradores()["Vizinho Do Fundo"]["familia_id"] == fundos


def test_lixeira_restaura_sem_familia_se_o_nucleo_sumiu(logged_client):
    """O núcleo pode ser desfeito enquanto o registro espera na lixeira."""
    _casa_repartida(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome": "Terceira"})
    fundos = _familias()[1]["id"]

    logged_client.post("/paciente/3/excluir")
    logged_client.post(f"/familia/{fundos}/excluir")
    resp = logged_client.post("/lixeira/3/restaurar")
    assert resp.status_code == 302

    morador = _moradores()["Vizinho Do Fundo"]
    assert morador["casa_id"] == 1
    assert morador["familia_id"] is None


# ---------------------------------------------------------------------------
# O que a equipe reporta
# ---------------------------------------------------------------------------
def test_indicador_conta_nucleos_e_nao_casas(logged_client):
    """"Famílias cadastradas" sempre quis dizer núcleos. A casa de família única
    continua contando 1 — o número só se mexe quando o operador reparte."""
    import app as app_module

    _casa_com_dois_moradores(logged_client)
    assert app_module.calcular_perfil_epidemiologico()["familias"] == 1

    logged_client.post("/casa/1/familia/nova", data={"nome_atual": "Frente", "nome": "Fundos"})
    fundos = _familias()[1]["id"]
    criar_paciente(logged_client, nome="Vizinho Do Fundo", cpf="33333333333")
    conn = db.get_db_connection()
    conn.execute("UPDATE pacientes SET familia_id = ? WHERE nome = 'Vizinho Do Fundo'", (fundos,))
    conn.commit()
    conn.close()

    assert app_module.calcular_perfil_epidemiologico()["familias"] == 2


def test_nucleo_sem_morador_ativo_nao_conta(logged_client):
    import app as app_module

    fundos = _casa_repartida(logged_client)
    logged_client.post("/casa/1/status-familia", data={"status": "mudou_se", "familia_id": str(fundos)})
    assert app_module.calcular_perfil_epidemiologico()["familias"] == 1


def test_pdf_nao_reimprime_a_abertura_a_cada_familia(logged_client):
    """A abertura (título da seção e da quadra) pertence à casa, não ao núcleo.
    Passada em todas as voltas, ela era reimpressa no meio da folha uma vez por
    família — e o relatório passava a anunciar a mesma seção duas vezes."""
    from tests.conftest import texto_pdf

    criar_quadra(logged_client)
    _casa_repartida(logged_client)
    logged_client.post("/casa/1/familia/nova", data={"nome": "Puxadinho"})
    texto = texto_pdf(logged_client.get("/exportar/pdf").data)
    assert texto.count("Pacientes por quadra e casa") == 1


def test_pdf_separa_as_familias_do_mesmo_endereco(logged_client):
    """Duas famílias saindo como uma lista só de nove pessoas deixa quem vai a
    campo sem saber onde termina uma e começa a outra."""
    from tests.conftest import texto_pdf

    criar_quadra(logged_client)
    _casa_repartida(logged_client)
    texto = texto_pdf(logged_client.get("/exportar/pdf").data)
    assert "Frente" in texto
    assert "Fundos" in texto
    assert "Vizinho Do Fundo" in texto
