"""Testes end-to-end da navegação sem recarregar a página (smooth-navigation).

Diferente do resto da suíte, que usa o `test_client` do Flask (sem navegador,
sem JavaScript), estes testes sobem o servidor de verdade e dirigem um Chromium
real com o Playwright. É a única forma de provar o que o `test_client` não
alcança: que clicar num link troca apenas o `#app-main` via `fetch`, sem reload,
e que o diálogo de confirmação intercepta ações destrutivas.

O truque central: antes de navegar, gravamos `window.__spa` na página. Se a
navegação foi PARCIAL (fetch + troca de nó), o objeto `window` sobrevive e o
marcador continua lá. Se houve reload COMPLETO, a `window` é recriada e o
marcador some. É esse marcador que separa uma coisa da outra — a URL, sozinha,
fica igual nos dois casos.

Sem o navegador do Playwright instalado, o módulo inteiro é pulado (não quebra a
suíte). Para instalar: `python -m playwright install chromium`.
"""
import pytest

import db
from tests.conftest import chromium_instalado, entrar

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not chromium_instalado(),
        reason="Navegador do Playwright ausente — rode: python -m playwright install chromium",
    ),
]


# ---------------------------------------------------------------------------
# A infraestrutura e2e (servidor real, navegador, login) mora no conftest.py:
# é compartilhada com os outros arquivos e2e e o fixture de sessão do
# Playwright precisa ser único na suíte.
# ---------------------------------------------------------------------------
def _entrar(pagina, servidor):
    return entrar(pagina, servidor)


def _marcar_janela(pagina):
    """Deixa uma marca no objeto window. Sobrevive à troca parcial; não
    sobrevive a um reload completo."""
    pagina.evaluate("window.__spa = 'vivo'")


def _janela_sobreviveu(pagina):
    return pagina.evaluate("window.__spa") == "vivo"


