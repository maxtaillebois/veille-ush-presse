#!/usr/bin/env python3
"""
Generateur PDF - Veille Presse USH
Version GitHub Actions (chemins relatifs au repo)
Charte Procivis sept 2025 :
  Vert institutionnel #97C33D | Gris institutionnel #515459
  Polices : Bricolage Grotesque (titres) + Helvetica (corps)

Usage:
  python generate_pdf.py                  # lit articles.json, produit le PDF
  python generate_pdf.py selection.json   # lit un JSON spécifique
"""

import json, os, sys
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, Spacer, PageBreak,
    Table, TableStyle
)
from reportlab.platypus.doctemplate import BaseDocTemplate, PageTemplate, Frame
from pypdf import PdfReader, PdfWriter

# -- Chemins relatifs au repo --
REPO_DIR      = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR     = os.path.join(REPO_DIR, "fonts")
ASSETS_DIR    = os.path.join(REPO_DIR, "assets")
LOGO_PATH     = os.path.join(ASSETS_DIR, "logo_procivis.png")

# -- Enregistrement des polices --
def register_fonts():
    fonts = {
        'Bricolage-Regular': 'BricolageGrotesque-Regular.ttf',
        'Bricolage-Medium': 'BricolageGrotesque-Medium.ttf',
        'Bricolage-Bold': 'BricolageGrotesque-Bold.ttf',
    }
    for name, filename in fonts.items():
        path = os.path.join(FONTS_DIR, filename)
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception as e:
                print(f"  Warning: could not register {name}: {e}")

register_fonts()

# -- Couleurs charte Procivis --
C_VERT       = HexColor('#97C33D')
C_GRIS       = HexColor('#515459')
C_VERT_PALE  = HexColor('#DCEDC0')
C_VERT_40    = HexColor('#C5DC8C')
C_GRIS_PALE  = HexColor('#D1D2D3')
C_GRIS_40    = HexColor('#A8A9AB')
C_WHITE      = HexColor('#FFFFFF')
C_BLACK      = HexColor('#1a1a1a')

W, H = A4

MOIS_FR = [
    '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
]

import re


def smart_split_text(texte, article_titre='', article_auteur=''):
    """
    Découpe un texte d'article LuQi en blocs typés pour le PDF.

    Le texte LuQi arrive en un seul bloc continu, souvent pollué par :
    - Le titre de l'article répété au début
    - Des crédits photo (© ...)
    - Un sommaire web (liste de questions/intertitres empilés)
    - Le nom de l'auteur à la fin

    Le traitement :
    1. Nettoie le texte (supprime bruit)
    2. Découpe en phrases
    3. Détecte les intertitres (segments courts, sans verbe conjugué typique)
    4. Supprime les blocs de sommaire (intertitres consécutifs sans contenu)
    5. Regroupe les phrases en paragraphes de 3 phrases pour aérer la lecture
    """
    text = texte.strip()
    if not text:
        return []

    # --- Normalisation : supprimer césures et sauts de ligne parasites ---
    # Césure en fin de ligne : "de-\nmande" → "demande"
    text = re.sub(r'-\s*\n\s*', '', text)
    # Doubles sauts de ligne → marqueur de paragraphe
    text = text.replace('\n\n', '§§PARA§§')
    # Simples sauts de ligne → espace (lignes continues dans la même phrase)
    text = text.replace('\n', ' ')
    # Restaurer les vrais paragraphes
    text = text.replace('§§PARA§§', '\n')
    # Nettoyer les espaces multiples
    text = re.sub(r'  +', ' ', text)

    # --- Nettoyage ---
    text = _clean_text(text, article_titre, article_auteur)

    # --- Découpe en phrases ---
    # Si le texte a des \n (vrais paragraphes), les utiliser comme base
    raw_blocks = [b.strip() for b in text.split('\n') if b.strip()]

    # Si un seul bloc ou blocs trop gros, redécouper par phrases
    if len(raw_blocks) == 1 or max(len(b) for b in raw_blocks) > 700:
        # Fusionner et redécouper proprement
        full_text = ' '.join(raw_blocks)
        raw_blocks = _split_sentences(full_text)

    # --- Typage et filtrage ---
    typed_blocks = []
    for block in raw_blocks:
        if _is_subtitle(block):
            typed_blocks.append({'type': 'subtitle', 'text': block})
        else:
            typed_blocks.append({'type': 'paragraph', 'text': block})

    # --- Suppression des sommaires (intertitres consécutifs) ---
    typed_blocks = _remove_toc_blocks(typed_blocks)

    return typed_blocks


