"""Testes funcionais — CRUD de quadras/casas/pacientes, busca, exportação,
integridade de dados (backups, cascata) e estados de erro."""
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


def test_casas_listadas_em_ordem_de_numeracao(logged_client):
    """A lista do painel ordena pelo número da casa, independente da quadra."""
    import re

    criar_quadra(logged_client, "1")
    criar_quadra(logged_client, "2")
    # Cadastradas fora de ordem e em quadras diferentes de propósito.
    criar_casa(logged_client, endereco="Rua C", numero="9", quadra_id="1")
    criar_casa(logged_client, endereco="Rua A", numero="2", quadra_id="2")
    criar_casa(logged_client, endereco="Rua B", numero="5", quadra_id="")

    body = logged_client.get("/").get_data(as_text=True)
    secao_casas = body.split("Cadastrar casa")[1].split("Quadras")[0]
    # Ancorado no título do cartão: "Casa N" aparece também na confirmação de
    # exclusão ("Excluir Casa N · Quadra Q?"), e contar as duas contava cada
    # casa duas vezes — o que se quer aferir aqui é a ordem dos cartões.
    numeros = [int(n) for n in re.findall(r'text-slate-900">Casa (\d+)</h3>', secao_casas)]
    assert numeros == sorted(numeros)
    assert numeros == [2, 5, 9]
    # Listas longas rolam dentro do cartão em vez de esticar a página.
    assert "house-board-scroll" in body
    assert "quadra-list-scroll" in body


def test_casas_ordenacao_decrescente(logged_client):
    """?ordem=desc inverte a numeração; padrão e valor inválido caem em crescente."""
    import re

    criar_casa(logged_client, endereco="Rua C", numero="9", quadra_id="")
    criar_casa(logged_client, endereco="Rua A", numero="2", quadra_id="")
    criar_casa(logged_client, endereco="Rua B", numero="5", quadra_id="")

    def numeros_de(query):
        body = logged_client.get(query).get_data(as_text=True)
        secao = body.split("Cadastrar casa")[1].split("Quadras")[0]
        # Título do cartão, não qualquer "Casa N" (ver nota acima).
        return [int(n) for n in re.findall(r'text-slate-900">Casa (\d+)</h3>', secao)]

    assert numeros_de("/?ordem=desc") == [9, 5, 2]
    assert numeros_de("/?ordem=asc") == [2, 5, 9]
    # Valor inválido não quebra: volta ao padrão crescente.
    assert numeros_de("/?ordem=lixo") == [2, 5, 9]


def test_ordenacao_preserva_filtro_ativo(logged_client):
    """O botão de ordem mantém o filtro por tipo e o próprio sentido no link."""
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/?tipo=loja&ordem=desc").get_data(as_text=True)
    # Recorte por tipo preservado.
    assert "Loja Q1" in body
    assert "Loja sem quadra" in body
    assert "Domicílio Q1" not in body
    # Ordem decrescente aplicada dentro do recorte.
    secao = body.split("Cadastrar casa")[1].split("Quadras")[0]
    import re

    assert [int(n) for n in re.findall(r'text-slate-900">Casa (\d+)</h3>', secao)] == [3, 2]
    # O botão exibe o estado atual e o link do filtro leva ordem junto.
    assert "Decrescente" in body
    assert 'name="ordem" value="desc"' in body


def test_tipo_de_imovel_no_cadastro_e_nas_telas(logged_client):
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Av. Central, 100", "numero_casa": "1", "quadra_id": "", "tipo_imovel": "loja"},
    )
    assert "Loja" in logged_client.get("/").get_data(as_text=True)
    assert "Loja" in logged_client.get("/casa/1").get_data(as_text=True)

    # Demais tipos comerciais/comunitários seguem o mesmo caminho.
    for numero, (codigo, label) in enumerate(
        [("igreja", "Igreja"), ("pizzaria", "Pizzaria"), ("hamburgueria", "Hamburgueria")], start=2
    ):
        logged_client.post(
            "/casa/nova",
            data={"endereco": f"Ponto {numero}", "numero_casa": str(numero), "quadra_id": "", "tipo_imovel": codigo},
        )
        assert label in logged_client.get(f"/casa/{numero}").get_data(as_text=True)


def test_tipo_de_imovel_editavel(logged_client):
    criar_casa(logged_client)  # domicílio por padrão
    logged_client.post(
        "/casa/1/editar",
        data={"endereco": "Rua A, 1", "numero_casa": "1", "quadra_id": "", "tipo_imovel": "escola"},
    )
    assert "Escola" in logged_client.get("/casa/1").get_data(as_text=True)


def test_tipo_de_imovel_invalido_vira_domicilio(logged_client):
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Rua B, 2", "numero_casa": "1", "quadra_id": "", "tipo_imovel": "castelo"},
    )
    conn = db.get_db_connection()
    tipo = conn.execute("SELECT tipo_imovel FROM casas WHERE id = 1").fetchone()["tipo_imovel"]
    conn.close()
    assert tipo == "domicilio"