def _semear_casa_com_paciente(nome="Fulano De Tal"):
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO casas (id, numero_casa, endereco, tipo_imovel) "
        "VALUES (1, 1, 'Rua A, 1', 'domicilio')"
    )
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, nome, status) VALUES (1, 1, ?, 'ativo')",
        (nome,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------
def test_login_leva_ao_painel(pagina, servidor):
    _entrar(pagina, servidor)
    assert pagina.locator("#app-main").is_visible()
    # A sidebar (fora do #app-main) está presente — a casca autenticada montou.
    assert pagina.locator('[data-nav-link][href$="/pacientes"]').count() == 1


def test_navegacao_por_link_e_parcial(pagina, servidor):
    """Clicar num link do menu troca só o conteúdo — a window é preservada,
    prova de que NÃO houve reload da página inteira."""
    _entrar(pagina, servidor)
    _marcar_janela(pagina)

    pagina.click('[data-nav-link][href$="/pacientes"]')
    pagina.wait_for_url("**/pacientes")

    assert _janela_sobreviveu(pagina)  # troca parcial, sem reload
    assert "Pacientes" in pagina.locator("#app-main").inner_text()


def test_submit_get_e_parcial_e_atualiza_conteudo(pagina, servidor):
    """Uma busca (form GET) também navega parcial e reflete o resultado no
    #app-main, sem recarregar a página."""
    _semear_casa_com_paciente(nome="JOAQUINA DA BUSCA")
    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/pacientes")
    pagina.wait_for_selector("#app-main")
    _marcar_janela(pagina)

    pagina.fill('input[name="busca"]', "Joaquina")
    pagina.press('input[name="busca"]', "Enter")
    pagina.wait_for_url("**/pacientes?*busca=Joaquina*")

    assert _janela_sobreviveu(pagina)
    assert "JOAQUINA DA BUSCA" in pagina.locator("#app-main").inner_text()


def test_logout_no_smooth_recarrega_a_pagina(pagina, servidor):
    """O form de logout tem data-no-smooth: precisa ser navegação completa
    (a window é recriada), senão a sessão não é descartada de fato."""
    _entrar(pagina, servidor)
    _marcar_janela(pagina)

    pagina.click('aside form[action$="/logout"] button[type="submit"]')
    pagina.wait_for_url("**/login")

    assert pagina.evaluate("window.__spa") is None  # reload completo


def test_voltar_do_navegador_e_parcial(pagina, servidor):
    """O botão Voltar do navegador (popstate) também usa a troca parcial —
    volta ao painel sem reload."""
    _entrar(pagina, servidor)
    _marcar_janela(pagina)

    pagina.click('[data-nav-link][href$="/pacientes"]')
    pagina.wait_for_url("**/pacientes")
    pagina.go_back()
    pagina.wait_for_url(f"{servidor}/")

    assert _janela_sobreviveu(pagina)


def test_dialogo_de_confirmacao_intercepta_exclusao(pagina, servidor):
    """Ação destrutiva (excluir paciente) abre o diálogo de confirmação em vez
    de disparar na hora; cancelar não exclui nada."""
    _semear_casa_com_paciente(nome="Nao Me Exclua")
    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/casa/1")
    pagina.wait_for_selector("#app-main")

    # O submit do form com data-confirm é interceptado — nada é enviado ainda.
    pagina.click('form[action$="/paciente/1/excluir"] button[type="submit"]')
    dialogo = pagina.locator("#confirm-dialog")
    dialogo.wait_for(state="visible")
    assert dialogo.is_visible()

    # Cancelar fecha o diálogo e mantém o paciente — nenhuma requisição saiu.
    # (O botão, não o backdrop, que também é [data-confirm-cancel] mas fica
    # atrás do painel.)
    pagina.locator("#confirm-dialog button[data-confirm-cancel]").click()
    dialogo.wait_for(state="hidden")
    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes WHERE id = 1").fetchone()["c"]
    conn.close()
    assert total == 1


def test_dialogo_confirmado_executa_exclusao(pagina, servidor):
    """Confirmando o diálogo, a exclusão realmente acontece: o paciente vai
    para a lixeira (some da tabela ativa)."""
    _semear_casa_com_paciente(nome="Pode Excluir")
    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/casa/1")
    pagina.wait_for_selector("#app-main")

    pagina.click('form[action$="/paciente/1/excluir"] button[type="submit"]')
    pagina.locator("#confirm-dialog").wait_for(state="visible")
    pagina.locator("#confirm-dialog [data-confirm-submit]").click()

    # A exclusão envia o form (navegação parcial) e mostra o flash de sucesso.
    pagina.wait_for_selector("text=Lixeira")
    conn = db.get_db_connection()
    ativos = conn.execute("SELECT COUNT(*) AS c FROM pacientes WHERE id = 1").fetchone()["c"]
    na_lixeira = conn.execute(
        "SELECT COUNT(*) AS c FROM lixeira_pacientes WHERE id = 1"
    ).fetchone()["c"]
    conn.close()
    assert ativos == 0
    assert na_lixeira == 1


def _semear_casas_com_enderecos_longos():
    """Doze casas com endereços de campo, do tamanho que o operador escreve."""
    enderecos = [
        "Rua das Palmeiras, 145 - Setor Aeroporto",
        "Avenida Juscelino Kubitschek, 1020, Quadra 12 Lote 4 - Centro",
        "Rua Projetada A, casa dos fundos, proximo ao poste 7 - Vila Nova",
    ]
    conn = db.get_db_connection()
    for numero in range(1, 13):
        conn.execute(
            "INSERT INTO casas (numero_casa, endereco, tipo_imovel) VALUES (?, ?, 'domicilio')",
            (numero, enderecos[(numero - 1) % len(enderecos)]),
        )
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, nome, status) VALUES (1, 1, 'Morador', 'ativo')"
    )
    conn.commit()
    conn.close()


def test_lista_do_select_nao_escapa_do_campo(pagina, servidor):
    """O picker de `appearance: base-select` nasce do tamanho da opção mais
    longa. Com o endereço inteiro numa opção, ele passava da borda do modal e
    subia por cima do próprio cabeçalho do diálogo. Presa ao campo, a lista
    abre abaixo, na largura dele, dentro da janela."""
    _semear_casas_com_enderecos_longos()
    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/casa/1")
    pagina.wait_for_selector("#app-main")

    pagina.click("button:has-text('Ações da casa')")
    pagina.click(".house-menu-item:has-text('Transferir família')")
    pagina.locator("#transfer-dialog").wait_for(state="visible")
    campo = pagina.locator("#transfer-dialog select")
    campo.click()

    medidas = pagina.evaluate(
        """(() => {
          const sel = document.querySelector('#transfer-dialog select');
          const campo = sel.getBoundingClientRect();
          const opcoes = [...sel.querySelectorAll('option')].map(o => o.getBoundingClientRect());
          return {
            larguraMaxima: Math.max(...opcoes.map(o => o.width)),
            larguraDoCampo: campo.width,
            direitaMaxima: Math.max(...opcoes.map(o => o.right)),
            topoDaLista: Math.min(...opcoes.map(o => o.top)),
            baseDoCampo: campo.bottom,
            janela: window.innerWidth,
          };
        })()"""
    )
    # Nenhuma opção é mais larga que o campo, nem vaza para fora da janela.
    assert medidas["larguraMaxima"] <= medidas["larguraDoCampo"] + 4
    assert medidas["direitaMaxima"] <= medidas["janela"]
    # E a lista desce a partir do campo, em vez de subir sobre o diálogo.
    assert medidas["topoDaLista"] >= medidas["baseDoCampo"] - 2


