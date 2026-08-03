"""Busca de imóvel no painel — o ACS procura um lugar, não um registro.

Duas coisas são verificadas aqui: a gramática da consulta ("casa 42", "q3",
endereço, tipo) e a fronteira entre BUSCA e FILTRO — a busca localiza no
território inteiro, o filtro recorta o quadro, e uma não pode desfazer a outra.
"""
from app import casa_corresponde_busca, interpretar_busca_casa
from tests.conftest import criar_casa, criar_paciente, criar_quadra


# ---------------------------------------------------------------------------
# Leitura do bloco de resultados
#
# O quadro de casas abaixo da busca lista o território inteiro: asserção sobre
# o corpo inteiro passaria (ou falharia) por causa dele, não por causa da
# busca. Todo teste de resultado recorta o bloco certo antes de afirmar.
# ---------------------------------------------------------------------------
def _bloco(body, alvo, fim):
    inicio = body.index(f'id="{alvo}"')
    return body[inicio:body.index(fim, inicio)]


def bloco_pacientes(body):
    return _bloco(body, "busca-pacientes", 'id="busca-casas"')


def bloco_casas(body):
    return _bloco(body, "busca-casas", "</section>")


def _territorio(client):
    """Quadra 3 (id 1) com as casas 42 e 142; quadra 7 (id 2) com outra casa 42
    — a numeração recomeça a cada quadra. Mais um terreno baldio sem quadra."""
    criar_quadra(client, "3")
    criar_quadra(client, "7")
    criar_casa(client, endereco="Rua das Flores, 100", numero="42", quadra_id="1")
    criar_casa(client, endereco="Avenida Central, 900", numero="142", quadra_id="1")
    criar_casa(client, endereco="Travessa do Sol, 5", numero="42", quadra_id="2")
    client.post(
        "/casa/nova",
        data={"endereco": "Lote atras do mercado", "numero_casa": "8",
              "quadra_id": "", "tipo_imovel": "terreno_baldio"},
    )


# ---------------------------------------------------------------------------
# Gramática da consulta (unidade)
# ---------------------------------------------------------------------------
def test_interpreta_rotulo_com_numero_separado_e_colado():
    assert interpretar_busca_casa("casa 42") == (["42"], [], [])
    assert interpretar_busca_casa("q3") == ([], ["3"], [])
    assert interpretar_busca_casa("quadra 3") == ([], ["3"], [])
    assert interpretar_busca_casa("qd 7") == ([], ["7"], [])


def test_interpreta_consulta_mista():
    assert interpretar_busca_casa("Casa 42 Q3 flores") == (["42"], ["3"], ["flores"])


def test_rotulo_sem_numero_nao_vira_termo():
    """"casa" está no identificador de toda casa — deixá-lo como termo livre
    faria a consulta casar com o território inteiro."""
    assert interpretar_busca_casa("casa") == ([], [], [])


def test_pontuacao_e_acento_nao_atrapalham():
    assert interpretar_busca_casa("Rua das Flores, 100") == ([], [], ["rua", "das", "flores", "100"])
    assert interpretar_busca_casa("SÃO JOÃO") == ([], [], ["sao", "joao"])


def test_consulta_vazia_nao_casa_com_nada():
    casa = {"numero_casa": 42, "numero_quadra": 3, "endereco": "Rua das Flores", "tipo_imovel": "domicilio"}
    assert casa_corresponde_busca(casa, "") is False
    assert casa_corresponde_busca(casa, "   ") is False
    assert casa_corresponde_busca(casa, "casa") is False


# ---------------------------------------------------------------------------
# Busca pelo painel
# ---------------------------------------------------------------------------
def test_busca_por_numero_casa_por_palavra_inteira(logged_client):
    """"42" acha a Casa 42, nunca a 142: número casa por palavra inteira, senão
    procurar a casa 4 devolveria metade do território."""
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=42").get_data(as_text=True))
    assert "Rua das Flores, 100" in casas
    assert "Travessa do Sol, 5" in casas       # a Casa 42 da outra quadra também
    assert "Avenida Central, 900" not in casas  # a 142 não é a 42


