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
    criar_paciente(logged_client, nome="MARIA APARECIDA")
    body = logged_client.get("/pacientes").get_data(as_text=True)
    assert "MARIA APARECIDA" in body
    assert "Importar e-SUS" in body


def test_filtro_por_status_e_quadra(logged_client):
    criar_quadra(logged_client, "1")
    criar_casa(logged_client, quadra_id="1")
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, casa_id=1, nome="ANA DA QUADRA", cpf="11111111111")
    criar_paciente(logged_client, casa_id=2, nome="BRUNO SEM QUADRA", cpf="22222222222")
    logged_client.post("/paciente/2/status", data={"status": "mudou_se"})
    logged_client.get("/pacientes")  # consome o flash do POST (contém o nome)

    body = logged_client.get("/pacientes?status=ativo").get_data(as_text=True)
    assert "ANA DA QUADRA" in body and "BRUNO SEM QUADRA" not in body

    body = logged_client.get("/pacientes?status=mudou_se").get_data(as_text=True)
    assert "BRUNO SEM QUADRA" in body and "ANA DA QUADRA" not in body

    body = logged_client.get("/pacientes?quadra=1").get_data(as_text=True)
    assert "ANA DA QUADRA" in body and "BRUNO SEM QUADRA" not in body

    body = logged_client.get("/pacientes?quadra=0").get_data(as_text=True)
    assert "BRUNO SEM QUADRA" in body and "ANA DA QUADRA" not in body


# ---------------------------------------------------------------------------
# Situação cadastral
# ---------------------------------------------------------------------------
def test_marcar_mudou_se_preserva_cadastro_fora_das_contagens(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="CARLOS MUDANTE")
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
    criar_paciente(logged_client, nome="DONA FALECIDA")
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
# Cadastro pela aba Pacientes (casa opcional)
# ---------------------------------------------------------------------------
def test_cadastrar_paciente_sem_casa_pela_lista(logged_client):
    resp = logged_client.post(
        "/pacientes/novo",
        data={"nome": "NOVO SEM CASA", "cpf": "12345678901", "casa_id": ""},
    )
    assert resp.status_code == 302
    assert "/pacientes" in resp.headers["Location"]

    conn = db.get_db_connection()
    row = conn.execute("SELECT casa_id, cpf FROM pacientes WHERE nome = 'NOVO SEM CASA'").fetchone()
    conn.close()
    assert row["casa_id"] is None
    assert row["cpf"] == "123.456.789-01"


def test_cadastrar_paciente_com_casa_pela_lista(logged_client):
    criar_casa(logged_client)
    resp = logged_client.post(
        "/pacientes/novo",
        data={"nome": "NOVO COM CASA", "cpf": "12345678901", "casa_id": "1"},
    )
    assert resp.status_code == 302

    conn = db.get_db_connection()
    casa_id = conn.execute(
        "SELECT casa_id FROM pacientes WHERE nome = 'NOVO COM CASA'"
    ).fetchone()["casa_id"]
    conn.close()
    assert casa_id == 1


def test_cadastrar_pela_lista_valida_casa_e_documento(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="TITULAR", cpf="12345678901")

    # Casa inexistente: re-render com erro, nada gravado.
    resp = logged_client.post(
        "/pacientes/novo", data={"nome": "CASA FANTASMA", "casa_id": "99"}
    )
    assert resp.status_code == 200

    # CPF duplicado: rejeitado.
    resp = logged_client.post(
        "/pacientes/novo", data={"nome": "IMPOSTOR", "cpf": "123.456.789-01", "casa_id": ""}
    )
    assert resp.status_code == 200

    # Nome vazio: rejeitado.
    resp = logged_client.post("/pacientes/novo", data={"nome": "", "casa_id": ""})
    assert resp.status_code == 200

    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 1  # só o Titular