def _clean_text(text, titre='', auteur=''):
    """Supprime le bruit du texte LuQi."""

    # Supprimer les crédits photo au début (© ... jusqu'à la première phrase)
    text = re.sub(r'^©[^\.\!]{0,300}[\.\!]?\s*', '', text)
    # Variante : "Photo NR, ..." ou "(Photo ...)"
    text = re.sub(r'^\(Photo[^\)]{0,80}\)\s*', '', text)

    # Supprimer le titre de l'article s'il est répété au début du texte
    if titre and len(titre) > 10:
        # Chercher le titre exact dans les 200 premiers caractères
        titre_lower = titre.lower()
        text_start_lower = text[:250].lower()
        pos = text_start_lower.find(titre_lower)
        if pos >= 0:
            text = text[pos + len(titre):].strip()

    # Supprimer les indications de lieu en début (ex: "centre-val de loire ")
    text = re.sub(r'^[a-zà-ÿ\s\-]{5,40}(?=[A-ZÀÂÉÈÊËÏÎÔÙÛÜÇ])', '', text)

    # Supprimer les crédits photo entre parenthèses
    text = re.sub(r'\(Photo[^\)]{0,80}\)', '', text)

    # Supprimer le nom de l'auteur seul à la fin
    if auteur and len(auteur) > 3:
        auteur_escaped = re.escape(auteur)
        text = re.sub(r'\s*' + auteur_escaped + r'\s*$', '', text)

    # Supprimer "Sommaire" suivi d'une liste de titres de sections
    text = re.sub(r'Sommaire\s+', '', text, count=1)

    # Supprimer un nom propre isolé à la toute fin (1-3 mots, que des majuscules initiales)
    # Ex: "Emmanuelle Cosse", "Mathieu G.", "Christine Berkovicius"
    text = re.sub(r'\s+[A-ZÀÂÉÈÊËÏÎÔÙÛÜÇ][a-zà-ÿ]+(?:\s+[A-ZÀÂÉÈÊËÏÎÔÙÛÜÇ][\.\w]*){0,2}\s*$', '', text)

    return text.strip()


def _split_sentences(text):
    """
    Découpe un texte continu en phrases, puis regroupe par paquets
    de 3 phrases pour créer des paragraphes lisibles.
    Isole les intertitres détectés.
    """
    # Découper en phrases : fin de phrase (. ! ? ») suivie d'espace + majuscule/guillemet
    sentences = re.split(
        r'(?<=[\.\!\?»])\s+(?=[A-ZÀÂÉÈÊËÏÎÔÙÛÜÇ«\""])',
        text
    )

    if len(sentences) <= 1:
        return _force_split(text, 500)

    segments = []
    current_group = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if _is_subtitle(sentence):
            if current_group:
                segments.append(' '.join(current_group))
                current_group = []
            segments.append(sentence)
        else:
            current_group.append(sentence)
            if len(current_group) >= 3:
                segments.append(' '.join(current_group))
                current_group = []

    if current_group:
        segments.append(' '.join(current_group))

    # Post-traitement : si un paragraphe est trop long (>700 chars),
    # le redécouper (cas des textes OCR avec peu de frontières de phrases)
    final = []
    for seg in segments:
        if len(seg) > 700 and not _is_subtitle(seg):
            final.extend(_force_split(seg, 450))
        else:
            final.append(seg)

    return final