def test_vazias_conta_apenas_imoveis_residenciais(logged_client):
    # Domicílio e apartamento sem morador = achado; terreno baldio = esperado.
    criar_casa(logged_client, endereco="Domicílio vazio", numero="1")
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Apto 101", "numero_casa": "2", "quadra_id": "", "tipo_imovel": "apartamento"},
    )
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Terreno da esquina", "numero_casa": "3", "quadra_id": "", "tipo_imovel": "terreno_baldio"},
    )
    body = logged_client.get("/").get_data(as_text=True)
    assert "2 vazia(s)" in body


# ---------------------------------------------------------------------------
# Filtro de casas (tipo de imóvel + ocupação + quadra)
# ---------------------------------------------------------------------------
def _montar_territorio_para_filtro(logged_client):
    criar_quadra(logged_client, "1")
    criar_casa(logged_client, endereco="Domicílio Q1", numero="1", quadra_id="1")
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Loja Q1", "numero_casa": "2", "quadra_id": "1", "tipo_imovel": "loja"},
    )
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Loja sem quadra", "numero_casa": "3", "quadra_id": "", "tipo_imovel": "loja"},
    )


def test_filtro_por_tipo_de_imovel(logged_client):
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/?tipo=loja").get_data(as_text=True)
    assert "Loja Q1" in body
    assert "Loja sem quadra" in body
    assert "Domicílio Q1" not in body
    assert "2 de 3 — filtro ativo" in body


def test_filtro_por_quadra(logged_client):
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/?quadra=1").get_data(as_text=True)
    assert "Domicílio Q1" in body
    assert "Loja Q1" in body
    assert "Loja sem quadra" not in body


def test_filtro_sem_quadra(logged_client):
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/?quadra=0").get_data(as_text=True)
    assert "Loja sem quadra" in body
    assert "Domicílio Q1" not in body


def test_filtro_combinado_tipo_e_quadra(logged_client):
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/?tipo=loja&quadra=1").get_data(as_text=True)
    assert "Loja Q1" in body
    assert "Loja sem quadra" not in body
    assert "Domicílio Q1" not in body


def test_filtro_mostra_contagens_no_modal(logged_client):
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/").get_data(as_text=True)
    assert "Filtrar casas" in body                      # modal presente
    assert "Quadra 1 (2 casas)" in body                 # contagem por quadra
    assert "Sem quadra (1)" in body


def test_filtro_tipo_invalido_ignorado(logged_client):
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/?tipo=castelo&quadra=abc").get_data(as_text=True)
    assert "3 cadastrada(s)" in body                    # filtro não ativou
    assert "filtro ativo" not in body


def test_filtro_sem_resultado(logged_client):
    _montar_territorio_para_filtro(logged_client)
    body = logged_client.get("/?tipo=escola").get_data(as_text=True)
    assert "Nenhuma casa corresponde ao filtro" in body


def _territorio_com_ocupacao(logged_client):
    """Casa 1: com morador. Casa 2: domicílio vazio. Casa 3: loja sem morador
    (não é "vazia" — imóvel não residencial sem morador é o esperado)."""
    criar_casa(logged_client, endereco="Casa Com Morador", numero="1")
    criar_casa(logged_client, endereco="Casa Vazia", numero="2")
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Loja Sem Morador", "numero_casa": "3", "quadra_id": "",
              "tipo_imovel": "loja"},
    )
    criar_paciente(logged_client, casa_id=1, nome="Moradora Presente")


def test_filtro_com_moradores(logged_client):
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/?ocupacao=com_moradores").get_data(as_text=True)
    assert "Casa Com Morador" in body
    assert "Casa Vazia" not in body
    assert "Loja Sem Morador" not in body


def test_filtro_vazias_segue_a_regra_do_indicador(logged_client):
    """O filtro tem que devolver exatamente as casas que o card conta como
    vazias — inclusive não chamando de vazia a loja sem morador."""
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/?ocupacao=vazias").get_data(as_text=True)
    assert "Casa Vazia" in body
    assert "Casa Com Morador" not in body
    assert "Loja Sem Morador" not in body
    assert "1 de 3 — filtro ativo" in body

    painel = logged_client.get("/").get_data(as_text=True)
    assert "1 vazia(s)" in painel  # mesmo número do indicador


def test_filtro_de_ocupacao_ignora_imovel_inativo(logged_client):
    """Inativo não é vazio nem cheio: está fora da conta, e os dois recortes
    falam sobre o que conta."""
    _territorio_com_ocupacao(logged_client)
    logged_client.post("/casa/1/situacao", data={"status": "inativa"})
    logged_client.post("/casa/2/situacao", data={"status": "inativa"})

    com_moradores = logged_client.get("/?ocupacao=com_moradores").get_data(as_text=True)
    assert "Casa Com Morador" not in com_moradores

    vazias = logged_client.get("/?ocupacao=vazias").get_data(as_text=True)
    assert "Casa Vazia" not in vazias


