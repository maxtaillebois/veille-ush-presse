#!/usr/bin/env python3
"""
Envoi email - Veille Presse USH
Envoie le PDF en pièce jointe via Microsoft Graph, depuis la boîte pro Outlook.
Utilisé par GitHub Actions après génération du PDF.

Variables d'environnement requises :
  GRAPH_TENANT_ID      : tenant Azure AD (app « n8n Outlook »)
  GRAPH_CLIENT_ID      : client ID de l'app Graph
  GRAPH_CLIENT_SECRET  : client secret de l'app Graph
  MAIL_FROM            : boîte expéditrice (défaut maxime.taillebois@procivis.fr)
  MAIL_TO              : destinataire principal
  MAIL_CC              : destinataires en copie (séparés par des virgules, optionnel)
"""

import os, sys, glob, json, base64
import urllib.request, urllib.parse, urllib.error
from datetime import datetime

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_FROM = "maxime.taillebois@procivis.fr"

MOIS_FR = [
    '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
]


def format_date_short(date_str):
    """Formate une date en 'jour mois année' (ex: 1 avril 2026)."""
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return f"{d.day} {MOIS_FR[d.month]} {d.year}"
    except Exception:
        return date_str


def clean_media_name(media):
    """Nettoie le nom du média : supprime www./http(s)://, puis title case sauf si URL."""
    if not media:
        return ''
    import re
    name = media.strip()
    is_url = bool(re.search(r'^(https?://|www\.)', name, flags=re.IGNORECASE)) or \
             bool(re.search(r'\.\w{2,4}$', name))
    name = re.sub(r'^https?://', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^www\.', '', name, flags=re.IGNORECASE)
    if is_url:
        return name.lower()
    words = name.lower().split()
    small_words = {'de', 'du', 'le', 'la', 'les', 'des', 'et', 'en', 'au', 'aux', 'à'}
    result = []
    for i, w in enumerate(words):
        result.append(w.capitalize() if (i == 0 or w not in small_words) else w)
    return ' '.join(result)


def build_email_body(articles):
    """Construit le corps HTML de l'email — format basique, noir."""
    lines = ['<div style="font-family: Helvetica, Arial, sans-serif; color: #000000; max-width: 600px;">',
             '<p>Bonjour,</p>',
             '<p>Voici la sélection de la veille presse USH de cette semaine :</p>',
             '<ul style="padding-left: 20px;">']
    for art in articles:
        titre = art.get('titre', 'Sans titre')
        media = clean_media_name(art.get('media', ''))
        date_pub = format_date_short(art.get('date_publication', ''))
        lines.append(f'<li style="margin: 6px 0;"><strong>{media}</strong> | '
                     f'<em>{titre}</em> | {date_pub}</li>')
    lines += ['</ul>', '<p>Le PDF complet est en pièce jointe.</p>', '</div>']
    return '\n'.join(lines)


def graph_token(tenant, client_id, client_secret):
    """Jeton OAuth2 via le flux client credentials."""
    data = urllib.parse.urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials',
    }).encode()
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
            return json.loads(r.read())['access_token']
    except urllib.error.HTTPError as e:
        print(f"ERREUR token Graph : {e.code} {e.read().decode(errors='ignore')[:300]}")
        sys.exit(1)
    except (KeyError, json.JSONDecodeError) as e:
        print(f"ERREUR token Graph : réponse inattendue ({e})")
        sys.exit(1)


def send_via_graph(token, sender, payload):
    """POST /users/{sender}/sendMail. Renvoie le code HTTP (202 attendu)."""
    req = urllib.request.Request(
        f"{GRAPH}/users/{sender}/sendMail",
        data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"ERREUR envoi Graph : {e.code} {e.read().decode(errors='ignore')[:400]}")
        sys.exit(1)


def main():
    pdfs = glob.glob(os.path.join(REPO_DIR, "Veille_Presse_USH_*.pdf"))
    if not pdfs:
        print("ERREUR: Aucun PDF trouvé !")
        sys.exit(1)
    pdf_path = pdfs[0]
    pdf_name = os.path.basename(pdf_path)
    print(f"PDF à envoyer : {pdf_name}")

    with open(os.path.join(REPO_DIR, "articles.json"), 'r', encoding='utf-8') as f:
        data = json.load(f)
    semaine = data.get('semaine', 'S??')
    all_arts = data.get('articles', [])
    selected = [a for a in all_arts if a.get('selectionne', False)] or all_arts

    tenant        = os.environ.get('GRAPH_TENANT_ID', '')
    client_id     = os.environ.get('GRAPH_CLIENT_ID', '')
    client_secret = os.environ.get('GRAPH_CLIENT_SECRET', '')
    mail_from     = os.environ.get('MAIL_FROM', '') or DEFAULT_FROM
    mail_to       = os.environ.get('MAIL_TO', '')
    mail_cc       = os.environ.get('MAIL_CC', '')

    if not all([tenant, client_id, client_secret, mail_to]):
        print("ERREUR: GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET et MAIL_TO requis")
        sys.exit(1)

    token = graph_token(tenant, client_id, client_secret)

    with open(pdf_path, 'rb') as f:
        pdf_b64 = base64.b64encode(f.read()).decode()

    message = {
        "subject": f"Veille presse USH — {semaine}",
        "body": {"contentType": "HTML", "content": build_email_body(selected)},
        "toRecipients": [{"emailAddress": {"address": mail_to.strip()}}],
        "attachments": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": pdf_name,
            "contentType": "application/pdf",
            "contentBytes": pdf_b64,
        }],
    }
    cc_recips = [{"emailAddress": {"address": a.strip()}}
                 for a in mail_cc.split(',') if a.strip()]
    if cc_recips:
        message["ccRecipients"] = cc_recips

    status = send_via_graph(token, mail_from, {"message": message, "saveToSentItems": True})
    print(f"Email envoyé via Graph depuis {mail_from} (HTTP {status}).")
    print(f"  À : {mail_to}" + (f" | CC : {mail_cc}" if mail_cc else " | sans CC"))


if __name__ == '__main__':
    main()
