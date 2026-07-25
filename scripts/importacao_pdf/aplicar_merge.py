# -*- coding: utf-8 -*-
"""Casa a extração do caderno com o banco. Simulação por padrão.

Política decidida por James (2026-07-24), a manter em qualquer nova carga:

  1. MERGE NÃO DESTRUTIVO. Morador que já existe só recebe dado em campo VAZIO.
     Nada preenchido é sobrescrito — correção feita à mão depois da importação
     do e-SUS vale mais que o documento.
  2. CASA SEM ENDEREÇO NÃO É CRIADA. As casas 171-180 são só marcador no
     caderno; inventar endereço para satisfazer a validação do app seria
     inventar dado.
  3. CONDIÇÃO DE SAÚDE SÓ EM TERMO INEQUÍVOCO, e só a partir da observação de
     saúde escrita pelo agente — nunca do nome do medicamento. Qualquer marca
     de dúvida no texto cancela a marcação inteira daquele morador.

O texto original do agente vai SEMPRE inteiro para `observacao`, mesmo quando
vira checkbox: assim nenhuma marcação depende da interpretação da máquina.

Uso:
    python scripts/importacao_pdf/aplicar_merge.py                # simulação
    python scripts/importacao_pdf/aplicar_merge.py --gravar       # efetiva
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comum import (  # noqa: E402
    BANCO,
    SAIDA_PADRAO,
    backup,
    conectar,
    confirmar_gravacao,
    cpf_valido,
    data_iso,
    digitos,
    encontrar_paciente,
    formatar_cpf_ou_cns,
    formatar_telefone,
    indexar_pacientes,
    nome_e_nota,
    norm,
    stdout_utf8,
)

# Só marcador no caderno: sem endereço, sem contagem, sem morador.
CASAS_SO_MARCADOR = set(range(171, 181))

# CONTAGEM da casa -> (tipo_imovel do app, nota preservada no endereço).
# A nota existe porque `casas` não tem campo de observação e "cadastro não
# realizado" é fila de trabalho do agente — perder isso é perder o próximo passo.
TIPO_POR_CONTAGEM = [
    ("CASA CADASTRADA", "domicilio", ""),
    ("CADASTRO NAO REALIZADO", "domicilio", "CADASTRO NÃO REALIZADO"),
    ("PONTO DE COMERCIO", "loja", ""),
    ("LOTE VAZIO", "terreno_baldio", ""),
    ("ABANDONADO", "domicilio", "ABANDONADO"),
    ("LAR VICENTINO", "domicilio", "LAR VICENTINO"),
    ("ESCOLA", "escola", ""),
    ("IGREJA", "igreja", ""),
]

# O que se ESCREVE no endereço de uma casa do fundo.
MARCA_FUNDO = "(CASA DO FUNDO)"
# O que se PROCURA para reconhecê-la. Sem os parênteses de propósito: uma carga
# antiga gravou "(CASA DO FUNDO — CASA-234.5)", e exigir a forma exata fazia o
# script não reconhecer a casa e inserir uma duplicata a cada reexecução.
MARCA_FUNDO_BUSCA = "CASA DO FUNDO"

# Dúvida do agente não vira diagnóstico.
INCERTEZA = ("CONFIRMAR SE", "SINTOMAS DE", "APARENTEMENTE", "SUSPEITA", "PRE-DIABET")

TERMOS = [
    ("hipertensao", ("HIPERTENS", "HIPER TENS", "HIPETENS", "HIPERTESO",
                     "HIPTER TENS", "PRESSAO ALTA")),
    ("diabetes", ("DIABET",)),
    ("gestante", ("GESTANTE",)),
    ("fumante", ("FUMANTE", "FUMA ", "TABAGIS")),
    ("alcool", ("ALCOOL", "ALCOLATRA", "ETILIS")),
    ("asma", ("ASMA",)),
    ("dpoc_enfisema", ("ENFISEMA", "DPOC")),
    ("acima_peso", ("ACIMA DO PESO", "SOBREPESO", "OBESO", "OBESA", "OBESIDADE")),
    ("abaixo_peso", ("ABAIXO DO PESO",)),
    ("avc_derrame", ("AVC", "DERRAME")),
    ("infarto", ("INFARTO",)),
    ("doenca_cardiaca", ("CARDIAC", "CORACAO", "ARRITMIA")),
    ("problemas_rins", ("NOS RINS", "PROBLEMA DE RINS", "PROBLEMA NOS RINS")),
    ("doenca_respiratoria", ("PULMAO", "PULMAR", "RESPIRATORI")),
    ("tuberculose", ("TUBERCULOSE",)),
    ("hanseniase", ("HANSENIASE",)),
    ("cancer", ("CANCER",)),
    ("saude_mental", ("DEPRESSAO", "ANSIEDADE", "SAUDE MENTAL", "ESQUIZOFREN", "BIPOLAR")),
    ("acamado", ("ACAMAD",)),
    ("deficiencia", ("CADEIRANTE", "DEFICIENC", "DEFICIENTE")),
]

PREENCHIVEIS = ("cpf", "telefone", "data_nascimento", "sexo", "nome_pai",
                "nome_mae", "condicoes_saude", "observacao")


def tipo_e_nota(contagem):
    alvo = norm(contagem)
    for marcador, tipo, nota in TIPO_POR_CONTAGEM:
        if alvo.startswith(marcador):
            resto = contagem[len(marcador):].strip(" -–—.,")
            return tipo, " — ".join(p for p in (nota, resto) if p)
    return "domicilio", contagem.strip()


def condicoes(texto):
    """Marca condições só quando o termo é inequívoco.

    A quebra de linha do PDF separa "PRÉ-" de "DIABETES"; sem colar o hífen de
    volta, "PRÉ- DIABETES" passaria batido e viraria diabetes."""
    alvo = re.sub(r"-\s+", "-", norm(texto))
    if not alvo:
        return "", False
    if any(marca in alvo for marca in INCERTEZA):
        return "", True
    achados = []
    for codigo, termos in TERMOS:
        if any(t in alvo for t in termos) and codigo not in achados:
            achados.append(codigo)
    return "\n".join(achados), False


def observacao_de(pessoa):
    """Tudo que o app não tem coluna para guardar entra aqui, rotulado.
    Nenhuma informação do caderno é descartada."""
    partes = []
    if pessoa.get("saude"):
        partes.append(pessoa["saude"].strip(" ;."))
    if pessoa.get("medicamentos"):
        partes.append("Medicamento de uso contínuo: " + pessoa["medicamentos"].strip(" ;."))
    extras = pessoa.get("extras", {})
    medidas = [v for v in (extras.get("peso"), extras.get("altura")) if v]
    if medidas:
        partes.append("Peso/altura: " + " / ".join(medidas))
    for chave_extra, rotulo in (("cidade", "Naturalidade"), ("apelido", "Apelido"),
                                ("escolaridade", "Escolaridade"),
                                ("casa_anterior", "Número da casa em que morava")):
        if extras.get(chave_extra):
            partes.append("%s: %s" % (rotulo, extras[chave_extra]))
    if pessoa.get("notas"):
        partes.append(pessoa["notas"].strip())
    # CNS só entra na observação quando o CPF já ocupou a coluna do documento.
    if pessoa.get("cns") and pessoa.get("cpf"):
        partes.append("CNS: " + pessoa["cns"].strip())
    return ". ".join(p for p in partes if p)


def endereco_da_casa(casa, existentes):
    tipo, nota = tipo_e_nota(casa["contagem"])
    endereco = casa["endereco"].strip()
    if casa["sufixo"]:
        # A casa do fundo raramente tem endereço próprio no caderno: herda o da
        # casa da frente, senão fica um cadastro com moradores e sem local.
        if not endereco:
            base = existentes.get((casa["quadra"], casa["numero"]))
            endereco = re.sub(r"\s*\[[^\]]*\]\s*$", "", (base or {}).get("endereco", "")).strip()
        endereco = (endereco + " " if endereco else "") + MARCA_FUNDO
    if nota:
        endereco = (endereco + " " if endereco else "") + "[%s]" % nota
    return tipo, endereco.strip() or "(sem endereço no documento)"


def aplicar(conn, dados):
    rel = {
        "quadras_novas": [], "casas_novas": 0, "casas_existentes": 0,
        "casas_endereco_preenchido": [], "casas_tipo_ajustado": [],
        "pac_novos": 0, "pac_vinculados": 0, "campos_preenchidos": {},
        "pac_ja_tinha_outra_casa": [], "pac_duplicado_no_caderno": [],
        "cond_marcadas": [], "cond_canceladas_por_duvida": [],
        "cpf_invalido": [], "data_ilegivel": [],
        "casas_ignoradas": sorted(CASAS_SO_MARCADOR),
    }

    # ---- quadras ----
    quadras = {r["numero_quadra"]: r["id"] for r in conn.execute("SELECT * FROM quadras")}
    for numero in sorted({c["quadra"] for c in dados["casas"]}):
        if numero not in quadras:
            quadras[numero] = conn.execute(
                "INSERT INTO quadras (numero_quadra) VALUES (?)", (numero,)
            ).lastrowid
            rel["quadras_novas"].append(numero)

    # ---- casas ----
    # Casa do fundo tem o mesmo número da casa da frente; a marca no endereço é
    # o que as distingue. Sem indexar as duas separadamente, reexecutar o script
    # duplicaria as casas do fundo a cada rodada.
    existentes, fundos = {}, {}
    for r in conn.execute(
        "SELECT ca.id, ca.numero_casa, ca.endereco, ca.tipo_imovel, q.numero_quadra "
        "FROM casas ca LEFT JOIN quadras q ON q.id = ca.quadra_id"
    ):
        alvo = fundos if MARCA_FUNDO_BUSCA in (r["endereco"] or "").upper() else existentes
        alvo.setdefault((r["numero_quadra"], r["numero_casa"]), dict(r))

    mapa_casa = {}
    for casa in dados["casas"]:
        if casa["numero"] in CASAS_SO_MARCADOR and not casa["sufixo"]:
            continue

        tipo, endereco = endereco_da_casa(casa, existentes)
        chave_casa = (casa["quadra"], casa["numero"])
        indice = fundos if casa["sufixo"] else existentes
        alvo = indice.get(chave_casa)

        if alvo:
            rel["casas_existentes"] += 1
            casa_id = alvo["id"]
            if not (alvo["endereco"] or "").strip():
                conn.execute("UPDATE casas SET endereco = ? WHERE id = ?", (endereco, casa_id))
                rel["casas_endereco_preenchido"].append(casa["rotulo"])
            # Só especializa o tipo quando o banco está no padrão 'domicilio' —
            # nunca desfaz uma escolha feita à mão.
            if tipo != "domicilio" and (alvo["tipo_imovel"] or "domicilio") == "domicilio":
                conn.execute("UPDATE casas SET tipo_imovel = ? WHERE id = ?", (tipo, casa_id))
                rel["casas_tipo_ajustado"].append((casa["rotulo"], tipo))
        else:
            casa_id = conn.execute(
                "INSERT INTO casas (quadra_id, numero_casa, endereco, tipo_imovel) "
                "VALUES (?, ?, ?, ?)",
                (quadras[casa["quadra"]], casa["numero"], endereco, tipo),
            ).lastrowid
            rel["casas_novas"] += 1
            indice[chave_casa] = {"id": casa_id, "endereco": endereco, "tipo_imovel": tipo}

        mapa_casa[id(casa)] = casa_id

    # ---- moradores ----
    _, por_documento, por_nome = indexar_pacientes(conn)
    vistos = set()

    for casa in dados["casas"]:
        casa_id = mapa_casa.get(id(casa))
        if casa_id is None:
            continue
        for pessoa in casa["pacientes"]:
            nome, nota_nome = nome_e_nota(pessoa["nome"])
            if not nome:
                continue

            nascimento = data_iso(pessoa.get("data_nascimento", ""))
            if pessoa.get("data_nascimento") and not nascimento:
                rel["data_ilegivel"].append((casa["rotulo"], nome, pessoa["data_nascimento"]))
            if pessoa.get("cpf") and not cpf_valido(pessoa["cpf"]):
                rel["cpf_invalido"].append((casa["rotulo"], nome, pessoa["cpf"]))

            marcadas, teve_duvida = condicoes(pessoa.get("saude", ""))
            if marcadas:
                rel["cond_marcadas"].append((nome, pessoa.get("saude", "")[:70],
                                             marcadas.split("\n")))
            if teve_duvida:
                rel["cond_canceladas_por_duvida"].append((nome, pessoa.get("saude", "")[:70]))

            observacao = ". ".join(p for p in (observacao_de(pessoa), nota_nome) if p)
            documento = digitos(pessoa.get("cpf", "")) or digitos(pessoa.get("cns", ""))
            novo = {
                "nome": nome,
                "cpf": formatar_cpf_ou_cns(documento) if documento else "",
                "telefone": formatar_telefone(pessoa["telefone"]) if pessoa.get("telefone") else "",
                "data_nascimento": nascimento,
                "sexo": pessoa.get("sexo", ""),
                "nome_pai": pessoa.get("nome_pai", "").strip(),
                "nome_mae": pessoa.get("nome_mae", "").strip(),
                "condicoes_saude": marcadas,
                "observacao": observacao,
            }

            chave_dup = documento if len(documento) >= 11 else (norm(nome), nascimento)
            if chave_dup in vistos:
                rel["pac_duplicado_no_caderno"].append((casa["rotulo"], nome))
                continue
            vistos.add(chave_dup)

            _, atual = encontrar_paciente(pessoa, por_documento, por_nome)

            if atual is None:
                conn.execute(
                    "INSERT INTO pacientes (casa_id, nome, cpf, telefone, data_nascimento,"
                    " sexo, nome_pai, nome_mae, condicoes_saude, observacao)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (casa_id, novo["nome"], novo["cpf"], novo["telefone"],
                     novo["data_nascimento"], novo["sexo"], novo["nome_pai"],
                     novo["nome_mae"], novo["condicoes_saude"], novo["observacao"]),
                )
                rel["pac_novos"] += 1
                continue

            # Já existe: vincula a casa e preenche só o que está vazio.
            mudancas, valores = [], []
            if not atual["casa_id"]:
                mudancas.append("casa_id = ?")
                valores.append(casa_id)
                rel["pac_vinculados"] += 1
            elif atual["casa_id"] != casa_id:
                rel["pac_ja_tinha_outra_casa"].append((nome, casa["rotulo"]))

            for campo in PREENCHIVEIS:
                if novo[campo] and not str(atual[campo] or "").strip():
                    mudancas.append("%s = ?" % campo)
                    valores.append(novo[campo])
                    rel["campos_preenchidos"][campo] = rel["campos_preenchidos"].get(campo, 0) + 1

            if mudancas:
                conn.execute("UPDATE pacientes SET %s WHERE id = ?" % ", ".join(mudancas),
                             valores + [atual["id"]])

    return rel


def imprimir(rel, conn):
    print("quadras criadas ............ %s" % (rel["quadras_novas"] or "nenhuma"))
    print("casas novas ................ %d" % rel["casas_novas"])
    print("casas já existentes ........ %d" % rel["casas_existentes"])
    print("  endereço preenchido ...... %d" % len(rel["casas_endereco_preenchido"]))
    print("  tipo especializado ....... %d %s" % (len(rel["casas_tipo_ajustado"]),
                                                  rel["casas_tipo_ajustado"][:6]))
    print("casas ignoradas (só marcador) %d" % len(rel["casas_ignoradas"]))
    print()
    print("moradores novos ............ %d" % rel["pac_novos"])
    print("moradores vinculados à casa  %d" % rel["pac_vinculados"])
    print("campos preenchidos ......... %d  %s"
          % (sum(rel["campos_preenchidos"].values()), rel["campos_preenchidos"]))
    print("duplicados no caderno ...... %d %s" % (len(rel["pac_duplicado_no_caderno"]),
                                                  rel["pac_duplicado_no_caderno"]))
    print("já tinham OUTRA casa ....... %d %s" % (len(rel["pac_ja_tinha_outra_casa"]),
                                                  rel["pac_ja_tinha_outra_casa"][:5]))
    print()
    print("condições marcadas ......... %d moradores" % len(rel["cond_marcadas"]))
    print("canceladas por dúvida ...... %d" % len(rel["cond_canceladas_por_duvida"]))
    for nome, texto in rel["cond_canceladas_por_duvida"]:
        print("   %-38s %s" % (nome[:38], texto))
    print("CPF com dígito inválido .... %d %s" % (len(rel["cpf_invalido"]), rel["cpf_invalido"]))
    print("data ilegível .............. %d %s" % (len(rel["data_ilegivel"]), rel["data_ilegivel"]))
    print()
    totais = {t: conn.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
              for t in ("quadras", "casas", "pacientes")}
    print("TOTAIS NO BANCO -> %s" % totais)


def main():
    stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracao", default=os.path.join(SAIDA_PADRAO, "extraido.json"))
    ap.add_argument("--banco", default=BANCO)
    ap.add_argument("--gravar", action="store_true", help="efetiva (sem isto, simula)")
    args = ap.parse_args()

    if not os.path.exists(args.extracao):
        raise SystemExit("Extração não encontrada: %s — rode parser_pdf.py antes."
                         % args.extracao)

    dados = json.load(open(args.extracao, encoding="utf-8"))
    if args.gravar:
        backup("antes_importar_pdf_residencias", args.banco)

    conn = conectar(args.banco)
    try:
        rel = aplicar(conn, dados)
        confirmar_gravacao(conn, args.gravar)
        print()
        imprimir(rel, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