def _force_split(text, max_chars=500):
    """
    Dernier recours : découpe un texte tous les ~max_chars caractères
    en cherchant la fin de phrase la plus proche.
    """
    if len(text) <= max_chars:
        return [text]

    segments = []
    remaining = text

    while len(remaining) > max_chars:
        # Chercher le dernier point suivi d'un espace dans la zone max_chars
        cut_zone = remaining[:max_chars + 100]
        last_period = -1
        for m in re.finditer(r'[\.\!\?»]\s', cut_zone):
            last_period = m.end()

        if last_period > 100:  # assez de texte avant la coupure
            segments.append(remaining[:last_period].strip())
            remaining = remaining[last_period:].strip()
        else:
            # Pas de fin de phrase trouvée, couper à l'espace le plus proche
            space_pos = remaining.rfind(' ', 0, max_chars)
            if space_pos > 100:
                segments.append(remaining[:space_pos].strip())
                remaining = remaining[space_pos:].strip()
            else:
                segments.append(remaining[:max_chars].strip())
                remaining = remaining[max_chars:].strip()

    if remaining.strip():
        segments.append(remaining.strip())

    return segments


def _is_subtitle(text):
    """
    Un intertitre est un segment court qui sert de titre de section.
    Critères stricts pour éviter les faux positifs.
    """
    text = text.strip()
    if len(text) > 80 or len(text) < 5:
        return False
    # Pas une citation
    if text[0] in ('«', '"', "'", '—', '–'):
        return False
    # Ne finit PAS par un point ou des guillemets fermants
    # Les ? sont OK (intertitres interrogatifs)
    if text.endswith('.') or text.endswith('!') or text.endswith('»') or text.endswith('"'):
        return False
    # Maximum 12 mots
    if len(text.split()) > 12:
        return False
    # Doit contenir au moins une majuscule (sinon c'est juste un fragment)
    if not any(c.isupper() for c in text):
        return False
    # Un ou deux mots seulement = probablement un nom propre, pas un intertitre
    if len(text.split()) <= 2 and not text.endswith('?'):
        return False
    return True


def _remove_toc_blocks(blocks):
    """
    Supprime les blocs de type 'sommaire' : quand 2+ intertitres se suivent
    sans paragraphe entre eux, c'est le sommaire de l'article web.
    On les retire car les vrais intertitres apparaîtront plus loin avec leur contenu.
    """
    if len(blocks) <= 2:
        return blocks

    # Identifier les groupes d'intertitres consécutifs
    to_remove = set()
    i = 0
    while i < len(blocks):
        if blocks[i]['type'] == 'subtitle':
            # Compter combien d'intertitres se suivent
            j = i
            while j < len(blocks) and blocks[j]['type'] == 'subtitle':
                j += 1
            consecutive = j - i
            # 2+ intertitres consécutifs = sommaire → supprimer
            if consecutive >= 2:
                for k in range(i, j):
                    to_remove.add(k)
            i = j
        else:
            i += 1

    return [b for idx, b in enumerate(blocks) if idx not in to_remove]