def test_detalhes_do_paciente_abrem_e_a_escolha_fica_salva(pagina, servidor):
    """O recolhimento é a resposta à tela poluída: fechado por padrão, abre por
    linha ou pela tabela inteira — e a escolha do interruptor sobrevive à
    navegação, para o agente não repetir o clique em cada casa."""
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO casas (id, numero_casa, endereco, tipo_imovel)"
        " VALUES (1, 1, 'Rua A, 1', 'domicilio')"
    )
    for indice, nome in enumerate(("Ana Com Detalhe", "Bruno Com Detalhe"), start=1):
        conn.execute(
            "INSERT INTO pacientes (id, casa_id, nome, status, nome_mae, condicoes_saude)"
            " VALUES (?, 1, ?, 'ativo', 'Mae Registrada', 'hipertensao')",
            (indice, nome),
        )
    conn.commit()
    conn.close()

    _entrar(pagina, servidor)
    pagina.goto(f"{servidor}/casa/1")
    pagina.wait_for_selector("#app-main")

    detalhe = pagina.locator("#detalhes-1")
    gatilho = pagina.locator('[data-detalhes-alvo="detalhes-1"]')
    assert detalhe.is_hidden()

    # Fechado, o gatilho anuncia o que existe e não o conteúdo: no navegador de
    # verdade é aqui que se vê se o texto cru vazou para o estado recolhido.
    fechado = gatilho.inner_text()
    assert "Detalhes" in fechado
    assert "1 condição" in fechado and "filiação" in fechado
    assert "Mae Registrada" not in fechado
    assert "Fechar detalhes" not in fechado

    # Uma linha por vez.
    gatilho.click()
    detalhe.wait_for(state="visible")
    assert gatilho.inner_text().strip() == "Fechar detalhes"
    assert pagina.locator("#detalhes-2").is_hidden()

    # O interruptor vale para a tabela inteira.
    pagina.locator("[data-detalhes-todos]").click()
    pagina.locator("#detalhes-2").wait_for(state="visible")

    # E a escolha volta com o conteúdo depois de navegar para outra página.
    pagina.click('a[href="/"]')
    pagina.wait_for_selector("text=Quadras e casas cadastradas")
    pagina.goto(f"{servidor}/casa/1")
    pagina.wait_for_selector("#app-main")
    assert pagina.locator("#detalhes-1").is_visible()
    assert pagina.locator("#detalhes-2").is_visible()
    assert pagina.get_attribute("[data-detalhes-todos]", "aria-pressed") == "true"


def test_controles_da_linha_nao_se_sobrepoem(pagina, servidor):
    """A coluna Ações alinha o grupo à direita: se os botões não couberem na
    célula, o excedente vaza para a ESQUERDA e o ícone do WhatsApp pousa em
    cima do "Ativo" da coluna Situação. A suíte inteira passava com os dois
    controles sobrepostos — HTML válido, layout quebrado —, então a medida
    tem de vir do navegador. Vale para toda largura: em layout fixo a célula
    não cresce com o conteúdo."""
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO casas (id, numero_casa, endereco, tipo_imovel)"
        " VALUES (1, 1, 'Rua A, 1', 'domicilio')"
    )
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, nome, cpf, data_nascimento, telefone,"
        " nome_mae, status) VALUES (1, 1, 'MARIA JOSE DE SOUZA SANTOS',"
        " '31520170149', '1961-01-27', '6496091751', 'ALTIVA', 'ativo')"
    )
    conn.commit()
    conn.close()

    _entrar(pagina, servidor)

    for largura in (1280, 1440, 1920):
        pagina.set_viewport_size({"width": largura, "height": 900})
        pagina.goto(f"{servidor}/casa/1")
        pagina.wait_for_selector("#app-main")
        medidas = pagina.evaluate(
            """() => {
              const tds = document.querySelectorAll(
                'table.patients-table tbody tr:first-child td');
              const grupo = tds[5].querySelector('div');
              const itens = [...grupo.children];
              const precisa = itens.reduce(
                (soma, el) => soma + el.getBoundingClientRect().width, 0)
                + (itens.length - 1) * 6;
              return {
                direitaDoSelect: tds[4].querySelector('select').getBoundingClientRect().right,
                esquerdaDoPrimeiroBotao: itens[0].getBoundingClientRect().left,
                caixaDoGrupo: grupo.getBoundingClientRect().width,
                precisa,
              };
            }"""
        )
        # O primeiro botão começa depois de onde o select termina.
        assert medidas["esquerdaDoPrimeiroBotao"] > medidas["direitaDoSelect"], (
            f"a {largura}px os controles da linha se sobrepõem"
        )
        # E o grupo cabe na própria célula, que é a causa-raiz do vazamento.
        assert medidas["precisa"] <= medidas["caixaDoGrupo"], (
            f"a {largura}px as ações precisam de {medidas['precisa']:.0f}px"
            f" e a célula oferece {medidas['caixaDoGrupo']:.0f}px"
        )


