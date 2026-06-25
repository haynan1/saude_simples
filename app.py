import logging
import os
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from functools import wraps
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_wtf import CSRFProtect
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.security import check_password_hash, generate_password_hash

from db import (
    BASE_DIR,
    DATABASE,
    MIN_PASSWORD_LENGTH,
    criar_backup,
    garantir_senha_inicial,
    get_db_connection,
    get_senha_hash,
    init_db,
    set_senha_hash,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("saude_simples")

app = Flask(__name__)

SECRET_KEY = os.environ.get("SAUDE_SIMPLES_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SAUDE_SIMPLES_SECRET_KEY não definida. Crie um arquivo .env (veja .env.example) "
        "ou gere uma com `python -c \"import secrets; print(secrets.token_hex(32))\"`."
    )
app.secret_key = SECRET_KEY

BOOTSTRAP_PASSWORD_HASH = os.environ.get("SAUDE_SIMPLES_PASSWORD_HASH")

csrf = CSRFProtect(app)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW_SECONDS = 60
_login_attempts = {}


def registrar_falha_login(client_ip):
    now = time.monotonic()
    attempts = [t for t in _login_attempts.get(client_ip, []) if now - t < LOGIN_ATTEMPT_WINDOW_SECONDS]
    attempts.append(now)
    _login_attempts[client_ip] = attempts


def login_bloqueado(client_ip):
    now = time.monotonic()
    attempts = [t for t in _login_attempts.get(client_ip, []) if now - t < LOGIN_ATTEMPT_WINDOW_SECONDS]
    _login_attempts[client_ip] = attempts
    return len(attempts) >= LOGIN_ATTEMPT_LIMIT


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("usuario_autenticado"):
            return redirect(url_for("login", next=request.full_path if request.query_string else request.path))
        return view(*args, **kwargs)

    return wrapped


def proxima_url_segura(value):
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("index")


def requisicao_e_local():
    # request.remote_addr é o IP de quem conectou direto no socket — não vem de
    # cabeçalho (X-Forwarded-For), então não é falsificável pelo cliente.
    # ATENÇÃO: se este app for colocado detrás de um reverse proxy (nginx, etc.)
    # na mesma máquina, o proxy passa a ser "quem conectou", e todo mundo do lado
    # de fora passaria a aparecer como local. Nesse cenário, configure
    # werkzeug.middleware.proxy_fix.ProxyFix ou desative esta rota.
    return request.remote_addr in ("127.0.0.1", "::1")

CONDICOES_SAUDE_OPCOES = [
    {"codigo": "gestante", "label": "Está gestante"},
    {"codigo": "abaixo_peso", "label": "Abaixo do peso"},
    {"codigo": "peso_adequado", "label": "Peso adequado"},
    {"codigo": "acima_peso", "label": "Acima do peso"},
    {"codigo": "fumante", "label": "Está fumante"},
    {"codigo": "alcool", "label": "Faz uso de álcool"},
    {"codigo": "outras_drogas", "label": "Faz uso de outras drogas"},
    {"codigo": "hipertensao", "label": "Tem hipertensão arterial"},
    {"codigo": "diabetes", "label": "Tem diabetes"},
    {"codigo": "avc_derrame", "label": "Teve AVC/derrame"},
    {"codigo": "infarto", "label": "Teve infarto"},
    {"codigo": "doenca_cardiaca", "label": "Tem doença cardíaca/do coração"},
    {"codigo": "problemas_rins", "label": "Tem ou teve problemas nos rins"},
    {"codigo": "doenca_respiratoria", "label": "Tem doença respiratória/no pulmão"},
    {"codigo": "asma", "label": "Asma"},
    {"codigo": "dpoc_enfisema", "label": "DPOC/Enfisema"},
    {"codigo": "hanseniase", "label": "Hanseníase"},
    {"codigo": "tuberculose", "label": "Tuberculose"},
    {"codigo": "cancer", "label": "Tem ou teve câncer"},
    {"codigo": "internacao_12_meses", "label": "Teve internação nos últimos 12 meses"},
    {"codigo": "saude_mental", "label": "Diagnóstico de problema de saúde mental"},
    {"codigo": "acamado", "label": "Está acamado"},
    {"codigo": "domiciliado", "label": "Está domiciliado"},
    {"codigo": "plantas_medicinais", "label": "Usa plantas medicinais"},
    {"codigo": "praticas_integrativas", "label": "Usa práticas integrativas e complementares"},
    {"codigo": "outras_condicoes", "label": "Outras condições de saúde"},
]
CONDICOES_SAUDE = [opcao["label"] for opcao in CONDICOES_SAUDE_OPCOES]


def get_next_house_number(quadra_id=None):
    conn = get_db_connection()
    if quadra_id:
        row = conn.execute(
            "SELECT COALESCE(MAX(numero_casa), 0) + 1 AS proximo FROM casas WHERE quadra_id = ?",
            (quadra_id,),
        ).fetchone()
    else:
        row = conn.execute("SELECT COALESCE(MAX(numero_casa), 0) + 1 AS proximo FROM casas").fetchone()
    conn.close()
    return row["proximo"]


def get_next_block_number():
    conn = get_db_connection()
    row = conn.execute("SELECT COALESCE(MAX(numero_quadra), 0) + 1 AS proximo FROM quadras").fetchone()
    conn.close()
    return row["proximo"]


def get_quadras():
    conn = get_db_connection()
    quadras = conn.execute("SELECT * FROM quadras ORDER BY numero_quadra, id").fetchall()
    conn.close()
    return quadras


def parse_optional_int(value):
    value = str(value or "").strip()
    return int(value) if value else None


def parse_positive_int(value, field_name, required=True):
    value = str(value or "").strip()
    if not value:
        if required:
            return None, f"Informe {field_name}."
        return None, None

    try:
        number = int(value)
    except ValueError:
        return None, f"{field_name.capitalize()} deve ser um número válido."

    if number < 1:
        return None, f"{field_name.capitalize()} deve ser maior que zero."
    return number, None


def quadra_exists(quadra_id):
    if quadra_id is None:
        return True

    conn = get_db_connection()
    exists = conn.execute("SELECT 1 FROM quadras WHERE id = ?", (quadra_id,)).fetchone() is not None
    conn.close()
    return exists


def pdf_text(value, style):
    return Paragraph(xml_escape(str(value or "")), style)


def pdf_count(value, style):
    return Paragraph(xml_escape(str(value if value not in (None, "") else 0)), style)


def pdf_image(path, max_width, max_height):
    image_source = path
    try:
        with PILImage.open(path) as source:
            source.thumbnail((1400, 700))
            optimized = BytesIO()
            source.convert("RGB").save(optimized, format="JPEG", quality=82, optimize=True)
            optimized.seek(0)
            image_source = optimized
    except (OSError, ValueError) as exc:
        logger.warning("Falha ao otimizar imagem do relatório %s: %s", path, exc)
        image_source = path

    image = Image(image_source)
    ratio = min(max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * ratio
    image.drawHeight = image.imageHeight * ratio
    image.hAlign = "CENTER"
    return image


def formatar_cpf_ou_cns(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())[:15]

    if len(digits) <= 11:
        if len(digits) <= 3:
            return digits
        if len(digits) <= 6:
            return f"{digits[:3]}.{digits[3:]}"
        if len(digits) <= 9:
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}"
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

    parts = [digits[:3], digits[3:7], digits[7:11], digits[11:15]]
    return " ".join(part for part in parts if part)


def formatar_data_br(value):
    if not value:
        return ""

    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value


def formatar_telefone(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())[:11]

    if len(digits) <= 2:
        return digits
    if len(digits) <= 6:
        return f"({digits[:2]}) {digits[2:]}"
    if len(digits) <= 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"


def whatsapp_link(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if not digits:
        return ""
    if len(digits) in (10, 11):
        digits = f"55{digits}"
    return f"https://wa.me/{digits}"


def normalizar_condicoes(values):
    selected = []
    for value in values:
        value = value.strip()
        codigo = condicao_codigo(value)
        if codigo and codigo not in selected:
            selected.append(codigo)
    return "\n".join(selected)


def listar_condicoes(value):
    return [condicao_label(item) for item in str(value or "").splitlines() if item]


def listar_condicao_codigos(value):
    return [condicao_codigo(item) for item in str(value or "").splitlines() if condicao_codigo(item)]


def paciente_tem_condicoes(paciente, condicoes):
    if not condicoes:
        return True
    return bool(set(listar_condicao_codigos(paciente["condicoes_saude"])) & set(condicoes))


def texto_normalizado(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in value if not unicodedata.combining(char)).lower()


CONDICOES_POR_CODIGO = {opcao["codigo"]: opcao["label"] for opcao in CONDICOES_SAUDE_OPCOES}
CONDICOES_CODIGO_POR_LABEL = {
    texto_normalizado(opcao["label"]): opcao["codigo"] for opcao in CONDICOES_SAUDE_OPCOES
}


def condicao_codigo(value):
    value = str(value or "").strip()
    if value in CONDICOES_POR_CODIGO:
        return value
    return CONDICOES_CODIGO_POR_LABEL.get(texto_normalizado(value), "")


def condicao_label(value):
    value = str(value or "").strip()
    if value in CONDICOES_POR_CODIGO:
        return CONDICOES_POR_CODIGO[value]
    codigo = CONDICOES_CODIGO_POR_LABEL.get(texto_normalizado(value))
    return CONDICOES_POR_CODIGO.get(codigo, value)


def apenas_digitos(value):
    return "".join(char for char in str(value or "") if char.isdigit())


def paciente_corresponde_busca(paciente, busca):
    busca_normalizada = texto_normalizado(busca).strip()
    busca_digitos = apenas_digitos(busca)
    nome_normalizado = texto_normalizado(paciente["nome"])
    documento_digitos = apenas_digitos(paciente["cpf"])

    if busca_digitos and busca_digitos in documento_digitos:
        return True

    if not busca_normalizada:
        return False

    if busca_normalizada in nome_normalizado:
        return True

    termos_busca = busca_normalizada.split()
    termos_nome = nome_normalizado.split()

    if termos_busca and all(
        any(
            termo in termo_nome or SequenceMatcher(None, termo, termo_nome).ratio() >= 0.62
            for termo_nome in termos_nome
        )
        for termo in termos_busca
    ):
        return True

    return SequenceMatcher(None, busca_normalizada, nome_normalizado).ratio() >= 0.58


def calcular_idade(data_nascimento):
    if not data_nascimento:
        return None

    try:
        nascimento = datetime.strptime(data_nascimento, "%Y-%m-%d").date()
    except ValueError:
        return None

    hoje = datetime.now().date()
    idade = hoje.year - nascimento.year
    if (hoje.month, hoje.day) < (nascimento.month, nascimento.day):
        idade -= 1
    return idade


def build_dashboard_stats(casas, pacientes):
    total_casas = len(casas)
    casas_vazias = sum(1 for casa in casas if casa["total_pacientes"] == 0)
    total_pacientes = len(pacientes)
    criancas = sum(1 for paciente in pacientes if (calcular_idade(paciente["data_nascimento"]) or 999) < 12)
    idosos = sum(1 for paciente in pacientes if (calcular_idade(paciente["data_nascimento"]) or 0) >= 60)
    gestantes = 0
    homens = 0
    mulheres = 0
    comorbidades = {condicao: 0 for condicao in CONDICOES_SAUDE}

    for paciente in pacientes:
        sexo = str(paciente["sexo"] or "").lower()
        if sexo == "masculino":
            homens += 1
        elif sexo == "feminino":
            mulheres += 1

        condicoes = listar_condicoes(paciente["condicoes_saude"])
        condicao_codigos = listar_condicao_codigos(paciente["condicoes_saude"])
        if "gestante" in condicao_codigos or any("gestante" in texto_normalizado(condicao) for condicao in condicoes):
            gestantes += 1

        for codigo in condicao_codigos:
            condicao = condicao_label(codigo)
            comorbidades[condicao] = comorbidades.get(condicao, 0) + 1

    return {
        "total_casas": total_casas,
        "casas_vazias": casas_vazias,
        "total_pacientes": total_pacientes,
        "criancas": criancas,
        "idosos": idosos,
        "gestantes": gestantes,
        "homens": homens,
        "mulheres": mulheres,
        "comorbidades": sorted(comorbidades.items(), key=lambda item: item[0]),
    }


def ler_codigos_condicoes(values):
    codigos = []
    for condicao in values:
        codigo = condicao_codigo(condicao)
        if codigo and codigo not in codigos:
            codigos.append(codigo)
    return codigos


def carregar_dados_relatorio(condicoes_selecionadas=None, filtro_sem_selecao=False):
    condicoes_selecionadas = condicoes_selecionadas or []
    conn = get_db_connection()
    casas = conn.execute(
        """
        SELECT casas.*, quadras.numero_quadra, COUNT(pacientes.id) AS total_pacientes
        FROM casas
        LEFT JOIN quadras ON quadras.id = casas.quadra_id
        LEFT JOIN pacientes ON pacientes.casa_id = casas.id
        GROUP BY casas.id
        ORDER BY quadras.numero_quadra IS NULL, quadras.numero_quadra, casas.numero_casa, casas.id
        """
    ).fetchall()
    pacientes = conn.execute("SELECT * FROM pacientes ORDER BY nome").fetchall()
    conn.close()

    if condicoes_selecionadas:
        pacientes = [
            paciente for paciente in pacientes if paciente_tem_condicoes(paciente, condicoes_selecionadas)
        ]
        total_por_casa = {}
        for paciente in pacientes:
            total_por_casa[paciente["casa_id"]] = total_por_casa.get(paciente["casa_id"], 0) + 1

        casas = [
            {**dict(casa), "total_pacientes": total_por_casa[casa["id"]]}
            for casa in casas
            if casa["id"] in total_por_casa
        ]
    elif filtro_sem_selecao:
        casas = []
        pacientes = []

    return casas, pacientes


app.add_template_filter(formatar_cpf_ou_cns, "cpf_cns")
app.add_template_filter(formatar_data_br, "data_br")
app.add_template_filter(formatar_telefone, "telefone")
app.add_template_filter(whatsapp_link, "whatsapp")
app.add_template_filter(listar_condicoes, "condicoes_lista")
app.add_template_filter(listar_condicao_codigos, "condicoes_codigos")


@app.context_processor
def inject_options():
    return {"opcoes_condicoes_saude": CONDICOES_SAUDE_OPCOES}


def get_house_or_404(casa_id):
    conn = get_db_connection()
    casa = conn.execute(
        """
        SELECT casas.*, quadras.numero_quadra
        FROM casas
        LEFT JOIN quadras ON quadras.id = casas.quadra_id
        WHERE casas.id = ?
        """,
        (casa_id,),
    ).fetchone()
    conn.close()
    if casa is None:
        flash("Casa não encontrada.", "warning")
        return None
    return casa


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_autenticado"):
        return redirect(url_for("index"))

    if request.method == "POST":
        client_ip = request.remote_addr or "desconhecido"
        if login_bloqueado(client_ip):
            flash("Muitas tentativas. Aguarde um minuto antes de tentar novamente.", "danger")
            return render_template("login.html", recuperacao_local=requisicao_e_local()), 429

        senha = request.form.get("senha", "")

        if check_password_hash(get_senha_hash(), senha):
            session.clear()
            session.permanent = True
            session["usuario_autenticado"] = True
            logger.info("Login bem-sucedido a partir de %s", client_ip)
            return redirect(proxima_url_segura(request.args.get("next")))

        registrar_falha_login(client_ip)
        logger.warning("Tentativa de login falhou a partir de %s", client_ip)
        flash("Senha inválida.", "danger")

    return render_template("login.html", recuperacao_local=requisicao_e_local())


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():
    if not requisicao_e_local():
        flash("A recuperação de senha só está disponível acessando o sistema na própria máquina onde ele roda.", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        nova_senha = request.form.get("nova_senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if len(nova_senha) < MIN_PASSWORD_LENGTH:
            flash(f"A nova senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.", "danger")
            return render_template("recuperar_senha.html")

        if nova_senha != confirmar_senha:
            flash("A confirmação não corresponde à nova senha.", "danger")
            return render_template("recuperar_senha.html")

        try:
            criar_backup("antes_recuperar_senha")
        except (sqlite3.Error, OSError) as exc:
            logger.error("Falha ao criar backup antes de recuperar senha: %s", exc)
            flash("Não foi possível criar backup de segurança. Tente novamente.", "danger")
            return render_template("recuperar_senha.html")

        set_senha_hash(generate_password_hash(nova_senha))
        session.clear()
        logger.warning("Senha redefinida via recuperação local (acesso 127.0.0.1).")
        flash("Senha redefinida com sucesso. Faça login com a nova senha.", "success")
        return redirect(url_for("login"))

    return render_template("recuperar_senha.html")


@app.route("/conta/senha", methods=["GET", "POST"])
@login_required
def alterar_senha():
    if request.method == "POST":
        client_ip = request.remote_addr or "desconhecido"
        if login_bloqueado(client_ip):
            flash("Muitas tentativas. Aguarde um minuto antes de tentar novamente.", "danger")
            return render_template("alterar_senha.html"), 429

        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if not check_password_hash(get_senha_hash(), senha_atual):
            registrar_falha_login(client_ip)
            logger.warning("Tentativa de troca de senha com senha atual incorreta a partir de %s", client_ip)
            flash("Senha atual incorreta.", "danger")
            return render_template("alterar_senha.html")

        if len(nova_senha) < MIN_PASSWORD_LENGTH:
            flash(f"A nova senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.", "danger")
            return render_template("alterar_senha.html")

        if nova_senha != confirmar_senha:
            flash("A confirmação não corresponde à nova senha.", "danger")
            return render_template("alterar_senha.html")

        if check_password_hash(get_senha_hash(), nova_senha):
            flash("A nova senha deve ser diferente da senha atual.", "danger")
            return render_template("alterar_senha.html")

        set_senha_hash(generate_password_hash(nova_senha))
        logger.info("Senha alterada com sucesso a partir de %s", client_ip)
        flash("Senha alterada com sucesso.", "success")
        return redirect(url_for("index"))

    return render_template("alterar_senha.html")


@app.route("/")
@login_required
def index():
    busca = request.args.get("busca", "").strip()
    conn = get_db_connection()
    quadras = conn.execute(
        """
        SELECT quadras.*, COUNT(casas.id) AS total_casas
        FROM quadras
        LEFT JOIN casas ON casas.quadra_id = quadras.id
        GROUP BY quadras.id
        ORDER BY quadras.numero_quadra, quadras.id
        """
    ).fetchall()
    casas = conn.execute(
        """
        SELECT casas.*, quadras.numero_quadra, COUNT(pacientes.id) AS total_pacientes
        FROM casas
        LEFT JOIN quadras ON quadras.id = casas.quadra_id
        LEFT JOIN pacientes ON pacientes.casa_id = casas.id
        GROUP BY casas.id
        ORDER BY quadras.numero_quadra IS NULL, quadras.numero_quadra, casas.numero_casa, casas.id
        """
    ).fetchall()
    pacientes = conn.execute("SELECT sexo, data_nascimento, condicoes_saude FROM pacientes").fetchall()
    pacientes_busca = []
    if busca:
        todos_pacientes = conn.execute(
            """
            SELECT pacientes.*, casas.numero_casa, casas.endereco, quadras.numero_quadra
            FROM pacientes
            LEFT JOIN casas ON casas.id = pacientes.casa_id
            LEFT JOIN quadras ON quadras.id = casas.quadra_id
            ORDER BY pacientes.nome
            """
        ).fetchall()
        pacientes_busca = [
            paciente for paciente in todos_pacientes if paciente_corresponde_busca(paciente, busca)
        ]
    conn.close()
    stats = build_dashboard_stats(casas, pacientes)
    return render_template(
        "index.html",
        casas=casas,
        quadras=quadras,
        stats=stats,
        busca=busca,
        pacientes_busca=pacientes_busca,
    )


@app.route("/quadra/nova", methods=["GET", "POST"])
@login_required
def cadastrar_quadra():
    if request.method == "POST":
        numero_quadra, error = parse_positive_int(request.form.get("numero_quadra"), "o número da quadra")

        if error:
            flash(error, "danger")
            return render_template("cadastrar_quadra.html", proximo_numero=get_next_block_number())

        conn = get_db_connection()
        conn.execute("INSERT INTO quadras (numero_quadra) VALUES (?)", (numero_quadra,))
        conn.commit()
        conn.close()
        flash("Quadra cadastrada com sucesso.", "success")
        return redirect(url_for("index"))

    return render_template("cadastrar_quadra.html", proximo_numero=get_next_block_number())


@app.route("/quadra/<int:quadra_id>/editar", methods=["GET", "POST"])
@login_required
def editar_quadra(quadra_id):
    conn = get_db_connection()
    quadra = conn.execute("SELECT * FROM quadras WHERE id = ?", (quadra_id,)).fetchone()

    if quadra is None:
        conn.close()
        flash("Quadra não encontrada.", "warning")
        return redirect(url_for("index"))

    if request.method == "POST":
        numero_quadra, error = parse_positive_int(request.form.get("numero_quadra"), "o número da quadra")
        if error:
            conn.close()
            flash(error, "danger")
            return render_template("editar_quadra.html", quadra=quadra)

        conn.execute("UPDATE quadras SET numero_quadra = ? WHERE id = ?", (numero_quadra, quadra_id))
        conn.commit()
        conn.close()
        flash("Quadra atualizada com sucesso.", "success")
        return redirect(url_for("index"))

    conn.close()
    return render_template("editar_quadra.html", quadra=quadra)


@app.route("/quadra/<int:quadra_id>/excluir", methods=["POST"])
@login_required
def excluir_quadra(quadra_id):
    try:
        criar_backup("antes_excluir_quadra")
    except (sqlite3.Error, OSError) as exc:
        logger.error("Falha ao criar backup antes de excluir quadra %s: %s", quadra_id, exc)
        flash("Não foi possível criar backup de segurança. Exclusão cancelada.", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    conn.execute("UPDATE casas SET quadra_id = NULL WHERE quadra_id = ?", (quadra_id,))
    conn.execute("DELETE FROM quadras WHERE id = ?", (quadra_id,))
    conn.commit()
    conn.close()
    flash("Quadra excluída. As casas vinculadas ficaram sem quadra.", "success")
    return redirect(url_for("index"))


@app.route("/casa/nova", methods=["GET", "POST"])
@login_required
def cadastrar_casa():
    quadras = get_quadras()
    if request.method == "POST":
        endereco = request.form.get("endereco", "").strip()
        numero_casa_text = request.form.get("numero_casa", "").strip()
        quadra_id, quadra_error = parse_positive_int(request.form.get("quadra_id"), "a quadra", required=False)

        if not endereco:
            flash("Informe o endereço da casa.", "danger")
            return render_template(
                "cadastrar_casa.html",
                proximo_numero=get_next_house_number(),
                endereco=endereco,
                numero_casa=numero_casa_text,
                quadra_id=quadra_id,
                quadras=quadras,
            )

        if quadra_error:
            flash(quadra_error, "danger")
            return render_template(
                "cadastrar_casa.html",
                proximo_numero=get_next_house_number(),
                endereco=endereco,
                numero_casa=numero_casa_text,
                quadra_id=None,
                quadras=quadras,
            )

        if not quadra_exists(quadra_id):
            flash("Quadra selecionada não existe.", "danger")
            return render_template(
                "cadastrar_casa.html",
                proximo_numero=get_next_house_number(),
                endereco=endereco,
                numero_casa=numero_casa_text,
                quadra_id=None,
                quadras=quadras,
            )

        numero_final, numero_error = parse_positive_int(numero_casa_text, "o número da casa", required=False)
        if numero_error:
            flash(numero_error, "danger")
            return render_template(
                "cadastrar_casa.html",
                proximo_numero=get_next_house_number(quadra_id),
                endereco=endereco,
                numero_casa=numero_casa_text,
                quadra_id=quadra_id,
                quadras=quadras,
            )

        if numero_final is None:
            numero_final = get_next_house_number(quadra_id)

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO casas (quadra_id, numero_casa, endereco) VALUES (?, ?, ?)",
            (quadra_id, numero_final, endereco),
        )
        conn.commit()
        conn.close()
        flash("Casa cadastrada com sucesso.", "success")
        return redirect(url_for("index"))

    return render_template("cadastrar_casa.html", proximo_numero=get_next_house_number(), quadras=quadras)


@app.route("/casa/<int:casa_id>")
@login_required
def detalhes_casa(casa_id):
    casa = get_house_or_404(casa_id)
    if casa is None:
        return redirect(url_for("index"))

    conn = get_db_connection()
    pacientes = conn.execute(
        "SELECT * FROM pacientes WHERE casa_id = ? ORDER BY nome",
        (casa_id,),
    ).fetchall()
    conn.close()
    return render_template("detalhes_casa.html", casa=casa, pacientes=pacientes)


@app.route("/casa/<int:casa_id>/editar", methods=["GET", "POST"])
@login_required
def editar_casa(casa_id):
    casa = get_house_or_404(casa_id)
    if casa is None:
        return redirect(url_for("index"))

    quadras = get_quadras()
    if request.method == "POST":
        numero_casa_text = request.form.get("numero_casa", "").strip()
        endereco = request.form.get("endereco", "").strip()
        quadra_id, quadra_error = parse_positive_int(request.form.get("quadra_id"), "a quadra", required=False)

        if not endereco:
            flash("Informe o endereço da casa.", "danger")
            return render_template("editar_casa.html", casa=casa, quadras=quadras)

        if quadra_error:
            flash(quadra_error, "danger")
            return render_template("editar_casa.html", casa=casa, quadras=quadras)

        if not quadra_exists(quadra_id):
            flash("Quadra selecionada não existe.", "danger")
            return render_template("editar_casa.html", casa=casa, quadras=quadras)

        numero_casa, numero_error = parse_positive_int(numero_casa_text, "o número da casa")
        if numero_error:
            flash(numero_error, "danger")
            return render_template("editar_casa.html", casa=casa, quadras=quadras)

        conn = get_db_connection()
        conn.execute(
            "UPDATE casas SET quadra_id = ?, numero_casa = ?, endereco = ? WHERE id = ?",
            (quadra_id, numero_casa, endereco, casa_id),
        )
        conn.commit()
        conn.close()
        flash("Casa atualizada com sucesso.", "success")
        return redirect(url_for("detalhes_casa", casa_id=casa_id))

    return render_template("editar_casa.html", casa=casa, quadras=quadras)


@app.route("/casa/<int:casa_id>/excluir", methods=["POST"])
@login_required
def excluir_casa(casa_id):
    try:
        criar_backup("antes_excluir_casa")
    except (sqlite3.Error, OSError) as exc:
        logger.error("Falha ao criar backup antes de excluir casa %s: %s", casa_id, exc)
        flash("Não foi possível criar backup de segurança. Exclusão cancelada.", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    conn.execute("DELETE FROM casas WHERE id = ?", (casa_id,))
    conn.commit()
    conn.close()
    flash("Casa e pacientes vinculados foram excluídos.", "success")
    return redirect(url_for("index"))


@app.route("/casa/<int:casa_id>/paciente/novo", methods=["GET", "POST"])
@login_required
def cadastrar_paciente(casa_id):
    casa = get_house_or_404(casa_id)
    if casa is None:
        return redirect(url_for("index"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("Informe o nome do paciente.", "danger")
            return render_template("cadastrar_paciente.html", casa=casa, paciente=request.form)

        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO pacientes (
                casa_id, nome, cpf, telefone, data_nascimento, sexo, nome_pai, nome_mae,
                condicoes_saude, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                casa_id,
                nome,
                formatar_cpf_ou_cns(request.form.get("cpf", "")),
                formatar_telefone(request.form.get("telefone", "")),
                request.form.get("data_nascimento", "").strip(),
                request.form.get("sexo", "").strip(),
                request.form.get("nome_pai", "").strip(),
                request.form.get("nome_mae", "").strip(),
                normalizar_condicoes(request.form.getlist("condicoes_saude")),
                request.form.get("observacao", "").strip(),
            ),
        )
        conn.commit()
        conn.close()
        flash("Paciente cadastrado com sucesso.", "success")
        return redirect(url_for("detalhes_casa", casa_id=casa_id))

    return render_template("cadastrar_paciente.html", casa=casa)


@app.route("/paciente/<int:paciente_id>/editar", methods=["GET", "POST"])
@login_required
def editar_paciente(paciente_id):
    conn = get_db_connection()
    paciente = conn.execute("SELECT * FROM pacientes WHERE id = ?", (paciente_id,)).fetchone()

    if paciente is None:
        conn.close()
        flash("Paciente não encontrado.", "warning")
        return redirect(url_for("index"))

    casa = conn.execute("SELECT * FROM casas WHERE id = ?", (paciente["casa_id"],)).fetchone()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("Informe o nome do paciente.", "danger")
            conn.close()
            return render_template("editar_paciente.html", paciente=paciente, casa=casa)

        conn.execute(
            """
            UPDATE pacientes
            SET nome = ?, cpf = ?, telefone = ?, data_nascimento = ?, nome_pai = ?,
                nome_mae = ?, sexo = ?, condicoes_saude = ?, observacao = ?
            WHERE id = ?
            """,
            (
                nome,
                formatar_cpf_ou_cns(request.form.get("cpf", "")),
                formatar_telefone(request.form.get("telefone", "")),
                request.form.get("data_nascimento", "").strip(),
                request.form.get("nome_pai", "").strip(),
                request.form.get("nome_mae", "").strip(),
                request.form.get("sexo", "").strip(),
                normalizar_condicoes(request.form.getlist("condicoes_saude")),
                request.form.get("observacao", "").strip(),
                paciente_id,
            ),
        )
        conn.commit()
        casa_id = paciente["casa_id"]
        conn.close()
        flash("Paciente atualizado com sucesso.", "success")
        return redirect(url_for("detalhes_casa", casa_id=casa_id))

    conn.close()
    return render_template("editar_paciente.html", paciente=paciente, casa=casa)


@app.route("/paciente/<int:paciente_id>/excluir", methods=["POST"])
@login_required
def excluir_paciente(paciente_id):
    try:
        criar_backup("antes_excluir_paciente")
    except (sqlite3.Error, OSError) as exc:
        logger.error("Falha ao criar backup antes de excluir paciente %s: %s", paciente_id, exc)
        flash("Não foi possível criar backup de segurança. Exclusão cancelada.", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    paciente = conn.execute("SELECT casa_id FROM pacientes WHERE id = ?", (paciente_id,)).fetchone()

    if paciente is None:
        conn.close()
        flash("Paciente não encontrado.", "warning")
        return redirect(url_for("index"))

    casa_id = paciente["casa_id"]
    conn.execute("DELETE FROM pacientes WHERE id = ?", (paciente_id,))
    conn.commit()
    conn.close()
    flash("Paciente excluído com sucesso.", "success")
    return redirect(url_for("detalhes_casa", casa_id=casa_id))


@app.route("/exportar/preview")
@login_required
def preview_exportar_pdf():
    condicoes_selecionadas = ler_codigos_condicoes(request.args.getlist("condicoes"))
    casas, pacientes = carregar_dados_relatorio(condicoes_selecionadas)
    stats = build_dashboard_stats(casas, pacientes)
    comorbidades = dict(stats["comorbidades"])
    condicoes_preview = [
        {
            "codigo": codigo,
            "label": condicao_label(codigo),
            "total": comorbidades.get(condicao_label(codigo), 0),
        }
        for codigo in condicoes_selecionadas
    ]

    return jsonify(
        {
            "modo": "filtrado" if condicoes_selecionadas else "geral",
            "condicoes": condicoes_preview,
            "stats": {
                "total_casas": stats["total_casas"],
                "casas_vazias": stats["casas_vazias"],
                "total_pacientes": stats["total_pacientes"],
                "criancas": stats["criancas"],
                "idosos": stats["idosos"],
                "gestantes": stats["gestantes"],
                "homens": stats["homens"],
                "mulheres": stats["mulheres"],
            },
        }
    )


@app.route("/exportar/pdf")
@login_required
def exportar_pdf():
    condicoes_selecionadas = ler_codigos_condicoes(request.args.getlist("condicoes"))
    modo_filtro = request.args.get("filtrar") == "1" or bool(condicoes_selecionadas)
    filtro_ativo = bool(condicoes_selecionadas)
    filtro_sem_selecao = modo_filtro and not filtro_ativo
    filtro_labels = [condicao_label(codigo) for codigo in condicoes_selecionadas]
    casas, pacientes = carregar_dados_relatorio(condicoes_selecionadas, filtro_sem_selecao)

    pacientes_por_casa = {}
    for paciente in pacientes:
        pacientes_por_casa.setdefault(paciente["casa_id"], []).append(paciente)

    data_geracao = datetime.now().strftime("%d/%m/%Y às %H:%M")

    def adicionar_cabecalho_rodape(canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(colors.HexColor("#0b5ed7"))
            canvas.drawString(1.5 * cm, A4[1] - 1.1 * cm, "RELATÓRIO")
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor("#6c757d"))
            canvas.drawRightString(A4[0] - 1.5 * cm, A4[1] - 1.1 * cm, f"Gerado em {data_geracao}")
            canvas.setStrokeColor(colors.HexColor("#dee2e6"))
            canvas.line(1.5 * cm, A4[1] - 1.3 * cm, A4[0] - 1.5 * cm, A4[1] - 1.3 * cm)

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6c757d"))
        canvas.drawString(1.5 * cm, 0.9 * cm, "Saúde Simples")
        canvas.drawRightString(A4[0] - 1.5 * cm, 0.9 * cm, f"Página {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TituloRelatorio",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0b5ed7"),
        alignment=1,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SubtituloRelatorio",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#6c757d"),
        alignment=1,
        spaceAfter=12,
    )
    image_title_style = ParagraphStyle(
        "TituloImagem",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#495057"),
        alignment=1,
        spaceBefore=2,
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "SecaoRelatorio",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0b5ed7"),
        spaceBefore=10,
        spaceAfter=8,
    )
    house_style = ParagraphStyle(
        "CasaTitulo",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=colors.white,
    )
    block_style = ParagraphStyle(
        "QuadraTitulo",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0b5ed7"),
        spaceBefore=8,
        spaceAfter=6,
    )
    normal_style = ParagraphStyle(
        "TextoNormal",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#212529"),
    )
    label_style = ParagraphStyle(
        "Rotulo",
        parent=normal_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#495057"),
    )
    number_style = ParagraphStyle(
        "NumeroResumo",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=17,
        textColor=colors.HexColor("#0b5ed7"),
        alignment=1,
    )
    empty_style = ParagraphStyle(
        "Vazio",
        parent=normal_style,
        textColor=colors.HexColor("#6c757d"),
        alignment=1,
    )

    total_pacientes = len(pacientes)
    stats = build_dashboard_stats(casas, pacientes)
    elements = [
        Paragraph("RELATÓRIO", title_style),
        Paragraph(
            f"Gerado em {data_geracao} | {len(casas)} casa(s) | {total_pacientes} paciente(s)",
            subtitle_style,
        ),
    ]
    if modo_filtro:
        filtro_texto = ", ".join(filtro_labels) if filtro_labels else "nenhuma comorbidade selecionada"
        elements.append(
            Paragraph(f"<b>Filtro por comorbidade:</b> {filtro_texto}", subtitle_style)
        )

    report_image_path = os.path.join(BASE_DIR, "image", "image.jpg")
    if os.path.exists(report_image_path):
        elements.extend(
            [
                Paragraph("Imagem da Região da UBS", image_title_style),
                pdf_image(report_image_path, 16.2 * cm, 4.4 * cm),
                Spacer(1, 10),
            ]
        )

    summary_top = [
        [
            pdf_text("Total de casas", label_style),
            pdf_text("Casas vazias", label_style),
            pdf_text("Pacientes", label_style),
            pdf_text("Crianças", label_style),
            pdf_text("Idosos 60+", label_style),
        ],
        [
            pdf_count(stats["total_casas"], number_style),
            pdf_count(stats["casas_vazias"], number_style),
            pdf_count(stats["total_pacientes"], number_style),
            pdf_count(stats["criancas"], number_style),
            pdf_count(stats["idosos"], number_style),
        ],
    ]
    summary_bottom = [
        [
            pdf_text("Gestantes", label_style),
            pdf_text("Homens", label_style),
            pdf_text("Mulheres", label_style),
        ],
        [
            pdf_count(stats["gestantes"], number_style),
            pdf_count(stats["homens"], number_style),
            pdf_count(stats["mulheres"], number_style),
        ],
    ]

    summary_top_table = Table(summary_top, colWidths=[3.4 * cm, 3.4 * cm, 3.4 * cm, 3.4 * cm, 3.4 * cm])
    summary_bottom_table = Table(summary_bottom, colWidths=[5.66 * cm, 5.66 * cm, 5.66 * cm])
    summary_style = TableStyle(
        [
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cfe2ff")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dee2e6")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fbff")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (0, 1), (-1, 1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
    )
    summary_top_table.setStyle(summary_style)
    summary_bottom_table.setStyle(summary_style)
    resumo_titulo = "Resumo do filtro" if modo_filtro else "Resumo geral"
    elements.extend(
        [
            Paragraph(resumo_titulo, section_style),
            summary_top_table,
            Spacer(1, 4),
            summary_bottom_table,
            Spacer(1, 10),
        ]
    )

    comorbidity_rows = [[pdf_text("Condição", label_style), pdf_text("Total", label_style), pdf_text("Condição", label_style), pdf_text("Total", label_style)]]
    selected_condition_labels = set(filtro_labels)
    selected_condition_cells = []
    selected_condition_style = ParagraphStyle(
        "CondicaoSelecionada",
        parent=normal_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#084298"),
    )
    selected_count_style = ParagraphStyle(
        "TotalCondicaoSelecionada",
        parent=selected_condition_style,
        alignment=1,
    )
    comorbidades = stats["comorbidades"]
    for index in range(0, len(comorbidades), 2):
        left_name, left_total = comorbidades[index]
        right_name = ""
        right_total = ""
        if index + 1 < len(comorbidades):
            right_name, right_total = comorbidades[index + 1]
        row_number = len(comorbidity_rows)
        left_selected = modo_filtro and left_name in selected_condition_labels
        right_selected = modo_filtro and right_name in selected_condition_labels
        if left_selected:
            selected_condition_cells.append((row_number, 0, 1))
        if right_selected:
            selected_condition_cells.append((row_number, 2, 3))
        comorbidity_rows.append(
            [
                pdf_text(left_name, selected_condition_style if left_selected else normal_style),
                pdf_count(left_total, selected_count_style if left_selected else normal_style),
                pdf_text(right_name, selected_condition_style if right_selected else normal_style),
                pdf_count(right_total, selected_count_style if right_selected else normal_style) if right_name else pdf_text("", normal_style),
            ]
        )

    comorbidity_table = Table(comorbidity_rows, repeatRows=1, colWidths=[7 * cm, 1.5 * cm, 7 * cm, 1.5 * cm])
    comorbidity_style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dee2e6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
    ]
    for row_number, start_col, end_col in selected_condition_cells:
        comorbidity_style_commands.extend(
            [
                ("BACKGROUND", (start_col, row_number), (end_col, row_number), colors.HexColor("#fff3cd")),
                ("BOX", (start_col, row_number), (end_col, row_number), 0.5, colors.HexColor("#ffc107")),
            ]
        )
    comorbidity_table.setStyle(TableStyle(comorbidity_style_commands))
    comorbidity_title = "Contagem de comorbidades no filtro" if modo_filtro else "Contagem por comorbidade"
    elements.extend([Paragraph(comorbidity_title, section_style), comorbidity_table, Spacer(1, 12)])

    if not casas:
        if filtro_sem_selecao:
            empty_message = "Nenhuma comorbidade selecionada para exportação."
        elif filtro_ativo:
            empty_message = "Nenhum paciente encontrado para as comorbidades selecionadas."
        else:
            empty_message = "Nenhuma casa cadastrada."
        elements.append(
            KeepTogether(
                [
                    Paragraph("Pacientes por quadra e casa", section_style),
                    Paragraph(empty_message, normal_style),
                ]
            )
        )

    quadra_atual = object()
    primeira_casa = True
    for casa in casas:
        casa_elements = []
        quadra_label = f"Quadra Nº {casa['numero_quadra']}" if casa["numero_quadra"] else "Sem quadra"

        if primeira_casa:
            casa_elements.append(Paragraph("Pacientes por quadra e casa", section_style))

        if quadra_label != quadra_atual:
            casa_elements.append(Paragraph(quadra_label, block_style))
            quadra_atual = quadra_label

        lista_pacientes = pacientes_por_casa.get(casa["id"], [])
        total_da_casa = len(lista_pacientes)

        bloco_casa = [
            [
                Paragraph(f"Casa Nº {casa['numero_casa']}", house_style),
                Paragraph(f"{total_da_casa} paciente(s)", house_style),
            ],
            [
                Paragraph(f"<b>Endereço:</b> {xml_escape(casa['endereco'] or '')}", normal_style),
                "",
            ],
        ]
        tabela_casa = Table(bloco_casa, colWidths=[13.0 * cm, 4.0 * cm])
        tabela_casa.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
                    ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f1f6ff")),
                    ("SPAN", (0, 1), (1, 1)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b6d4fe")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#084298")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ]
            )
        )

        dados = [
            [
                pdf_text("Paciente", label_style),
                pdf_text("CPF/CNS", label_style),
                pdf_text("Nascimento", label_style),
                pdf_text("Telefone", label_style),
                pdf_text("Filiação", label_style),
            ]
        ]

        if lista_pacientes:
            for paciente in lista_pacientes:
                filiacao = (
                    f"<b>Pai:</b> {xml_escape(paciente['nome_pai'] or '-')}<br/>"
                    f"<b>Mãe:</b> {xml_escape(paciente['nome_mae'] or '-')}"
                )
                dados.append(
                    [
                        pdf_text(paciente["nome"], normal_style),
                        pdf_text(formatar_cpf_ou_cns(paciente["cpf"]), normal_style),
                        pdf_text(formatar_data_br(paciente["data_nascimento"]), normal_style),
                        pdf_text(formatar_telefone(paciente["telefone"]), normal_style),
                        Paragraph(filiacao, normal_style),
                    ]
                )
                if paciente["observacao"]:
                    dados.append(
                        [
                            Paragraph(f"<b>Observação:</b> {xml_escape(paciente['observacao'] or '')}", normal_style),
                            "",
                            "",
                            "",
                            "",
                        ]
                    )
                condicoes = listar_condicoes(paciente["condicoes_saude"])
                if condicoes:
                    dados.append(
                        [
                            Paragraph(f"<b>Condições de saúde:</b> {', '.join(condicoes)}", normal_style),
                            "",
                            "",
                            "",
                            "",
                        ]
                    )
        else:
            dados.append([Paragraph("Nenhum paciente cadastrado", empty_style), "", "", "", ""])

        tabela = Table(dados, repeatRows=1, colWidths=[3.6 * cm, 2.8 * cm, 2.2 * cm, 2.7 * cm, 5.7 * cm])
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#212529")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dee2e6")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        for row_index, row in enumerate(dados):
            if row_index > 0 and row[1:] == ["", "", "", ""]:
                tabela.setStyle(
                    TableStyle(
                        [
                            ("SPAN", (0, row_index), (-1, row_index)),
                            ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f1f6ff")),
                        ]
                    )
                )
        casa_intro = casa_elements + [tabela_casa, Spacer(1, 6)]
        if len(dados) <= 8:
            elements.append(KeepTogether(casa_intro + [tabela, Spacer(1, 14)]))
        else:
            elements.append(KeepTogether(casa_intro))
            elements.append(tabela)
            elements.append(Spacer(1, 14))
        primeira_casa = False

    doc.build(elements, onFirstPage=adicionar_cabecalho_rodape, onLaterPages=adicionar_cabecalho_rodape)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="relatorio_pacientes_por_casa.pdf",
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    init_db()
    garantir_senha_inicial(BOOTSTRAP_PASSWORD_HASH)
    try:
        criar_backup("inicializacao")
    except (sqlite3.Error, OSError) as exc:
        logger.warning("Falha ao criar backup de inicialização: %s", exc)

    debug_enabled = os.environ.get("SAUDE_SIMPLES_DEBUG", "").lower() in ("1", "true", "sim", "yes")
    host = os.environ.get("SAUDE_SIMPLES_HOST", "127.0.0.1")
    port = int(os.environ.get("SAUDE_SIMPLES_PORT", "5001"))

    if debug_enabled:
        app.run(debug=True, host=host, port=port)
    else:
        from waitress import serve

        logger.info("Iniciando servidor de produção (waitress) em %s:%s", host, port)
        serve(app, host=host, port=port)