def load_articles(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    semaine = data.get('semaine', 'S??-2026')
    all_arts = data.get('articles', [])
    # Filtrer les articles sélectionnés
    selected = [a for a in all_arts if a.get('selectionne', False)]
    if not selected:
        selected = all_arts  # fallback: tous si aucun n'est marqué
    return semaine, selected

def format_date_fr(date_str):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return f"{d.day} {MOIS_FR[d.month]} {d.year}"
    except:
        return date_str

def date_range(articles):
    dates = []
    for a in articles:
        try:
            dates.append(datetime.strptime(a['date_publication'], '%Y-%m-%d'))
        except:
            pass
    if not dates:
        return ('', '')
    mn, mx = min(dates), max(dates)
    return (
        f"{mn.day} {MOIS_FR[mn.month]} {mn.year}",
        f"{mx.day} {MOIS_FR[mx.month]} {mx.year}"
    )


# ============================================================
# COUVERTURE
# ============================================================

def draw_cover(output_path, semaine, articles):
    c = canvas.Canvas(output_path, pagesize=A4)

    c.setFillColor(C_WHITE)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Barre verte fine en haut
    c.setFillColor(C_VERT)
    c.rect(0, H - 3*mm, W, 3*mm, fill=1, stroke=0)

    # Logo Procivis en haut à droite
    logo_w = W * 0.22
    logo_h = logo_w * 0.35
    if os.path.exists(LOGO_PATH):
        c.drawImage(LOGO_PATH, W - logo_w - 25*mm, H - logo_h - 18*mm,
                     width=logo_w, height=logo_h, preserveAspectRatio=True, mask='auto')

    y_base = H * 0.52

    # "Veille presse USH" sur une seule ligne
    title_font = "Bricolage-Bold"
    try:
        pdfmetrics.getFont(title_font)
    except:
        title_font = "Helvetica-Bold"
    c.setFont(title_font, 36)
    c.setFillColor(C_GRIS)
    c.drawString(30*mm, y_base + 10*mm, "Veille presse ")
    vp_width = c.stringWidth("Veille presse ", title_font, 36)
    c.setFillColor(C_VERT)
    c.drawString(30*mm + vp_width, y_base + 10*mm, "USH")

    # Filet vert court
    c.setStrokeColor(C_VERT)
    c.setLineWidth(2)
    c.line(30*mm, y_base - 1*mm, 95*mm, y_base - 1*mm)

    # Sous-titre + dates
    d_min, d_max = date_range(articles)
    c.setFont("Helvetica", 13)
    c.setFillColor(C_GRIS)
    if d_min == d_max:
        subtitle = f"Notre sélection pour la semaine du {d_min}"
    else:
        subtitle = f"Notre sélection pour la semaine du {d_min} au {d_max}"
    c.drawString(30*mm, y_base - 18*mm, subtitle)

    # Bandeau vert en bas
    bandeau_h = 28*mm
    c.setFillColor(C_VERT)
    c.rect(0, 0, W, bandeau_h, fill=1, stroke=0)
    c.setFillColor(C_WHITE)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(30*mm, bandeau_h - 12*mm, "PROCIVIS")
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor('#D6E8A8'))
    c.drawString(30*mm, bandeau_h - 22*mm, "Le premier acteur coopératif du logement")

    c.save()


# ============================================================
# CONTENU (Platypus)
# ============================================================

def get_styles():
    styles = getSampleStyleSheet()

    title_font = "Bricolage-Bold"
    try:
        pdfmetrics.getFont(title_font)
    except:
        title_font = "Helvetica-Bold"

    body_font = 'Helvetica'
    body_bold = 'Helvetica-Bold'
    body_light = 'Helvetica'

    try:
        pdfmetrics.getFont('Bricolage-Medium')
        bricolage_medium = 'Bricolage-Medium'
    except:
        bricolage_medium = 'Helvetica'

    styles.add(ParagraphStyle(
        'TocTitle', parent=styles['Normal'],
        fontName=title_font, fontSize=24, textColor=C_GRIS,
        spaceAfter=20, spaceBefore=10
    ))
    styles.add(ParagraphStyle(
        'TocEntry', parent=styles['Normal'],
        fontName=body_font, fontSize=11, textColor=C_BLACK,
        spaceBefore=10, spaceAfter=10, leftIndent=20, leading=16
    ))
    styles.add(ParagraphStyle(
        'ArticleMedia', parent=styles['Normal'],
        fontName=body_bold, fontSize=9, textColor=C_VERT,
        spaceBefore=0, spaceAfter=4, leading=14
    ))
    styles.add(ParagraphStyle(
        'ArticleTitle', parent=styles['Normal'],
        fontName=title_font, fontSize=18, textColor=C_GRIS,
        spaceBefore=4, spaceAfter=10, leading=24
    ))
    styles.add(ParagraphStyle(
        'ArticleMeta', parent=styles['Normal'],
        fontName=body_light, fontSize=10, textColor=C_GRIS_40,
        spaceBefore=0, spaceAfter=6, leading=14
    ))
    styles.add(ParagraphStyle(
        'ArticleKeywords', parent=styles['Normal'],
        fontName=bricolage_medium, fontSize=9, textColor=C_VERT,
        spaceBefore=2, spaceAfter=14, leading=13
    ))
    styles.add(ParagraphStyle(
        'ArticleBody', parent=styles['Normal'],
        fontName=body_font, fontSize=10, textColor=C_BLACK,
        alignment=TA_JUSTIFY, spaceBefore=3, spaceAfter=5,
        leading=16, firstLineIndent=0
    ))
    styles.add(ParagraphStyle(
        'ArticleSource', parent=styles['Normal'],
        fontName=body_font, fontSize=9, textColor=C_VERT,
        spaceBefore=12, spaceAfter=0, leading=13
    ))
    styles.add(ParagraphStyle(
        'ArticleButton', parent=styles['Normal'],
        fontName=body_bold, fontSize=9, textColor=C_WHITE,
        spaceBefore=0, spaceAfter=0, leading=13,
        alignment=TA_LEFT
    ))
    return styles