def test_busca_com_rotulo_casa(logged_client):
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=casa+42").get_data(as_text=True))
    assert "Rua das Flores, 100" in casas
    assert "Avenida Central, 900" not in casas


def test_busca_por_quadra(logged_client):
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=q3").get_data(as_text=True))
    assert "Rua das Flores, 100" in casas
    assert "Avenida Central, 900" in casas
    assert "Travessa do Sol, 5" not in casas   # essa é da quadra 7


def test_numero_de_casa_e_de_quadra_se_somam(logged_client):
    """A numeração recomeça a cada quadra: "casa 42" sozinho é ambíguo, e o par
    casa+quadra é o que identifica um imóvel."""
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=casa+42+q7").get_data(as_text=True))
    assert "Travessa do Sol, 5" in casas
    assert "Rua das Flores, 100" not in casas


def test_busca_por_endereco(logged_client):
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=flores").get_data(as_text=True))
    assert "Rua das Flores, 100" in casas
    assert "Avenida Central, 900" not in casas


def test_busca_por_endereco_com_erro_de_digitacao(logged_client):
    """Digitação de campo, no celular, andando: o termo aproximado acha."""
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=florees").get_data(as_text=True))
    assert "Rua das Flores, 100" in casas
    assert "Avenida Central, 900" not in casas


def test_termo_curto_nao_casa_por_aproximacao(logged_client):
    """Abaixo de 4 letras a semelhança vira ruído ("rua" bate 0.67 com "sua").
    Termo curto casa por conteúdo exato, e só."""
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=sol").get_data(as_text=True))
    assert "Travessa do Sol, 5" in casas
    assert "Rua das Flores, 100" not in casas


def test_termos_de_endereco_se_somam(logged_client):
    """"flores 42" é a Casa 42 da Rua das Flores — não toda casa da rua mais
    toda casa 42 do território."""
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=flores+42").get_data(as_text=True))
    assert "Rua das Flores, 100" in casas
    assert "Travessa do Sol, 5" not in casas


def test_busca_por_tipo_de_imovel(logged_client):
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=terreno+baldio").get_data(as_text=True))
    assert "Lote atras do mercado" in casas
    assert "Rua das Flores, 100" not in casas


def test_busca_por_sem_quadra(logged_client):
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=sem+quadra").get_data(as_text=True))
    assert "Lote atras do mercado" in casas
    assert "Rua das Flores, 100" not in casas


def test_busca_de_imovel_sem_resultado(logged_client):
    _territorio(logged_client)
    body = logged_client.get("/?busca=rua+inexistente-zzz").get_data(as_text=True)
    assert "Nenhuma casa encontrada" in body


def test_os_dois_grupos_aparecem_mesmo_vazios(logged_client):
    """Grupo omitido deixaria o operador sem saber se aquela dimensão foi
    varrida — "não achei" e "não procurei" não podem parecer a mesma coisa."""
    _territorio(logged_client)
    body = logged_client.get("/?busca=zzz-nada").get_data(as_text=True)
    assert "Nenhum paciente encontrado" in body
    assert "Nenhuma casa encontrada" in body


def test_resultado_de_casa_leva_ao_painel_da_casa(logged_client):
    _territorio(logged_client)
    casas = bloco_casas(logged_client.get("/?busca=q7").get_data(as_text=True))
    assert 'href="/casa/3"' in casas


def test_resultado_de_casa_mostra_quadra_e_moradores(logged_client):
    """O rótulo do resultado é o mesmo do resto do app: casa + quadra."""
    _territorio(logged_client)
    criar_paciente(logged_client, casa_id=1, nome="Moradora Presente")
    casas = bloco_casas(logged_client.get("/?busca=casa+42+q3").get_data(as_text=True))
    assert "Casa 42 · Quadra 3" in casas
    assert "1 pac." in casas


def test_imovel_inativo_continua_encontravel_e_marcado(logged_client):
    """Inativar tira das contagens, não do território — é pela busca que se
    chega no cadastro para reativar."""
    _territorio(logged_client)
    logged_client.post("/casa/1/situacao", data={"status": "inativa"})
    casas = bloco_casas(logged_client.get("/?busca=flores").get_data(as_text=True))
    assert "Rua das Flores, 100" in casas
    assert "inativa" in casas