# ---------------------------------------------------------------------------
# Paginação
# ---------------------------------------------------------------------------
def _semear_muitos_pacientes(total):
    """Inserção direta: rápida e com ordem alfabética previsível (P000…)."""
    conn = db.get_db_connection()
    conn.execute("INSERT INTO casas (numero_casa, endereco) VALUES (1, 'Rua A, 1')")
    for i in range(total):
        conn.execute(
            "INSERT INTO pacientes (casa_id, nome) VALUES (1, ?)", (f"P{i:03d} Da Silva",)
        )
    conn.commit()
    conn.close()


def test_paginacao_padrao_de_50(logged_client):
    _semear_muitos_pacientes(60)
    body = logged_client.get("/pacientes").get_data(as_text=True)
    assert "Mostrando <strong class=\"text-slate-700\">1–50</strong>" in body
    assert "P049 Da Silva" in body
    assert "P050 Da Silva" not in body  # 51º fica para a página 2

    body2 = logged_client.get("/pacientes?pagina=2").get_data(as_text=True)
    assert "51–60" in body2
    assert "P050 Da Silva" in body2
    assert "P049 Da Silva" not in body2


def test_paginacao_tamanho_selecionavel(logged_client):
    _semear_muitos_pacientes(60)
    body = logged_client.get("/pacientes?por_pagina=25").get_data(as_text=True)
    assert "1–25" in body
    assert "P024 Da Silva" in body
    assert "P025 Da Silva" not in body

    body3 = logged_client.get("/pacientes?por_pagina=25&pagina=3").get_data(as_text=True)
    assert "51–60" in body3


def test_paginacao_valores_invalidos_caem_no_padrao(logged_client):
    _semear_muitos_pacientes(60)
    # Tamanho fora da whitelist → 50; página não numérica → 1.
    body = logged_client.get("/pacientes?por_pagina=999&pagina=abc").get_data(as_text=True)
    assert "1–50" in body
    # Página além do fim → grampeada na última, nunca 500 nem lista vazia.
    body = logged_client.get("/pacientes?pagina=99").get_data(as_text=True)
    assert "51–60" in body


def test_ver_todos_desliga_a_paginacao(logged_client):
    _semear_muitos_pacientes(60)
    body = logged_client.get("/pacientes?por_pagina=todos").get_data(as_text=True)
    assert "1–60" in body
    assert "P000 Da Silva" in body and "P059 Da Silva" in body
    assert 'aria-label="Paginação' not in body  # navegação some com página única
    # A escolha sobrevive ao filtro (hidden no form de busca).
    assert 'name="por_pagina" value="todos"' in body


