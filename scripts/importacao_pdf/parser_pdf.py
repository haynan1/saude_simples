# -*- coding: utf-8 -*-
"""Extrai o caderno de campo (PDF) para JSON. Não toca no banco.

Estrutura do documento:

    QUADRA N° NN
      CASA-NN
        ENDEREÇO: ...
        CONTAGEM: <tipo do imóvel>
        NOME: <morador>
          CPF / CNS / DATA DE NASCIMENTO / TELEFONE / MÃE / PAI / saúde ...
          CONTAGEM: MASCULINO|FEMININO   <- sexo, encerra o morador

    ... depois da última casa, dois apêndices:
    LISTA DE CADA PESSOA QUE SE MUDOU DE SUA CASA
      NÚMERO DA CASA EM QUE MORAVA: NN   <- cabeçalho de grupo
        NOME: ...
    NOMES DOS FALESCIDOS
      NOME: ...

Armadilhas que o parser trata (cada uma corrompia dado antes de existir):

  - o timbre de 5 linhas se repete nas 181 páginas e precisa sair ANTES do
    parse, senão "Fone: (64) 9244-5685" vira um campo;
  - registros atravessam a quebra de página — as páginas viram um fluxo único;
  - valores quebram em várias linhas: linha sem rótulo é continuação;
  - "CONTAGEM:" é ambíguo — dentro de um morador é sexo, fora é tipo do imóvel;
  - rótulos vêm com erro de digitação ("DATA DE NACIMENTO", "NOME DA MÂE") e às
    vezes sem os dois-pontos ("CPF 051.886.521-53") ou sem separador nenhum
    ("DATA DE NASCIMENTO10/03/1993");
  - os apêndices vêm depois da última casa: sem reconhecê-los, 72 pessoas
    viram moradores ativos do Lar Vicentino.

Uso:
    python scripts/importacao_pdf/parser_pdf.py
    python scripts/importacao_pdf/parser_pdf.py --pdf caminho.pdf --saida extraido.json
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comum import PDF_PADRAO, SAIDA_PADRAO, chave, stdout_utf8  # noqa: E402

LETTERHEAD = (
    "av. cidade de goias, 1029",
    "sao luis de montes belos - go",
    "fone: (64) 9244-5685",
    "saude e bem-estar!",
)

# Rótulo canônico -> campo. Inclui os erros de digitação encontrados no PDF.
ROTULOS = {
    "nome": "nome",
    "cpf": "cpf",
    "cns": "cns",
    "cartao sus": "cns",
    "data de nascimento": "data_nascimento",
    "data de nacimento": "data_nascimento",
    "data de nascimemto": "data_nascimento",
    "data de nasicimento": "data_nascimento",
    "data de nascimeto": "data_nascimento",
    "telefone": "telefone",
    "celular": "telefone",
    "nome da mae": "nome_mae",
    "nomea da mae": "nome_mae",
    "mae": "nome_mae",
    "nome do pai": "nome_pai",
    "nome da pai": "nome_pai",
    "pai": "nome_pai",
    "endereco": "endereco",
    "contagem": "contagem",
    "estratificacao de risco": "estratificacao",
    "observacao de saude": "saude",
    "observacao": "saude",
    "obs": "saude",
    "doenca": "saude",
    "doencas": "saude",
    "medicamento de uso continuo": "medicamentos",
    "lista conferida de medicamentos": "medicamentos",
    "possui": "medicamentos",
    "peso": "peso",
    "altura": "altura",
    "cidade": "cidade",
    "local": "cidade",
    "cep": "cep",
    "apelido": "apelido",
    "escolaridade": "escolaridade",
    "numero da casa em que morava": "casa_anterior",
}

# Cabeçalhos dos apêndices. "FALESCIDOS" é como está escrito no caderno — a
# regex aceita as grafias próximas para não depender do erro se repetir.
RE_SECAO = [
    (re.compile(r"^LISTA DE CADA PESSOA QUE SE MUDOU", re.I), "mudou_se"),
    (re.compile(r"^NOMES? DOS? FAL[EA]S?CIDOS?", re.I), "obito"),
]
# Cabeçalho de grupo dentro do apêndice de mudanças: vale para os moradores
# listados abaixo dele, até vir o próximo.
RE_CASA_ANTERIOR = re.compile(r"^N[ÚU]MERO DA CASA EM QUE MORAVA\s*:?\s*(\d+)", re.I)

# Só "QUADRA N° NN" abre território. O índice da página 2 usa "QUADRA – NN" e
# não pode ser confundido com o corpo do documento.
RE_QUADRA = re.compile(r"^QUADRA\s*N[°º]\s*(\d+)\s*$", re.I)
# CASA-60, CASA - 60, CASA–60, CASA-19.5, CASA-262.5 (CASA DO FUNDO)
RE_CASA = re.compile(r"^CASA\s*[-–—]?\s*(\d+)(?:\.(\d+))?\s*(\(.*\))?\s*$", re.I)
RE_ROTULO = re.compile(r"^([^:]{2,45}?)\s*:\s*(.*)$")

# Lista curta e explícita de propósito: rótulo genérico demais casaria com o
# texto livre das observações de saúde.
RE_SEM_SEPARADOR = re.compile(
    r"^(NOME DA M[ÃÂA]E|NOME DO PAI|NOME DA PAI"
    r"|DATA DE (?:NASCIMENTO|NACIMENTO|NASCIMEMTO|NASICIMENTO|NASCIMETO)"
    r"|CART[ÃA]O SUS|ENDERE[ÇC]O|TELEFONE|CELULAR|CONTAGEM|NOME"
    r"|CPF|CNS|M[ÃÂA]E|PAI)"
    r"\s*[:\-]?\s*(.+)$",
    re.I,
)

# Campos de forma fixa: data/CPF/telefone nunca continuam na linha seguinte.
CAMPOS_ESTRUTURADOS = ("cpf", "cns", "data_nascimento", "telefone")

# Guarda contra rótulo repetido por engano: o caderno tem "DATA DE NASCIMENTO:
# 26/07/1972" seguido de "DATA DE NASCIMENTO: HIPERTENSO, DIABETICO;" — a
# segunda linha é observação de saúde no rótulo errado e não pode sobrescrever
# a data boa.
FORMA = {
    "data_nascimento": re.compile(r"^\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}$"),
    "cpf": re.compile(r"^\D*(?:\d\D*){11}$"),
    "cns": re.compile(r"^\D*(?:\d\D*){15}$"),
    "telefone": re.compile(r"^\D*(?:\d\D*){10,11}$"),
}


def forma_ok(campo, valor):
    regra = FORMA.get(campo)
    return bool(regra.match(valor.strip())) if regra else True


def paginas_do_pdf(caminho):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit(
            "pypdf não instalado. Rode:\n"
            "    pip install -r scripts/importacao_pdf/requirements.txt"
        )
    if not os.path.exists(caminho):
        raise SystemExit("PDF não encontrado: %s" % caminho)
    return [p.extract_text() or "" for p in PdfReader(caminho).pages]


def linhas_uteis(paginas):
    """Remove o timbre e devolve um fluxo único de linhas (página, texto)."""
    fluxo = []
    for numero, texto in enumerate(paginas, start=1):
        for bruta in texto.splitlines():
            linha = bruta.strip()
            if not linha:
                continue
            if any(chave(linha).startswith(h) for h in LETTERHEAD):
                continue
            fluxo.append((numero, linha))
    return fluxo


def parse(fluxo):
    casas = []
    casa = None
    paciente = None
    campo_atual = None  # (dono, nome_do_campo) para continuação de linha
    quadra = None
    avisos = []
    inicio_territorio = False
    secao = None          # None = território; "mudou_se"/"obito" = apêndice
    casa_anterior = None  # último "NÚMERO DA CASA EM QUE MORAVA"
    apendice = {"mudou_se": [], "obito": []}

    for pagina, linha in fluxo:
        marcador = next((nome for regra, nome in RE_SECAO if regra.match(linha)), None)
        if marcador:
            secao = marcador
            casa_anterior = None
            paciente = None
            campo_atual = None
            avisos.append((pagina, "início de apêndice", linha))
            continue

        if secao == "mudou_se":
            m = RE_CASA_ANTERIOR.match(linha)
            if m:
                casa_anterior = int(m.group(1))
                paciente = None
                campo_atual = None
                continue

        m = RE_QUADRA.match(linha)
        if m:
            quadra = int(m.group(1))
            inicio_territorio = True
            paciente = None
            campo_atual = None
            continue

        if not inicio_territorio:
            continue  # índice / mensagens prontas / legenda

        m = RE_CASA.match(linha)
        if m:
            casa = {
                "quadra": quadra,
                "numero": int(m.group(1)),
                "sufixo": m.group(2),
                "rotulo": linha,
                "pagina": pagina,
                "endereco": "",
                "contagem": "",
                "extras": {},
                "pacientes": [],
            }
            casas.append(casa)
            paciente = None
            campo_atual = None
            continue

        m = RE_ROTULO.match(linha)
        campo = ROTULOS.get(chave(m.group(1))) if m else None
        if campo is None:
            m2 = RE_SEM_SEPARADOR.match(linha)
            if m2:
                campo = ROTULOS.get(chave(m2.group(1)))
                if campo:
                    m = m2
                    avisos.append((pagina, "rótulo sem ':'", linha))

        if m and campo:
            valor = m.group(2).strip()

            if campo == "estratificacao":
                campo_atual = None
                continue  # sempre vazio no documento inteiro

            if campo == "nome":
                # "NOME: MÃE: ERNESTINA TEODORO DE JESUS" — o operador digitou
                # NOME onde queria NOME DA MÃE. Sem isto, a mãe vira um morador
                # fantasma com a saúde do filho pendurada nela.
                interno = RE_ROTULO.match(valor)
                campo_interno = ROTULOS.get(chave(interno.group(1))) if interno else None
                if campo_interno and campo_interno != "nome" and paciente is not None:
                    avisos.append((pagina, "NOME com rótulo dentro", linha))
                    paciente[campo_interno] = interno.group(2).strip()
                    campo_atual = (paciente, campo_interno)
                    continue

                if secao:
                    # Apêndice: a pessoa não mora na casa corrente.
                    paciente = {"nome": valor, "pagina": pagina, "extras": {},
                                "situacao": secao, "casa_anterior": casa_anterior}
                    apendice[secao].append(paciente)
                    campo_atual = (paciente, "nome")
                    continue

                if casa is None:
                    avisos.append((pagina, "morador sem casa", linha))
                    continue
                paciente = {"nome": valor, "pagina": pagina, "extras": {},
                            "situacao": "ativo"}
                casa["pacientes"].append(paciente)
                campo_atual = (paciente, "nome")
                continue

            if campo == "contagem":
                # Dentro de um morador -> sexo. Fora -> tipo do imóvel.
                if paciente is not None and chave(valor) in ("masculino", "feminino"):
                    paciente["sexo"] = "Masculino" if chave(valor) == "masculino" else "Feminino"
                    paciente = None
                    campo_atual = None
                elif casa is not None:
                    casa["contagem"] = valor
                    campo_atual = (casa, "contagem")
                continue

            dono = paciente if paciente is not None else casa
            if dono is None:
                avisos.append((pagina, "campo sem dono", linha))
                continue

            if campo == "endereco":
                # ENDEREÇO só existe no nível da casa; se apareceu dentro de um
                # morador, o morador anterior terminou sem CONTAGEM.
                paciente = None
                dono = casa

            if campo in CAMPOS_ESTRUTURADOS:
                if dono.get(campo) and forma_ok(campo, dono[campo]) and not forma_ok(campo, valor):
                    avisos.append((pagina, "rótulo trocado", linha))
                    dono["notas"] = (dono.get("notas", "") + " " + valor).strip()
                else:
                    dono[campo] = valor
                # Texto solto depois de um campo estruturado é nota, não
                # continuação do valor.
                campo_atual = (dono, "notas")
            elif campo in ("nome_mae", "nome_pai", "endereco"):
                dono[campo] = valor
                campo_atual = (dono, campo)
            elif campo in ("saude", "medicamentos"):
                anterior = dono.get(campo, "")
                dono[campo] = (anterior + " " + valor).strip() if anterior else valor
                campo_atual = (dono, campo)
            else:
                dono["extras"][campo] = valor
                campo_atual = (dono["extras"], campo)
            continue

        # Linha sem rótulo: continuação do último campo.
        if campo_atual:
            dono, nome_campo = campo_atual
            dono[nome_campo] = (dono.get(nome_campo, "") + " " + linha).strip()
        elif casa is not None:
            avisos.append((pagina, "linha solta", linha))

    return casas, apendice, avisos


def extrair(caminho_pdf):
    casas, apendice, avisos = parse(linhas_uteis(paginas_do_pdf(caminho_pdf)))
    return {"casas": casas, "apendice": apendice, "avisos": avisos}


def main():
    stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", default=PDF_PADRAO, help="caderno em PDF")
    ap.add_argument("--saida", default=os.path.join(SAIDA_PADRAO, "extraido.json"),
                    help="JSON de saída (contém dado de paciente — mantenha fora do git)")
    args = ap.parse_args()

    dados = extrair(args.pdf)
    os.makedirs(os.path.dirname(os.path.abspath(args.saida)), exist_ok=True)
    with open(args.saida, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=1)

    casas, apendice = dados["casas"], dados["apendice"]
    quadras = sorted({c["quadra"] for c in casas})
    print("quadras ................. %d %s" % (len(quadras), quadras))
    print("casas ................... %d" % len(casas))
    print("moradores no território . %d" % sum(len(c["pacientes"]) for c in casas))
    print("apêndice — se mudaram ... %d" % len(apendice["mudou_se"]))
    print("apêndice — falecidos .... %d" % len(apendice["obito"]))
    sem_casa = [p["nome"] for p in apendice["mudou_se"] if not p["casa_anterior"]]
    if sem_casa:
        print("  ATENÇÃO: %d sem casa anterior indicada: %s" % (len(sem_casa), sem_casa[:4]))
    print("avisos .................. %d" % len(dados["avisos"]))
    print("\nsaída: %s" % args.saida)


if __name__ == "__main__":
    main()
