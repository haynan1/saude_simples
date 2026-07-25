# -*- coding: utf-8 -*-
"""Aplica os dois apêndices do caderno: quem se mudou e quem faleceu.

Estas pessoas aparecem DEPOIS da última casa no documento, e não moram nela.
São gravadas com a situação certa, usando os status que o app já tem:

  - quem se mudou -> status 'mudou_se', vinculado à casa em que MORAVA (o
    caderno informa o número). Aparece na seção "Registros guardados" daquela
    casa: fora das contagens do território, cadastro preservado.
  - quem faleceu  -> status 'obito', SEM casa. O caderno não registra onde
    moravam, e chutar o endereço de um falecido não é aceitável.

Funciona nos dois cenários e é idempotente:
  - pessoa ainda não cadastrada -> insere já com a situação correta;
  - pessoa cadastrada na casa errada (carga feita antes de o parser reconhecer
    os apêndices, quando as 72 viravam moradores do Lar Vicentino) -> corrige
    situação e vínculo.

Uso:
    python scripts/importacao_pdf/aplicar_apendices.py            # simulação
    python scripts/importacao_pdf/aplicar_apendices.py --gravar   # efetiva
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comum import (  # noqa: E402
    BANCO,
    SAIDA_PADRAO,
    backup,
    conectar,
    confirmar_gravacao,
    data_iso,
    digitos,
    encontrar_paciente,
    formatar_cpf_ou_cns,
    formatar_telefone,
    indexar_pacientes,
    nome_e_nota,
    stdout_utf8,
)
from aplicar_merge import MARCA_FUNDO_BUSCA, observacao_de  # noqa: E402

# Cadastro fantasma criado pela carga anterior a partir do próprio cabeçalho
# "NOMES DOS FALESCIDOS" — o rótulo "NOME" casa com o começo da palavra.
FANTASMAS = ("S DOS FALESCIDOS",)


def indexar_casas_por_numero(conn):
    """numero_casa -> id. As casas do fundo repetem o número da casa da frente;
    quem se mudou morava na casa da frente, então ela tem preferência."""
    indice = {}
    for r in conn.execute("SELECT id, numero_casa, endereco FROM casas ORDER BY id"):
        fundo = MARCA_FUNDO_BUSCA in (r["endereco"] or "").upper()
        atual = indice.get(r["numero_casa"])
        if atual is None or (atual["fundo"] and not fundo):
            indice[r["numero_casa"]] = {"id": r["id"], "fundo": fundo}
    return indice


def aplicar(conn, dados):
    apendice = dados.get("apendice", {"mudou_se": [], "obito": []})
    casas_por_numero = indexar_casas_por_numero(conn)
    _, por_documento, por_nome = indexar_pacientes(conn)

    rel = {"mudou_se": [], "obito": [], "inseridos": 0, "corrigidos": 0,
           "sem_casa_antiga": [], "fantasmas": []}

    def gravar(pessoa, status, casa_id):
        nome, nota_nome = nome_e_nota(pessoa["nome"])
        if not nome:
            return None
        _, atual = encontrar_paciente(pessoa, por_documento, por_nome)
        if atual is not None:
            conn.execute("UPDATE pacientes SET status = ?, casa_id = ? WHERE id = ?",
                         (status, casa_id, atual["id"]))
            rel["corrigidos"] += 1
            return nome

        documento = digitos(pessoa.get("cpf", "")) or digitos(pessoa.get("cns", ""))
        observacao = ". ".join(p for p in (observacao_de(pessoa), nota_nome) if p)
        conn.execute(
            "INSERT INTO pacientes (casa_id, nome, cpf, telefone, data_nascimento,"
            " sexo, nome_pai, nome_mae, condicoes_saude, observacao, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)",
            (casa_id, nome,
             formatar_cpf_ou_cns(documento) if documento else "",
             formatar_telefone(pessoa["telefone"]) if pessoa.get("telefone") else "",
             data_iso(pessoa.get("data_nascimento", "")),
             pessoa.get("sexo", ""),
             pessoa.get("nome_pai", "").strip(),
             pessoa.get("nome_mae", "").strip(),
             observacao, status),
        )
        rel["inseridos"] += 1
        return nome

    for pessoa in apendice["mudou_se"]:
        destino = casas_por_numero.get(pessoa.get("casa_anterior"))
        if destino is None:
            rel["sem_casa_antiga"].append((pessoa["nome"], pessoa.get("casa_anterior")))
        nome = gravar(pessoa, "mudou_se", destino["id"] if destino else None)
        if nome:
            rel["mudou_se"].append((nome, pessoa.get("casa_anterior")))

    for pessoa in apendice["obito"]:
        # Sem casa de propósito: o caderno não diz onde moravam.
        nome = gravar(pessoa, "obito", None)
        if nome:
            rel["obito"].append(nome)

    for fantasma in FANTASMAS:
        for linha in conn.execute("SELECT id, nome FROM pacientes WHERE nome = ?", (fantasma,)):
            conn.execute("DELETE FROM pacientes WHERE id = ?", (linha["id"],))
            rel["fantasmas"].append(dict(linha))

    return rel


def imprimir(rel, conn):
    print("se mudaram .......... %d (vinculados à casa em que moravam)" % len(rel["mudou_se"]))
    print("falecidos ........... %d (status óbito, sem casa)" % len(rel["obito"]))
    print("  inseridos ......... %d" % rel["inseridos"])
    print("  já existiam ....... %d (situação e vínculo corrigidos)" % rel["corrigidos"])
    print("casa antiga inexistente: %d %s" % (len(rel["sem_casa_antiga"]),
                                              rel["sem_casa_antiga"][:5]))
    print("fantasmas removidos .. %s" % (rel["fantasmas"] or "nenhum"))
    print()
    print("falecidos:")
    for nome in rel["obito"]:
        print("   %s" % nome)
    print()
    for r in conn.execute("SELECT COALESCE(status,'ativo') s, COUNT(*) n "
                          "FROM pacientes GROUP BY 1 ORDER BY n DESC"):
        print("   %-14s %d" % (r["s"], r["n"]))
    print("   casas com registro guardado: %d" % conn.execute(
        "SELECT COUNT(DISTINCT casa_id) FROM pacientes WHERE status = 'mudou_se'"
    ).fetchone()[0])


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
        backup("antes_aplicar_apendices", args.banco)

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