def test_excluir_paciente_pela_lista_volta_para_a_lista(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="PARA EXCLUIR", cpf="11111111111")
    criar_paciente(logged_client, nome="QUE FICA", cpf="22222222222")

    resp = logged_client.post(
        "/paciente/1/excluir", data={"next": "/pacientes?status=ativo"}
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/pacientes?status=ativo")

    conn = db.get_db_connection()
    nomes = [r["nome"] for r in conn.execute("SELECT nome FROM pacientes").fetchall()]
    na_lixeira = conn.execute("SELECT COUNT(*) AS c FROM lixeira_pacientes").fetchone()["c"]
    conn.close()
    assert nomes == ["QUE FICA"]
    # Rede de segurança: o excluído está na lixeira, restaurável.
    assert na_lixeira == 1


def test_excluir_com_next_malicioso_nao_redireciona_fora(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    resp = logged_client.post(
        "/paciente/1/excluir", data={"next": "https://evil.example.com"}
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_janela_de_paginacao_com_elipses():
    import app as app_module

    janela = app_module._janela_paginacao
    assert janela(3, 7) == [1, 2, 3, 4, 5, 6, 7]  # até 7: todas
    assert janela(5, 20) == [1, None, 4, 5, 6, None, 20]
    assert janela(1, 20) == [1, 2, None, 20]
    assert janela(20, 20) == [1, None, 19, 20]
    assert janela(2, 20) == [1, 2, 3, None, 20]


def test_paginacao_respeita_filtros(logged_client):
    _semear_muitos_pacientes(60)
    logged_client.post("/paciente/1/status", data={"status": "mudou_se"})  # P000
    logged_client.get("/pacientes")  # consome o flash do POST (contém o nome)
    body = logged_client.get("/pacientes?status=ativo&por_pagina=25&pagina=3").get_data(as_text=True)
    # 59 ativos → página 3 de 25 mostra 51–59.
    assert "51–59" in body
    assert "P000 Da Silva" not in body


# ---------------------------------------------------------------------------
# Alteração de status em massa
# ---------------------------------------------------------------------------
def test_status_em_massa_altera_apenas_selecionados(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="UM", cpf="11111111111")
    criar_paciente(logged_client, nome="DOIS", cpf="22222222222")
    criar_paciente(logged_client, nome="TRÊS", cpf="33333333333")

    resp = logged_client.post(
        "/pacientes/status-em-massa",
        data={"status": "mudou_se", "paciente_ids": ["1", "2"]},
    )
    assert resp.status_code == 302

    conn = db.get_db_connection()
    status = {
        row["nome"]: row["status"]
        for row in conn.execute("SELECT nome, status FROM pacientes").fetchall()
    }
    conn.close()
    assert status == {"UM": "mudou_se", "DOIS": "mudou_se", "TRÊS": "ativo"}
    # Mutação em lote sempre cria backup antes.
    assert any("antes_status_em_massa" in b["nome"] for b in db.listar_backups())


def test_status_em_massa_reativa_em_lote(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="UM", cpf="11111111111")
    criar_paciente(logged_client, nome="DOIS", cpf="22222222222")
    logged_client.post("/pacientes/status-em-massa", data={"status": "obito", "paciente_ids": ["1", "2"]})
    logged_client.post("/pacientes/status-em-massa", data={"status": "ativo", "paciente_ids": ["1", "2"]})

    conn = db.get_db_connection()
    total_ativos = conn.execute(
        "SELECT COUNT(*) AS c FROM pacientes WHERE status = 'ativo'"
    ).fetchone()["c"]
    conn.close()
    assert total_ativos == 2


def test_status_em_massa_valida_entrada(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)

    # Status inválido: nada muda.
    logged_client.post(
        "/pacientes/status-em-massa", data={"status": "hackeado", "paciente_ids": ["1"]}
    )
    assert _status_de()["status"] == "ativo"

    # Sem seleção: nada muda, redirect amigável.
    resp = logged_client.post("/pacientes/status-em-massa", data={"status": "obito"})
    assert resp.status_code == 302
    assert _status_de()["status"] == "ativo"

    # IDs não numéricos são ignorados sem quebrar.
    logged_client.post(
        "/pacientes/status-em-massa",
        data={"status": "obito", "paciente_ids": ["abc", "1; DROP TABLE pacientes"]},
    )
    assert _status_de()["status"] == "ativo"


# ---------------------------------------------------------------------------
# Unicidade de CPF/CNS
# ---------------------------------------------------------------------------
def test_cpf_duplicado_rejeitado_no_cadastro(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="TITULAR DO CPF", cpf="12345678901")
    resp = criar_paciente(logged_client, nome="IMPOSTOR", cpf="123.456.789-01")
    assert resp.status_code == 200  # re-render com erro, nada gravado

    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 1


def test_cpf_duplicado_rejeitado_na_edicao(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="PRIMEIRO", cpf="12345678901")
    criar_paciente(logged_client, nome="SEGUNDO", cpf="98765432100")

    resp = logged_client.post(
        "/paciente/2/editar",
        data={"nome": "SEGUNDO", "cpf": "12345678901"},
    )
    assert resp.status_code == 200  # re-render com erro

    conn = db.get_db_connection()
    cpf = conn.execute("SELECT cpf FROM pacientes WHERE id = 2").fetchone()["cpf"]
    conn.close()
    assert "987" in cpf  # documento original preservado


def test_editar_mantendo_o_proprio_cpf_permitido(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="TITULAR", cpf="12345678901")
    resp = logged_client.post(
        "/paciente/1/editar",
        data={"nome": "TITULAR RENOMEADO", "cpf": "123.456.789-01"},
    )
    assert resp.status_code == 302  # o próprio documento não conta como duplicado

    conn = db.get_db_connection()
    nome = conn.execute("SELECT nome FROM pacientes WHERE id = 1").fetchone()["nome"]
    conn.close()
    assert nome == "TITULAR RENOMEADO"


def test_pacientes_sem_documento_podem_coexistir(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="BEBÊ UM", cpf="")
    resp = criar_paciente(logged_client, nome="BEBÊ DOIS", cpf="")
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
    criar_paciente(logged_client, nome="EVA TRANSFERIDA")
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
    criar_paciente(logged_client, nome="PAI ATIVO", cpf="11111111111")
    criar_paciente(logged_client, nome="FILHA ATIVA", cpf="22222222222")
    criar_paciente(logged_client, nome="AVÓ QUE JA MUDOU", cpf="33333333333")
    logged_client.post("/paciente/3/status", data={"status": "mudou_se"})

    resp = logged_client.post("/casa/1/transferir", data={"casa_destino_id": "2"})
    assert resp.status_code == 302

    conn = db.get_db_connection()
    casas = {
        row["nome"]: row["casa_id"]
        for row in conn.execute("SELECT nome, casa_id FROM pacientes").fetchall()
    }
    conn.close()
    assert casas["PAI ATIVO"] == 2
    assert casas["FILHA ATIVA"] == 2
    assert casas["AVÓ QUE JA MUDOU"] == 1  # registro guardado fica na casa antiga


def test_transferir_familia_para_mesma_casa_rejeitado(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client)
    logged_client.post("/casa/1/transferir", data={"casa_destino_id": "1"})
    assert _status_de()["casa_id"] == 1


# ---------------------------------------------------------------------------
# Situação da família inteira (pelo painel da casa)
# ---------------------------------------------------------------------------
def _familia(logged_client):
    """Três moradores na casa 1; a avó já consta como óbito."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="PAI DA CASA", cpf="11111111111")
    criar_paciente(logged_client, nome="FILHA DA CASA", cpf="22222222222")
    criar_paciente(logged_client, nome="AVÓ FALECIDA", cpf="33333333333")
    logged_client.post("/paciente/3/status", data={"status": "obito"})


def _situacoes():
    conn = db.get_db_connection()
    linhas = conn.execute("SELECT nome, status, casa_id FROM pacientes").fetchall()
    conn.close()
    return {linha["nome"]: linha["status"] for linha in linhas}


def test_familia_inteira_marcada_como_mudou_se(logged_client):
    _familia(logged_client)
    resp = logged_client.post("/casa/1/status-familia", data={"status": "mudou_se"})
    assert resp.status_code == 302

    situacoes = _situacoes()
    assert situacoes["PAI DA CASA"] == "mudou_se"
    assert situacoes["FILHA DA CASA"] == "mudou_se"


def test_obito_nunca_e_alterado_pela_acao_da_familia(logged_client):
    """Marcar a casa inteira não pode reescrever quem já foi registrado como
    óbito — nem para fora de área, nem de volta para ativo."""
    _familia(logged_client)
    logged_client.post("/casa/1/status-familia", data={"status": "fora_de_area"})
    assert _situacoes()["AVÓ FALECIDA"] == "obito"

    logged_client.post("/casa/1/status-familia", data={"status": "ativo"})
    assert _situacoes()["AVÓ FALECIDA"] == "obito"


def test_familia_sai_das_contagens_e_fica_guardada_na_casa(logged_client):
    _familia(logged_client)
    logged_client.post("/casa/1/status-familia", data={"status": "fora_de_area"})

    painel = logged_client.get("/").get_data(as_text=True)
    assert ">0</p>" in painel  # nenhum paciente ativo no território

    casa = logged_client.get("/casa/1").get_data(as_text=True)
    assert "PAI DA CASA" in casa           # cadastro continua na casa
    assert "Registros guardados" in casa


def test_familia_volta_a_ativa(logged_client):
    _familia(logged_client)
    logged_client.post("/casa/1/status-familia", data={"status": "mudou_se"})
    logged_client.post("/casa/1/status-familia", data={"status": "ativo"})

    situacoes = _situacoes()
    assert situacoes["PAI DA CASA"] == "ativo"
    assert situacoes["FILHA DA CASA"] == "ativo"
    assert situacoes["AVÓ FALECIDA"] == "obito"


def test_status_de_familia_invalido_rejeitado(logged_client):
    """Óbito em massa não passa: a lista de válidos é fechada."""
    _familia(logged_client)
    for invalido in ("obito", "sumiu", ""):
        logged_client.post("/casa/1/status-familia", data={"status": invalido})
    situacoes = _situacoes()
    assert situacoes["PAI DA CASA"] == "ativo"
    assert situacoes["FILHA DA CASA"] == "ativo"


def test_status_de_familia_em_casa_inexistente(logged_client):
    resp = logged_client.post("/casa/99/status-familia", data={"status": "mudou_se"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_status_de_familia_nao_atinge_outras_casas(logged_client):
    _familia(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(logged_client, casa_id=2, nome="VIZINHO INTACTO", cpf="44444444444")

    logged_client.post("/casa/1/status-familia", data={"status": "mudou_se"})
    assert _situacoes()["VIZINHO INTACTO"] == "ativo"


def test_acao_da_familia_gera_backup_antes(logged_client):
    """Mutação em lote: o estado anterior fica salvo antes de qualquer UPDATE."""
    _familia(logged_client)
    antes = len(db.listar_backups())
    logged_client.post("/casa/1/status-familia", data={"status": "mudou_se"})
    assert len(db.listar_backups()) == antes + 1


def test_casa_sem_morador_nao_mostra_o_controle_da_familia(logged_client):
    criar_casa(logged_client)
    corpo = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Situação da família" not in corpo


# ---------------------------------------------------------------------------
# Menu de ações do painel da casa
# ---------------------------------------------------------------------------
def test_menu_reune_todas_as_acoes_da_casa(logged_client):
    """Um botão só: o que era três botões no cabeçalho e duas seções no fim da
    página virou uma lista."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="MORADORA")
    corpo = logged_client.get("/casa/1").get_data(as_text=True)

    assert 'x-data="houseMenu"' in corpo
    assert "Ações da casa" in corpo
    for acao in (
        "Cadastrar paciente",
        "Transferir família",
        "Situação da família",
        "Editar casa",
        "Situação do imóvel",
    ):
        assert acao in corpo

    # Os dois diálogos existem no HTML e apontam para as rotas certas.
    assert 'id="dialogo-familia"' in corpo
    assert 'id="dialogo-imovel"' in corpo
    assert 'action="/casa/1/status-familia"' in corpo
    assert 'action="/casa/1/situacao"' in corpo


def test_detalhe_do_paciente_nasce_recolhido_com_resumo(logged_client):
    """A faixa de detalhes ocupava três linhas por morador. Agora ela nasce
    fechada, e a linha anuncia o que existe ali — sem despejar o conteúdo, que
    era a poluição que o recolhimento veio resolver."""
    criar_casa(logged_client)
    logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "MARIA COM TUDO", "cpf": "11111111111", "telefone": "",
              "data_nascimento": "1961-01-27", "sexo": "Feminino",
              "nome_pai": "VICENTE ANTONIO", "nome_mae": "ALTIVA MARIA",
              "observacao": "HIPERTENSA. Uso continuo de METFORMINA",
              "condicoes_saude": ["hipertensao", "diabetes"]},
    )
    corpo = logged_client.get("/casa/1").get_data(as_text=True)

    # O bloco existe, porém fechado.
    assert 'id="detalhes-1" class="patient-detalhes" hidden' in corpo
    assert 'aria-expanded="false"' in corpo
    assert 'aria-controls="detalhes-1"' in corpo

    # Fechada, a linha diz o que há dentro, na ordem clínica primeiro.
    inicio = corpo.index('class="patient-summary-sinais"')
    sinais = corpo[inicio:corpo.index("</span>", inicio)]
    assert "2 condições" in sinais
    assert sinais.index("2 condições") < sinais.index("observação")
    assert sinais.index("observação") < sinais.index("filiação")

    # E o conteúdo de verdade não vaza para o estado fechado: ele mora no bloco
    # recolhido, depois do resumo.
    for cru in ("Tem hipertensão arterial", "METFORMINA", "VICENTE ANTONIO"):
        assert cru not in sinais
        assert cru in corpo[corpo.index('id="detalhes-1"'):]


def test_resumo_recolhido_concorda_o_singular(logged_client):
    """"1 condições" é o tipo de detalhe que denuncia software descuidado."""
    criar_casa(logged_client)
    logged_client.post(
        "/casa/1/paciente/novo",
        data={"nome": "UMA CONDICAO", "cpf": "11111111111", "telefone": "",
              "data_nascimento": "1961-01-27", "sexo": "Feminino",
              "nome_pai": "", "nome_mae": "", "observacao": "",
              "condicoes_saude": ["hipertensao"]},
    )
    corpo = logged_client.get("/casa/1").get_data(as_text=True)
    inicio = corpo.index('class="patient-summary-sinais"')
    sinais = corpo[inicio:corpo.index("</span>", inicio)]
    assert "1 condição" in sinais
    assert "condições" not in sinais


def test_paciente_sem_detalhe_nao_ganha_linha_de_resumo(logged_client):
    """Sem condição, observação nem filiação não há o que recolher: a linha do
    morador fica sozinha, sem afordância morta."""
    criar_casa(logged_client)
    criar_paciente(
        logged_client, nome="SEM DETALHE", nome_pai="", nome_mae="", observacao=""
    )
    corpo = logged_client.get("/casa/1").get_data(as_text=True)
    assert "SEM DETALHE" in corpo
    assert "patient-summary-texto" not in corpo
    assert "patient-detalhes" not in corpo


def test_interruptor_de_detalhes_da_tabela(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="COM FILIACAO", nome_pai="PAI PRESENTE")
    corpo = logged_client.get("/casa/1").get_data(as_text=True)
    assert "data-detalhes-todos" in corpo
    assert "Abrir detalhes" in corpo


def test_menu_esconde_o_que_nao_se_aplica_a_casa_vazia(logged_client):
    """Casa sem morador não oferece transferir família nem situação da família
    — e o diálogo correspondente nem é renderizado."""
    criar_casa(logged_client)
    corpo = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Transferir família" not in corpo
    assert 'id="dialogo-familia"' not in corpo
    # O do imóvel continua: inativar não depende de morador.
    assert 'id="dialogo-imovel"' in corpo
    assert "Situação do imóvel" in corpo


def test_situacao_individual_pelo_painel_da_casa(logged_client):
    """A coluna Situação resolve o caso de um morador só — sem precisar ir até
    a página Pacientes nem aplicar à família inteira."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="QUEM MUDOU", cpf="11111111111")
    criar_paciente(logged_client, nome="QUEM FICOU", cpf="22222222222")

    corpo = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Situação" in corpo
    assert 'aria-label="Situação de QUEM MUDOU"' in corpo

    resp = logged_client.post(
        "/paciente/1/status", data={"status": "mudou_se", "next": "/casa/1"}
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/casa/1")

    situacoes = _situacoes()
    assert situacoes["QUEM MUDOU"] == "mudou_se"
    assert situacoes["QUEM FICOU"] == "ativo"  # o vizinho de tabela não se mexe

    casa = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Registros guardados" in casa  # a linha migrou para a seção de baixo


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
    decisão do operador ("Definir casa"). O cadastro entra limpo, sem
    observação gerada."""
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

    joao = next(p for p in pacientes if p["nome"] == "JOAO IMPORTADO")
    assert joao["cpf"] == "700 0000 0000 0001"  # CNS quando não há CPF
    assert joao["telefone"] == "(64) 3671-0002"  # residencial como alternativa

    # Cadastro entra limpo — nenhuma observação de importação gerada.
    assert all(p["observacao"] == "" for p in pacientes)


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


def test_migracao_limpa_observacoes_de_importacao_antigas(logged_client):
    """Bancos que importaram antes desta versão têm a observação gerada —
    o init_db limpa só o formato gerado, preservando texto do operador."""
    criar_casa(logged_client)
    conn = db.get_db_connection()
    casos = [
        ("Antigo Simples", "Importado do e-SUS"),
        ("Antigo Com Endereco", "Importado do e-SUS. Endereço no arquivo: Rua X, 1 - CENTRO"),
        ("Observacao Do Operador", "Acamado, visitar às terças"),
        ("Editado Pelo Operador", "Importado do e-SUS mas confirmei na visita"),
    ]
    for nome, obs in casos:
        conn.execute(
            "INSERT INTO pacientes (casa_id, nome, observacao) VALUES (1, ?, ?)", (nome, obs)
        )
    conn.commit()
    conn.close()

    db.init_db()  # reaplica migrações (inclusive a padronização dos nomes)

    conn = db.get_db_connection()
    observacoes = {
        row["nome"]: row["observacao"]
        for row in conn.execute("SELECT nome, observacao FROM pacientes").fetchall()
    }
    conn.close()
    assert observacoes["ANTIGO SIMPLES"] == ""
    assert observacoes["ANTIGO COM ENDERECO"] == ""
    assert observacoes["OBSERVACAO DO OPERADOR"] == "Acamado, visitar às terças"
    assert observacoes["EDITADO PELO OPERADOR"] == "Importado do e-SUS mas confirmei na visita"


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
    assert "PACIENTE LEGADO" in logged_client.get("/pacientes").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Quadra no painel da casa
# ---------------------------------------------------------------------------
def test_painel_da_casa_mostra_a_quadra_e_leva_a_listagem_filtrada(logged_client):
    """A quadra é o contexto hierárquico da casa e aparece acima do título, com
    link para a listagem já filtrada por ela."""
    criar_quadra(logged_client, numero="13")
    criar_casa(logged_client, endereco="Rua das Flores, 42", numero="42", quadra_id="1")
    corpo = logged_client.get("/casa/1").get_data(as_text=True)

    assert 'class="house-quadra"' in corpo
    assert "QUADRA 13" in corpo.upper()
    assert 'href="/?quadra=1"' in corpo

    # E não sobra a pílula antiga dizendo a mesma coisa duas vezes.
    assert corpo.count("Quadra 13") == 1


def test_casa_sem_quadra_diz_que_esta_sem_quadra(logged_client):
    """Silêncio aqui era ambíguo: o agente não sabia se a casa estava sem
    quadra ou se a tela apenas não mostrava. O link leva às casas por
    localizar (filtro `0`)."""
    criar_casa(logged_client, endereco="Rua B, 9", numero="9")
    corpo = logged_client.get("/casa/1").get_data(as_text=True)

    assert "Sem quadra" in corpo
    assert 'href="/?quadra=0"' in corpo