def header_footer(canvas_obj, doc):
    canvas_obj.saveState()

    # Barre verte fine en haut
    canvas_obj.setFillColor(C_VERT)
    canvas_obj.rect(0, H - 3*mm, W, 3*mm, fill=1, stroke=0)

    # Bandeau header gris
    canvas_obj.setFillColor(C_GRIS)
    canvas_obj.rect(0, H - 16*mm, W, 13*mm, fill=1, stroke=0)

    canvas_obj.setFillColor(C_WHITE)
    canvas_obj.setFont("Helvetica-Bold", 9)
    canvas_obj.drawString(20*mm, H - 12*mm, "VEILLE PRESSE USH")

    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(C_VERT_PALE)
    canvas_obj.drawRightString(W - 20*mm, H - 12*mm, f"Page {doc.page}")

    # Pied de page
    canvas_obj.setFillColor(C_VERT)
    canvas_obj.rect(0, 9*mm, W, 0.5*mm, fill=1, stroke=0)

    canvas_obj.setFillColor(C_GRIS_40)
    canvas_obj.setFont("Helvetica", 7)
    canvas_obj.drawString(20*mm, 4.5*mm, "Procivis — Le premier acteur coopératif du logement")
    canvas_obj.drawRightString(W - 20*mm, 4.5*mm, datetime.now().strftime('%d/%m/%Y'))

    canvas_obj.restoreState()