def test_filtro_de_ocupacao_combina_com_tipo_e_quadra(logged_client):
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/?ocupacao=vazias&tipo=loja").get_data(as_text=True)
    assert "Nenhuma casa corresponde ao filtro" in body


def test_ocupacao_invalida_ignorada(logged_client):
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/?ocupacao=assombrada").get_data(as_text=True)
    assert "3 cadastrada(s)" in body
    assert "filtro ativo" not in body


def test_contagens_de_ocupacao_no_modal(logged_client):
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/").get_data(as_text=True)
    assert "Com moradores — entram na contagem (1)" in body
    assert "Vazias — domicílio sem morador (1)" in body


def test_ocupacao_sobrevive_a_troca_de_ordem(logged_client):
    """Inverter a ordenação não pode derrubar o recorte ativo."""
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/?ocupacao=vazias").get_data(as_text=True)
    assert "ocupacao=vazias" in body  # o link de ordem carrega o filtro junto


def test_casa_esvaziada_por_saida_de_morador_migra_de_recorte(logged_client):
    """Quem se muda ou vem a óbito sai da contagem da casa — e a casa passa a
    ser vazia nos dois lugares ao mesmo tempo, filtro e indicador."""
    _territorio_com_ocupacao(logged_client)
    logged_client.post("/paciente/1/status", data={"status": "mudou_se"})

    assert "Casa Com Morador" not in logged_client.get(
        "/?ocupacao=com_moradores"
    ).get_data(as_text=True)
    assert "Casa Com Morador" in logged_client.get("/?ocupacao=vazias").get_data(as_text=True)
    assert "2 vazia(s)" in logged_client.get("/").get_data(as_text=True)


def test_filtro_de_ocupacao_convive_com_a_busca(logged_client):
    """O modal é submetido com a busca ativa: o recorte não pode apagá-la."""
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/?busca=Moradora&ocupacao=com_moradores").get_data(as_text=True)
    assert "Moradora Presente" in body       # resultado da busca segue na tela
    assert "Casa Com Morador" in body        # e a lista respeita o recorte
    assert "Casa Vazia" not in body


def test_selects_do_filtro_tem_rotulo_acessivel(logged_client):
    """Controle sem nome acessível é invisível para leitor de tela."""
    _territorio_com_ocupacao(logged_client)
    body = logged_client.get("/").get_data(as_text=True)
    assert 'for="filtro-ocupacao"' in body and 'id="filtro-ocupacao"' in body
    assert 'for="filtro-quadra"' in body and 'id="filtro-quadra"' in body


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
    logged_client.get("/casa/1")  # consome o flash da exclusão (contém o nome)
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


def _texto_para_copiar(client, casa_id=1, indice=0):
    """Conteúdo que o botão 'copiar dados' entrega — o atributo vem escapado
    como HTML, então é preciso desfazer isso para ver o texto real."""
    import html
    import re

    corpo = client.get(f"/casa/{casa_id}").get_data(as_text=True)
    achados = re.findall(r'data-copy="([^"]*)"', corpo)
    return html.unescape(achados[indice])


def test_copiar_dados_do_paciente_sai_em_linhas(logged_client):
    """Um dado por linha: o texto é colado em prontuário e no WhatsApp, e em
    tira contínua não se lê nada."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Maria Copiada")
    assert _texto_para_copiar(logged_client).splitlines() == [
        "Nome: Maria Copiada",
        "CPF/CNS: 123.456.789-01",
        "Nascimento: 10/05/1990",
        "Telefone: (63) 99999-8888",
    ]


def test_copia_nao_leva_campo_em_branco(logged_client):
    """Cadastro recém-importado quase não tem dado: colar "Telefone:" sem
    telefone é ruído."""
    criar_casa(logged_client)
    criar_paciente(
        logged_client, nome="Sem Contato", cpf="", telefone="", data_nascimento=""
    )
    assert _texto_para_copiar(logged_client).splitlines() == ["Nome: Sem Contato"]


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
def test_pagina_exportar(logged_client):
    body = logged_client.get("/exportar").get_data(as_text=True)
    assert "Exportar relatório em PDF" in body
    assert "export-condition" in body          # filtro de comorbidades presente
    assert "exportFilteredPdfForm" in body     # form com prévia ao vivo
    assert "Exportar tudo" in body


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


def test_exclusao_de_paciente_e_reversivel_pela_lixeira(logged_client):
    """Contrato de dados sagrados: excluir paciente não destrói nada — o
    registro vai para a lixeira e volta inteiro com um Restaurar."""
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="Protegida Pela Lixeira")
    logged_client.post("/paciente/1/excluir")

    conn = db.get_db_connection()
    na_lixeira = conn.execute("SELECT COUNT(*) AS c FROM lixeira_pacientes").fetchone()["c"]
    conn.close()
    assert na_lixeira == 1

    logged_client.post("/lixeira/1/restaurar")
    body = logged_client.get("/casa/1").get_data(as_text=True)
    assert "Protegida Pela Lixeira" in body


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