# ---------------------------------------------------------------------------
# Fronteira entre busca e filtro
# ---------------------------------------------------------------------------
def test_busca_nao_recorta_o_quadro_de_casas(logged_client):
    """Procurar um paciente não pode esvaziar a lista de casas: quem buscou uma
    pessoa não pediu para perder o quadro do território."""
    _territorio(logged_client)
    criar_paciente(logged_client, casa_id=1, nome="Joaquina Ferreira")
    body = logged_client.get("/?busca=Joaquina").get_data(as_text=True)
    assert "4 cadastrada(s)" in body
    assert "Avenida Central, 900" in body


def test_busca_ignora_o_filtro_ativo(logged_client):
    """Localizar varre o território inteiro: a Casa 42 aparece mesmo com o
    quadro recortado em outra quadra."""
    _territorio(logged_client)
    body = logged_client.get("/?busca=casa+42+q7&quadra=1").get_data(as_text=True)
    assert "Travessa do Sol, 5" in bloco_casas(body)
    assert "2 de 4 — filtro ativo" in body   # o quadro segue recortado na quadra 3


def test_buscar_preserva_o_filtro_e_a_ordem(logged_client):
    """O form da busca leva o recorte junto — o modal já faz o inverso."""
    _territorio(logged_client)
    body = logged_client.get("/?quadra=1&ordem=desc").get_data(as_text=True)
    assert '<input type="hidden" name="quadra" value="1">' in body
    assert '<input type="hidden" name="ordem" value="desc">' in body


def test_limpar_filtro_preserva_a_busca(logged_client):
    """Limpar o recorte não pode apagar o que o operador estava procurando."""
    _territorio(logged_client)
    body = logged_client.get("/?busca=flores&quadra=1").get_data(as_text=True)
    assert "busca=flores" in body


def test_limpar_busca_preserva_o_filtro(logged_client):
    _territorio(logged_client)
    body = logged_client.get("/?busca=flores&quadra=1").get_data(as_text=True)
    assert "quadra=1" in body


def test_consulta_gigante_e_truncada(logged_client):
    """Busca é O(termos × registros) com comparação aproximada em cada par: sem
    teto, um GET de 10 mil caracteres viraria minutos de CPU."""
    _territorio(logged_client)
    resp = logged_client.get("/?busca=" + "flores+" * 3000)
    assert resp.status_code == 200
    # O eco na caixa mostra o que de fato foi pesquisado, não o que foi enviado.
    body = resp.get_data(as_text=True)
    assert 'maxlength="120"' in body
    assert "flores " * 30 not in body


# ---------------------------------------------------------------------------
# Entrada hostil
#
# `busca` é querystring: chega do que o operador digita, mas também do que
# qualquer link colado no navegador mandar. Não vira SQL (a filtragem é em
# Python, sobre linhas já lidas), e sai da tela pelo autoescape do Jinja —
# estes testes seguram as duas afirmações.
# ---------------------------------------------------------------------------
def test_busca_com_script_e_escapada_na_tela(logged_client):
    _territorio(logged_client)
    resp = logged_client.get('/?busca=<script>alert(1)</script>')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_busca_com_sintaxe_de_sql_nao_derruba_nem_vaza(logged_client):
    _territorio(logged_client)
    resp = logged_client.get("/?busca=' OR 1=1 --")
    assert resp.status_code == 200
    assert "Nenhuma casa encontrada" in resp.get_data(as_text=True)


def test_busca_so_de_pontuacao_nao_casa_com_nada(logged_client):
    """Sem termo nenhum sobrando, a consulta não pode virar "tudo"."""
    _territorio(logged_client)
    body = logged_client.get("/?busca=...---%2F%2F").get_data(as_text=True)
    assert "Nenhuma casa encontrada" in body


def test_modal_de_filtro_usa_o_mecanismo_generico(logged_client):
    """Um só mecanismo de diálogo no app — o botão aponta para o id do modal."""
    _territorio(logged_client)
    body = logged_client.get("/").get_data(as_text=True)
    assert 'data-dialog-open="filter-dialog"' in body
    assert 'id="filter-dialog" class="filter-dialog" data-dialog' in body
    assert "data-filter-open" not in body