def build_content(output_path, semaine, articles):
    frame = Frame(20*mm, 16*mm, W - 40*mm, H - 36*mm, id='main')
    template = PageTemplate(id='content', frames=[frame], onPage=header_footer)
    doc = BaseDocTemplate(output_path, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=16*mm)
    doc.addPageTemplates([template])

    styles = get_styles()
    story = []

    # Sommaire
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("Sommaire", styles['TocTitle']))
    story.append(Spacer(1, 3*mm))

    toc_line = Table([['']], colWidths=[W - 40*mm])
    toc_line.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 2, C_VERT)]))
    story.append(toc_line)
    story.append(Spacer(1, 5*mm))

    for idx, art in enumerate(articles):
        num = f"{idx + 1:02d}"
        titre = art.get('titre', 'Sans titre')
        media = art.get('media', '')
        date_fr = format_date_fr(art.get('date_publication', ''))
        auteur = art.get('auteur', '')

        meta_parts = [media]
        if date_fr:
            meta_parts.append(date_fr)
        if auteur:
            meta_parts.append(auteur)
        meta = ' — '.join(meta_parts)

        anchor_name = f"article_{idx}"
        entry_text = (
            f'<a href="#{anchor_name}" color="#515459">'
            f'<b><font color="#97C33D">{num}</font></b>  '
            f'<font color="#515459">{titre}</font></a>'
            f'<br/><font size="8" color="#A8A9AB">{meta}</font>'
        )
        story.append(Paragraph(entry_text, styles['TocEntry']))
        story.append(Spacer(1, 2*mm))

    story.append(PageBreak())

    # Articles
    for idx, art in enumerate(articles):
        anchor_name = f"article_{idx}"
        titre = art.get('titre', 'Sans titre')
        media = art.get('media', '').upper()
        date_fr = format_date_fr(art.get('date_publication', ''))
        auteur = art.get('auteur', '')
        keywords = art.get('mots_cles', [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(',')]
        texte = art.get('texte_integral', '')
        url_source = art.get('url_source', '')

        story.append(Paragraph(f'<a name="{anchor_name}"/>', styles['ArticleMedia']))
        story.append(Paragraph(media, styles['ArticleMedia']))
        story.append(Paragraph(titre, styles['ArticleTitle']))

        meta_line = date_fr
        if auteur:
            meta_line += f" — {auteur}"
        chaine = art.get('chaine', '')
        emission = art.get('emission', '')
        if chaine:
            meta_line += f" — {chaine}"
        if emission:
            meta_line += f" — {emission}"
        story.append(Paragraph(meta_line, styles['ArticleMeta']))

        # Bouton cliquable vers la source
        if url_source:
            type_contenu = art.get('type_contenu', 'article')
            if type_contenu == 'audio':
                btn_label = "Écouter l'émission"
            elif type_contenu == 'video':
                btn_label = "Voir l'émission"
            else:
                btn_label = "Lire l'article en ligne"
            btn_para = Paragraph(
                f'<a href="{url_source}" color="#FFFFFF">{btn_label}  →</a>',
                styles['ArticleButton']
            )
            btn_table = Table([[btn_para]], colWidths=[None])
            btn_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), C_VERT),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('ROUNDEDCORNERS', [3, 3, 3, 3]),
            ]))
            # Wrap in outer table to left-align (not full width)
            outer = Table([[btn_table]], colWidths=[W - 40*mm])
            outer.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(outer)

        art_line = Table([['']], colWidths=[W - 40*mm])
        art_line.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 1, C_VERT_PALE)]))
        story.append(art_line)
        story.append(Spacer(1, 3*mm))

        if keywords:
            kw_text = '  ·  '.join(keywords[:3])
            story.append(Paragraph(kw_text, styles['ArticleKeywords']))

        if texte:
            blocks = smart_split_text(texte, article_titre=titre, article_auteur=auteur)
            for block in blocks:
                text_safe = block['text'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                if block['type'] == 'subtitle':
                    story.append(Spacer(1, 4*mm))
                    story.append(Paragraph(f'<b>{text_safe}</b>', styles['ArticleBody']))
                    story.append(Spacer(1, 2*mm))
                else:
                    story.append(Paragraph(text_safe, styles['ArticleBody']))
                    story.append(Spacer(1, 2.5*mm))

        if idx < len(articles) - 1:
            story.append(PageBreak())

    doc.build(story)


# ============================================================
# ASSEMBLAGE
# ============================================================

def merge_pdfs(cover_path, content_path, output_path):
    writer = PdfWriter()
    for pdf_path in [cover_path, content_path]:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, 'wb') as f:
        writer.write(f)


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_DIR, "articles.json")
    semaine, articles = load_articles(json_path)

    if not articles:
        print("Aucun article sélectionné !")
        sys.exit(1)

    print(f"Semaine : {semaine}")
    print(f"Articles sélectionnés : {len(articles)}")
    for a in articles:
        print(f"  - {a['titre']} ({a['media']})")

    cover_path = "/tmp/veille_cover.pdf"
    content_path = "/tmp/veille_content.pdf"
    final_name = f"Veille_Presse_USH_{semaine}.pdf"
    final_path = os.path.join(REPO_DIR, final_name)

    print("\n1. Couverture...")
    draw_cover(cover_path, semaine, articles)

    print("2. Contenu (sommaire + articles)...")
    build_content(content_path, semaine, articles)

    print("3. Assemblage...")
    merge_pdfs(cover_path, content_path, final_path)

    print(f"\nPDF généré : {final_path}")

    os.remove(cover_path)
    os.remove(content_path)

    return final_path


if __name__ == '__main__':
    main()
