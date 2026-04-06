#!/usr/bin/env python3
"""
Envoi email - Veille Presse USH
Envoie le PDF en pièce jointe via Gmail SMTP.
Utilisé par GitHub Actions après génération du PDF.

Variables d'environnement requises :
  GMAIL_USER     : adresse Gmail (ex: maxime.taillebois@gmail.com)
  GMAIL_APP_PWD  : mot de passe d'application Gmail (16 caractères)
  MAIL_TO        : destinataire principal
  MAIL_CC        : destinataires en copie (séparés par des virgules)
"""

import os, sys, glob, json, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

MOIS_FR = [
    '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
]


def format_date_fr(date_str):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return f"{d.day} {MOIS_FR[d.month]} {d.year}"
    except:
        return date_str


def format_date_short(date_str):
    """Formate une date en 'jour mois année' (ex: 1 avril 2026)."""
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return f"{d.day} {MOIS_FR[d.month]} {d.year}"
    except:
        return date_str


def clean_media_name(media):
    """Nettoie le nom du média : supprime www./http(s)://, puis title case sauf si URL."""
    if not media:
        return ''
    import re
    name = media.strip()
    # Détecter si c'est une URL (contient un point suivi d'une extension type .fr, .com, .org…)
    is_url = bool(re.search(r'^(https?://|www\.)', name, flags=re.IGNORECASE)) or \
             bool(re.search(r'\.\w{2,4}$', name))  # se termine par .fr, .com, etc.
    # Supprimer www. et http(s)://
    name = re.sub(r'^https?://', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^www\.', '', name, flags=re.IGNORECASE)
    # Si c'est une URL, tout en minuscules
    if is_url:
        return name.lower()
    # Sinon, title case avec mots courts en minuscules
    words = name.lower().split()
    small_words = {'de', 'du', 'le', 'la', 'les', 'des', 'et', 'en', 'au', 'aux', 'à'}
    result = []
    for i, w in enumerate(words):
        if i == 0 or w not in small_words:
            result.append(w.capitalize())
        else:
            result.append(w)
    return ' '.join(result)


def build_email_body(articles):
    """Construit le corps HTML de l'email — format basique, noir."""
    lines = []
    lines.append('<div style="font-family: Helvetica, Arial, sans-serif; color: #000000; max-width: 600px;">')
    lines.append('<p>Bonjour,</p>')
    lines.append('<p>Voici la sélection de la veille presse USH de cette semaine :</p>')
    lines.append('<ul style="padding-left: 20px;">')

    for art in articles:
        titre = art.get('titre', 'Sans titre')
        media = clean_media_name(art.get('media', ''))
        date_pub = format_date_short(art.get('date_publication', ''))
        lines.append(
            f'<li style="margin: 6px 0;">'
            f'<strong>{media}</strong> | <em>{titre}</em> | {date_pub}'
            f'</li>'
        )

    lines.append('</ul>')
    lines.append('<p>Le PDF complet est en pièce jointe.</p>')
    lines.append('</div>')
    return '\n'.join(lines)


def main():
    # Trouver le PDF généré
    pdfs = glob.glob(os.path.join(REPO_DIR, "Veille_Presse_USH_*.pdf"))
    if not pdfs:
        print("ERREUR: Aucun PDF trouvé !")
        sys.exit(1)
    pdf_path = pdfs[0]
    pdf_name = os.path.basename(pdf_path)
    print(f"PDF à envoyer : {pdf_name}")

    # Charger les articles pour le corps du mail
    json_path = os.path.join(REPO_DIR, "articles.json")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    semaine = data.get('semaine', 'S??')
    all_arts = data.get('articles', [])
    selected = [a for a in all_arts if a.get('selectionne', False)]
    if not selected:
        selected = all_arts

    # Config SMTP
    gmail_user = os.environ.get('GMAIL_USER', '')
    gmail_pwd  = os.environ.get('GMAIL_APP_PWD', '')
    mail_to    = os.environ.get('MAIL_TO', '')
    mail_cc    = os.environ.get('MAIL_CC', '')

    if not all([gmail_user, gmail_pwd, mail_to]):
        print("ERREUR: Variables GMAIL_USER, GMAIL_APP_PWD et MAIL_TO requises")
        sys.exit(1)

    # Construire le message
    msg = MIMEMultipart()
    msg['From'] = gmail_user
    msg['To'] = mail_to
    if mail_cc:
        msg['Cc'] = mail_cc
    msg['Subject'] = f"Veille presse USH — {semaine}"

    # Corps HTML
    body_html = build_email_body(selected)
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    # Pièce jointe PDF
    with open(pdf_path, 'rb') as f:
        pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
        pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_name)
        msg.attach(pdf_attachment)

    # Envoi
    recipients = [mail_to]
    if mail_cc:
        recipients += [addr.strip() for addr in mail_cc.split(',')]

    print(f"Envoi à : {mail_to}")
    if mail_cc:
        print(f"CC : {mail_cc}")

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(gmail_user, gmail_pwd)
        server.sendmail(gmail_user, recipients, msg.as_string())

    print("Email envoyé avec succès !")


if __name__ == '__main__':
    main()
