"""Contraste de texto (WCAG AA) medido no navegador, nos dois temas.

Por que no navegador e não lendo o CSS: o contraste real depende da cascata
inteira — token, utilitária, override de tema e o fundo que o elemento herda de
algum ancestral. Ler folha de estilo não responde "esse texto, nessa tela, dá
4,5:1?". Só a página montada responde.

Foi assim que apareceram os dois defeitos que este arquivo trava: o botão
primário (branco sobre teal-600, 3,74:1 no claro e 2,49:1 no escuro) e o texto
secundário da sidebar (slate sobre #04302e, 3,01:1) — ambos invisíveis para a
suíte anterior, que era toda de HTML e status HTTP.

Cuidado ao mexer: a medida precisa acontecer DEPOIS das transições de cor. O
tema anima background-color, e `getComputedStyle` no meio da animação devolve a
cor intermediária — medir cedo demais reprova a tela inteira sem defeito algum.
"""
import sqlite3

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

# "/?busca=casa 1" entra na lista porque o resultado da busca só existe com a
# busca ativa: os rótulos de grupo, a contagem e os selos do imóvel não estão
# na tela do painel vazio, e nenhuma outra rota os pintaria.
PAGINAS = ["/", "/?busca=casa+1", "/pacientes", "/casa/1", "/lixeira", "/banco", "/exportar"]

# Percorre as folhas de texto visíveis, resolve o fundo efetivo subindo pelos
# ancestrais e devolve só quem fica abaixo do mínimo AA (4,5:1, ou 3:1 para
# texto grande, conforme a norma).
MEDIR_CONTRASTE = r"""
() => {
  function lin(c){c/=255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4);}
  function lum(rgb){const m=rgb.match(/\d+(\.\d+)?/g).map(Number);
    return 0.2126*lin(m[0])+0.7152*lin(m[1])+0.0722*lin(m[2]);}
  function alfa(rgb){const m=rgb.match(/\d+(\.\d+)?/g).map(Number);
    return m.length>3?m[3]:1;}
  function fundo(el){
    let n=el;
    while(n && n!==document.documentElement){
      const bg=getComputedStyle(n).backgroundColor;
      if(bg && alfa(bg)>0.9) return bg;
      n=n.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor||'rgb(255,255,255)';
  }
  const ruins=[];
  document.querySelectorAll('body *').forEach(el=>{
    if(el.children.length>0) return;
    const txt=(el.textContent||'').trim();
    if(!txt) return;
    const r=el.getBoundingClientRect();
    if(r.width<1||r.height<1) return;
    const cs=getComputedStyle(el);
    if(cs.visibility==='hidden'||cs.display==='none'||+cs.opacity===0) return;
    const fg=cs.color, bg=fundo(el);
    const L1=lum(fg), L2=lum(bg);
    const razao=(Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    const px=parseFloat(cs.fontSize);
    const grande=px>=24||(px>=18.66&&+cs.fontWeight>=700);
    const minimo=grande?3:4.5;
    if(razao<minimo-0.05){
      ruins.push({txt:txt.slice(0,40),razao:+razao.toFixed(2),minimo,
                  px:+px.toFixed(1),fg,bg});
    }
  });
  return ruins;
}
"""


def _povoar():
    conn = sqlite3.connect(db.DATABASE)
    conn.execute(
        "INSERT INTO casas (id, numero_casa, endereco, tipo_imovel)"
        " VALUES (1, 1, 'Rua A, 1', 'domicilio')"
    )
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, nome, cpf, data_nascimento, telefone,"
        " nome_mae, observacao, condicoes_saude, status) VALUES (1, 1, 'MARIA JOSE',"
        " '31520170149', '1961-01-27', '6496091751', 'ALTIVA', 'obs de campo',"
        " 'hipertensao', 'ativo')"
    )
    # Casa repartida em famílias: o cabeçalho do núcleo, a contagem e o grupo
    # "sem família" são marcação que só existe aqui — sem repartir, nenhuma rota
    # da lista os pinta, e o contraste deles nunca seria medido.
    conn.execute(
        "INSERT INTO familias (id, casa_id, nome, criada_em)"
        " VALUES (1, 1, 'Frente', '2026-01-01T00:00:00'),"
        "        (2, 1, 'Fundos', '2026-01-01T00:00:01')"
    )
    conn.execute("UPDATE pacientes SET familia_id = 1 WHERE id = 1")
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, familia_id, nome, cpf, data_nascimento,"
        " status) VALUES (2, 1, 2, 'JOAO DO FUNDO', '70904240108', '1988-09-03', 'ativo')"
    )
    # Óbito: sai da tela da casa e deixa no lugar a linha que diz onde o
    # cadastro está. Sem um registro assim, essa linha não é pintada em rota
    # nenhuma e o contraste dela nunca seria medido.
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, familia_id, nome, data_nascimento, status)"
        " VALUES (3, 1, 1, 'AVO BENEDITA', '1931-05-12', 'obito')"
    )
    # Quem se mudou é o que pinta "Registros guardados" — sem um registro
    # guardado o bloco recolhível não existe na página e não seria medido.
    conn.execute(
        "INSERT INTO pacientes (id, casa_id, familia_id, nome, data_nascimento, status)"
        " VALUES (4, 1, 2, 'CARLOS QUE MUDOU', '1975-06-20', 'mudou_se')"
    )
    conn.commit()
    conn.close()


def test_contraste_wcag_aa_nos_dois_temas(pagina, servidor):
    _povoar()
    entrar(pagina, servidor)
    pagina.set_viewport_size({"width": 1600, "height": 950})

    falhas = []
    for tema in ("claro", "escuro"):
        for rota in PAGINAS:
            pagina.goto(f"{servidor}{rota}")
            pagina.wait_for_selector("#app-main")
            if tema == "escuro":
                pagina.evaluate(
                    "if(!document.documentElement.classList"
                    ".contains('theme-dark')){toggleTheme();}"
                )
                # As transições de cor precisam terminar antes da medida.
                pagina.wait_for_timeout(400)
            # Abre o bloco recolhido, se a tela tiver um.
            alternador = pagina.locator("[data-detalhes-todos]")
            if alternador.count():
                alternador.click()
            # <details> fechado não pinta o conteúdo, e o medidor pula o que não
            # pinta: sem abrir, só o rótulo entraria na conta.
            for recolhivel in pagina.locator("details:not([open]) > summary").all():
                recolhivel.click()
            # Diálogo fechado é `hidden`, e o medidor pula o que não pinta —
            # sem abrir, o modal nunca foi medido em tema nenhum. Só o gatilho
            # visível: em /casa/1 os botões moram num menu recolhido.
            gatilho = pagina.locator("[data-dialog-open]:visible").first
            if gatilho.count():
                gatilho.click()
                pagina.wait_for_selector(".filter-dialog.is-visible")
                pagina.wait_for_timeout(250)
            for ruim in pagina.evaluate(MEDIR_CONTRASTE):
                falhas.append(
                    f"[{tema}] {rota} {ruim['razao']}:1 (mín {ruim['minimo']}) "
                    f"{ruim['px']}px {ruim['fg']} sobre {ruim['bg']} "
                    f"— {ruim['txt']!r}"
                )

    assert not falhas, "texto abaixo do WCAG AA:\n" + "\n".join(falhas)