def test_resultado_da_busca_nao_e_esmagado_no_celular(pagina, servidor):
    """No celular, `.btn-secondary` vira 100% de largura — é a regra dos botões
    de formulário. Num resultado de busca, ao lado de um texto, com `shrink-0`
    impedindo o botão de ceder, isso empurrava o endereço para uma palavra por
    linha e o botão passava por cima do nome. HTML impecável, tela ilegível: a
    medida tem de vir do navegador, como no teste acima."""
    # Um termo que acerta os dois grupos: o endereço do imóvel e o nome de quem
    # mora nele — as duas listas de resultado precisam ser medidas.
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO casas (id, numero_casa, endereco, tipo_imovel)"
        " VALUES (1, 42, 'Rua das Flores Amarelas, 100', 'domicilio')"
    )
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, nome, status)"
        " VALUES (1, 1, 'JOAQUINA DAS FLORES SOUZA', 'ativo')"
    )
    conn.commit()
    conn.close()

    _entrar(pagina, servidor)
    pagina.set_viewport_size({"width": 390, "height": 844})
    pagina.goto(f"{servidor}/?busca=flores")
    pagina.wait_for_selector("#busca-casas .panel-scroll")
    pagina.wait_for_selector("#busca-pacientes .panel-scroll")

    for grupo in ("#busca-pacientes", "#busca-casas"):
        medidas = pagina.evaluate(
            """(seletor) => {
              const linha = document.querySelector(seletor + ' .panel-scroll > div');
              const texto = linha.firstElementChild;
              const acao = linha.lastElementChild;
              return {
                fimDoTexto: texto.getBoundingClientRect().right,
                inicioDaAcao: acao.getBoundingClientRect().left,
                larguraDoTexto: texto.getBoundingClientRect().width,
                larguraDaLinha: linha.getBoundingClientRect().width,
              };
            }""",
            grupo,
        )
        assert medidas["inicioDaAcao"] >= medidas["fimDoTexto"], (
            f"{grupo}: o botão cobre o texto do resultado"
        )
        # E o texto continua com metade da linha — sem isso ele "cabe", mas
        # quebrado em uma palavra por linha, que é o defeito real.
        assert medidas["larguraDoTexto"] >= medidas["larguraDaLinha"] * 0.5, (
            f"{grupo}: sobraram {medidas['larguraDoTexto']:.0f}px de"
            f" {medidas['larguraDaLinha']:.0f}px para o texto"
        )


def test_modal_de_filtro_abre_fecha_e_aplica(pagina, servidor):
    """O modal do painel usa o mecanismo genérico [data-dialog-open] — o mesmo
    dos diálogos da casa, depois de o JS próprio dele ser removido. O ciclo
    inteiro é verificado aqui, inclusive o destravamento do scroll: overlay que
    fecha sem soltar o `body` deixa a página presa."""
    _semear_casa_com_paciente()
    _entrar(pagina, servidor)

    travado = "document.body.classList.contains('confirm-dialog-open')"

    pagina.click('[data-dialog-open="filter-dialog"]')
    pagina.wait_for_selector("#filter-dialog.is-visible")
    assert pagina.evaluate(travado)

    pagina.keyboard.press("Escape")
    pagina.wait_for_selector("#filter-dialog", state="hidden")
    assert not pagina.evaluate(travado)

    pagina.click('[data-dialog-open="filter-dialog"]')
    pagina.wait_for_selector("#filter-dialog.is-visible")
    _marcar_janela(pagina)
    pagina.check('#filter-dialog input[name="tipo"][value="domicilio"]')
    pagina.click('#filter-dialog button[type="submit"]')
    pagina.wait_for_url("**/?*tipo=domicilio*")

    assert _janela_sobreviveu(pagina)   # aplicar filtro navega parcial
    assert not pagina.evaluate(travado)  # e solta o scroll
