#!/usr/bin/env python3
"""
Collecte hebdomadaire — Veille presse USH (Phase 1)
Routine distante Claude Code, vendredi 09:00 Europe/Paris.

Sous-commandes :
  netcheck             Teste la connectivité réseau sortante (à lancer en premier)
  collect              Outlook (Graph) -> panoramas LuQi -> raw_articles.json
  build ENRICHED.json  Valide l'analyse de l'agent -> articles.json (final)
  push                 Commit + push articles.json sur GitHub
  mail-recap           Envoie le récap par mail (Graph) à Maxime

Tout le HTTP sortant passe par `curl` (piège n°12 de la doc : requests/urllib
peuvent être bloqués par le sandbox ; curl est validé).

Variables d'environnement (définies en variables de routine, jamais dans le code) :
  VUSH_TENANT          Tenant Azure AD (app Graph « n8n Outlook »)
  VUSH_CLIENT_ID       Client ID de l'app Graph
  VUSH_CLIENT_SECRET   Client secret de l'app Graph
  VUSH_MAILBOX         Boîte à lire (ex. maxime.taillebois@procivis.fr)
  VUSH_GH_PAT          PAT GitHub (Contents: read/write sur veille-ush-presse)
  VUSH_RECAP_TO        Destinataire du mail récap (défaut = VUSH_MAILBOX)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import html as htmllib
from datetime import date, datetime, timedelta, timezone

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(REPO_DIR, "raw_articles.json")
ARTICLES_PATH = os.path.join(REPO_DIR, "articles.json")

BUDGET_ID = "a2t2p000000YwvIAAS"
GRAPH = "https://graph.microsoft.com/v1.0"
PAGE_URL = "https://maxtaillebois.github.io/veille-ush-presse/"

MOIS = {
    'janvier': '01', 'février': '02', 'fevrier': '02', 'mars': '03',
    'avril': '04', 'mai': '05', 'juin': '06', 'juillet': '07',
    'août': '08', 'aout': '08', 'septembre': '09', 'octobre': '10',
    'novembre': '11', 'décembre': '12', 'decembre': '12',
}
MOIS_FR = ['', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
           'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
THEMES_NOISE = {'boite de réception', 'boite de reception', 'corbeille',
                'themes synthese', 'thèmes synthèse'}


# --------------------------------------------------------------------------
# Utilitaires HTTP (curl)
# --------------------------------------------------------------------------

def _env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        fail(f"Variable d'environnement manquante : {name}")
    return val


def fail(msg):
    print(f"ERREUR : {msg}", file=sys.stderr)
    sys.exit(1)


def curl(args, timeout=40):
    """Lance curl, renvoie (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(["curl", "-s", "--max-time", str(timeout)] + args,
                           capture_output=True, text=True, timeout=timeout + 15)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def curl_json(args, timeout=40, ctx="requête"):
    rc, out, err = curl(args, timeout)
    if rc != 0:
        fail(f"{ctx} : curl a échoué (rc={rc}) {err}")
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        fail(f"{ctx} : réponse non-JSON — {out[:300]}")


# --------------------------------------------------------------------------
# netcheck
# --------------------------------------------------------------------------

def cmd_netcheck():
    hosts = [
        ("LuQi",   "https://luqi.fr/"),
        ("s.luqi", "http://s.luqi.fr/"),
        ("Graph",  "https://login.microsoftonline.com/"),
        ("GitHub", "https://api.github.com/"),
    ]
    ok = True
    for name, url in hosts:
        rc, out, err = curl(["-o", "/dev/null", "-w", "%{http_code}", "-I", url], timeout=20)
        reachable = rc == 0 and out.strip() not in ("", "000")
        print(f"  {'OK ' if reachable else 'KO '} {name:8s} {url}  (rc={rc} http={out.strip()})")
        ok = ok and reachable
    if not ok:
        fail("Réseau sortant partiellement bloqué — la collecte ne peut pas fonctionner.")
    print("Réseau sortant OK.")


# --------------------------------------------------------------------------
# Graph (Outlook)
# --------------------------------------------------------------------------

def graph_token():
    tenant = _env("VUSH_TENANT")
    cid = _env("VUSH_CLIENT_ID")
    secret = _env("VUSH_CLIENT_SECRET")
    data = curl_json([
        "-X", "POST",
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "--data-urlencode", f"client_id={cid}",
        "--data-urlencode", f"client_secret={secret}",
        "--data-urlencode", "scope=https://graph.microsoft.com/.default",
        "--data-urlencode", "grant_type=client_credentials",
    ], ctx="token Graph")
    if "access_token" not in data:
        fail(f"token Graph : {data.get('error_description', data)}")
    return data["access_token"]


def graph_get(token, url, params=None):
    args = ["-H", f"Authorization: Bearer {token}", "-G", url]
    for k, v in (params or {}).items():
        args += ["--data-urlencode", f"{k}={v}"]
    return curl_json(args, ctx="Graph GET")


def fetch_panorama_emails(token, mailbox, days=7):
    """Retourne les mails panorama USH des `days` derniers jours."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = graph_get(token, f"{GRAPH}/users/{mailbox}/messages", {
        "$filter": f"receivedDateTime ge {since}",
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,body",
        "$top": "200",
    })
    if "value" not in data:
        fail(f"lecture boîte {mailbox} : {data.get('error', data)}")
    mails = []
    for m in data["value"]:
        subj = (m.get("subject") or "").upper()
        if "PANORAMA" in subj and "USH" in subj:
            mails.append(m)
    return mails


# --------------------------------------------------------------------------
# LuQi
# --------------------------------------------------------------------------

def resolve_panorama_id(body_html):
    """Suit les liens de tracking s.luqi.fr du corps du mail jusqu'à un panoramaId."""
    body = htmllib.unescape(body_html or "")
    links = re.findall(r'https?://s\.luqi\.fr/ls/click[^"\'\s<>]+', body)
    seen = []
    for link in links:
        if link in seen:
            continue
        seen.append(link)
        _, out, _ = curl(["-I", "-L", "-o", "/dev/null", "-w", "%{url_effective}", link],
                         timeout=30)
        m = re.search(r'/panorama/(\d+)', out)
        if m:
            return m.group(1)
        if len(seen) >= 6:
            break
    return None


def fetch_panorama(panorama_id):
    url = (f"https://luqi.fr/sim-server/diffusion/budget/{BUDGET_ID}"
           f"/panoramas/{panorama_id}?isLatest=true")
    return curl_json([url], ctx=f"API LuQi panorama {panorama_id}")


def parse_display_date(raw):
    """Parse displayDate LuQi (presse '03 avril 2026' ou AV '01/04/26 à 14:34')."""
    if not raw:
        return ""
    raw = raw.strip()
    m = re.match(r'(\d{2})/(\d{2})/(\d{2})\s+à\s+\d{2}:\d{2}', raw)
    if m:
        return f"20{m.group(3)}-{m.group(2)}-{m.group(1)}"
    txt = raw.lower().replace('1er', '1')
    m = re.search(r'(\d{1,2})\s+([a-zà-ÿ]+)\s+(\d{4})', txt)
    if m:
        mois = MOIS.get(m.group(2))
        if mois:
            return f"{m.group(3)}-{mois}-{int(m.group(1)):02d}"
    return ""


def type_contenu(media_cat):
    cat = (media_cat or "").upper()
    if cat == "RADIO":
        return "audio"
    if cat in ("TV", "TELE", "TÉLÉ"):
        return "video"
    return "article"


def map_themes(theme_ids, themes_related):
    libelles = {t.get('id'): t.get('libelle', '') for t in (themes_related or [])}
    out = []
    for tid in (theme_ids or []):
        lib = libelles.get(tid, '')
        if lib and lib.lower() not in THEMES_NOISE:
            out.append(lib)
    return out


def rm_to_article(rm, panorama_id, themes_related):
    auteurs = rm.get('auteurs') or []
    auteur = ''
    if auteurs and isinstance(auteurs[0], dict):
        auteur = auteurs[0].get('nom_complet', '') or ''
    art_id = str(rm.get('id') or rm.get('idCoupure') or '')
    return {
        "semaine": "",
        "media": rm.get('support', '') or '',
        "titre": rm.get('titre', '') or '',
        "date_publication": parse_display_date(rm.get('displayDate', '')),
        "auteur": auteur,
        "resume": rm.get('resume', '') or '',
        "mots_cles": [],
        "texte_integral": rm.get('texte', '') or '',
        "selectionne": False,
        "url_source": (f"https://luqi.fr/luqiLatest/diffusion/budget/{BUDGET_ID}"
                       f"/panorama/{panorama_id}?idRm={art_id}"),
        "type_contenu": type_contenu(rm.get('media', '')),
        "chaine": rm.get('chaine', '') or '',
        "emission": rm.get('emission', '') or '',
        "themes_ush": map_themes(rm.get('themes'), themes_related),
        "media_type": (rm.get('media', '') or '').upper(),
        "id_coupure": art_id,
    }


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------

def cmd_collect():
    mailbox = _env("VUSH_MAILBOX")
    print("1/5  Connectivité réseau...")
    cmd_netcheck()

    print(f"2/5  Lecture de la boîte {mailbox} (7 derniers jours)...")
    token = graph_token()
    mails = fetch_panorama_emails(token, mailbox, days=7)
    print(f"     {len(mails)} mail(s) panorama trouvé(s).")
    if not mails:
        fail("Aucun mail panorama USH sur les 7 derniers jours.")

    print("3/5  Résolution des panoramaId...")
    panorama_ids = []
    for m in mails:
        body = (m.get('body') or {}).get('content', '')
        pid = resolve_panorama_id(body)
        recu = (m.get('receivedDateTime') or '')[:10]
        if pid and pid not in panorama_ids:
            panorama_ids.append(pid)
            print(f"     [{recu}] panoramaId = {pid}")
        elif pid:
            print(f"     [{recu}] doublon panoramaId {pid} — ignoré")
        else:
            print(f"     [{recu}] AUCUN panoramaId résolu — mail ignoré")
    if not panorama_ids:
        fail("Aucun panoramaId résolu.")

    print(f"4/5  Appel API LuQi ({len(panorama_ids)} panorama(s))...")
    articles = []
    for pid in panorama_ids:
        data = fetch_panorama(pid)
        rms = data.get('rms') or []
        themes_related = data.get('themesRelated') or []
        print(f"     panorama {pid} : {len(rms)} article(s)")
        for rm in rms:
            articles.append(rm_to_article(rm, pid, themes_related))

    # Dédoublonnage par id_coupure
    seen, dedup = set(), []
    for a in articles:
        key = a['id_coupure'] or a['titre']
        if key in seen:
            continue
        seen.add(key)
        dedup.append(a)

    # Filtre 7 jours obligatoire (doc §5 / piège n°18)
    limite = (date.today() - timedelta(days=7)).isoformat()
    before = len(dedup)
    dedup = [a for a in dedup if a['date_publication'] and a['date_publication'] >= limite]
    dedup.sort(key=lambda a: a['date_publication'], reverse=True)
    print(f"5/5  {before} article(s) dédoublonné(s) -> {len(dedup)} après filtre 7 jours.")
    if not dedup:
        fail("Aucun article dans la fenêtre des 7 jours.")

    with open(RAW_PATH, 'w', encoding='utf-8') as f:
        json.dump({"articles": dedup}, f, ensure_ascii=False, indent=2)
    print(f"\nÉcrit : {RAW_PATH}  ({len(dedup)} articles bruts)")
    print("-> Étape suivante : analyse éditoriale par l'agent (voir COLLECTE.md §3).")
    for a in dedup:
        print(f"   · [{a['date_publication']}] {a['media']} — {a['titre'][:70]}")


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def cmd_build(enriched_path):
    if not os.path.exists(enriched_path):
        fail(f"Fichier introuvable : {enriched_path}")
    with open(enriched_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    articles = data.get('articles') or []
    if not articles:
        fail("Le fichier enrichi ne contient aucun article.")

    iso = date.today().isocalendar()
    semaine = f"S{iso[1]}-{iso[0]}"

    errors = []
    for i, a in enumerate(articles, 1):
        a['semaine'] = semaine
        if not (a.get('resume') or '').strip():
            errors.append(f"article {i} ({a.get('titre','?')[:40]}) : résumé vide")
        mc = a.get('mots_cles') or []
        if len(mc) < 3:
            errors.append(f"article {i} ({a.get('titre','?')[:40]}) : {len(mc)} mot(s)-clé(s) (< 3)")
        if not (a.get('texte_integral') or '').strip():
            errors.append(f"article {i} ({a.get('titre','?')[:40]}) : texte intégral vide")
        a['selectionne'] = bool(a.get('selectionne', False))
    if errors:
        for e in errors:
            print(f"  CONTRÔLE QUALITÉ KO : {e}", file=sys.stderr)
        fail(f"{len(errors)} problème(s) de contrôle qualité — corriger {enriched_path}.")

    articles.sort(key=lambda a: a.get('date_publication', ''), reverse=True)
    nb_sel = sum(1 for a in articles if a['selectionne'])
    if nb_sel != 3:
        print(f"  ATTENTION : {nb_sel} article(s) présélectionné(s) (attendu : 3).")

    with open(ARTICLES_PATH, 'w', encoding='utf-8') as f:
        json.dump({
            "semaine": semaine,
            "date_generation": date.today().isoformat(),
            "articles": articles,
        }, f, ensure_ascii=False, indent=2)
    print(f"articles.json écrit — {semaine}, {len(articles)} articles, {nb_sel} présélectionné(s).")


# --------------------------------------------------------------------------
# push
# --------------------------------------------------------------------------

def _git(args, check=True):
    p = subprocess.run(["git", "-C", REPO_DIR] + args, capture_output=True, text=True)
    if check and p.returncode != 0:
        fail(f"git {' '.join(args)} : {p.stderr.strip()}")
    return p


def cmd_push():
    pat = _env("VUSH_GH_PAT")
    if not os.path.exists(ARTICLES_PATH):
        fail("articles.json absent — lancer `build` avant `push`.")
    iso = date.today().isocalendar()
    semaine = f"S{iso[1]}-{iso[0]}"

    _git(["config", "user.name", "veille-ush-bot"])
    _git(["config", "user.email", "veille-ush-bot@users.noreply.github.com"])
    remote = f"https://maxtaillebois:{pat}@github.com/maxtaillebois/veille-ush-presse.git"
    _git(["remote", "set-url", "origin", remote])

    _git(["add", "articles.json"])
    status = _git(["status", "--porcelain", "articles.json"]).stdout.strip()
    if not status:
        print("articles.json inchangé — rien à pousser.")
        return
    _git(["commit", "-m", f"Veille presse USH — {semaine}"])
    _git(["pull", "--rebase", "origin", "main"])
    _git(["push", "origin", "main"])
    print(f"articles.json poussé sur GitHub ({semaine}). Page : {PAGE_URL}")


# --------------------------------------------------------------------------
# mail-recap
# --------------------------------------------------------------------------

def _fmt_date(iso_str):
    try:
        d = datetime.strptime(iso_str, '%Y-%m-%d')
        return f"{d.day} {MOIS_FR[d.month]} {d.year}"
    except Exception:
        return iso_str


def cmd_mail_recap():
    mailbox = _env("VUSH_MAILBOX")
    recap_to = os.environ.get("VUSH_RECAP_TO") or mailbox
    if not os.path.exists(ARTICLES_PATH):
        fail("articles.json absent — lancer `build` avant `mail-recap`.")
    with open(ARTICLES_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    articles = data.get('articles') or []
    semaine = data.get('semaine', 'S??')
    preselect = [a for a in articles if a.get('selectionne')]

    rows = []
    for a in preselect:
        rows.append(
            f'<li style="margin:6px 0;"><strong>{htmllib.escape(a.get("media",""))}</strong> | '
            f'<em>{htmllib.escape(a.get("titre",""))}</em> | '
            f'{_fmt_date(a.get("date_publication",""))}</li>')
    body = (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#1a1a1a;max-width:600px;">'
        '<p>Bonjour,</p>'
        f'<p>La collecte de la veille presse USH <strong>{semaine}</strong> est terminée : '
        f'<strong>{len(articles)}</strong> article(s) collecté(s), '
        f'<strong>{len(preselect)}</strong> présélectionné(s).</p>'
        '<p>Présélection automatique :</p>'
        f'<ul style="padding-left:20px;">{"".join(rows) if rows else "<li>aucune</li>"}</ul>'
        f'<p>Sélection finale et envoi sur la page : <a href="{PAGE_URL}">{PAGE_URL}</a></p>'
        '<p style="color:#888;font-size:12px;">Message automatique — routine Veille presse USH.</p>'
        '</div>')

    token = graph_token()
    payload = {
        "message": {
            "subject": f"Veille presse USH {semaine} — collecte terminée",
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": [{"emailAddress": {"address": recap_to}}],
        },
        "saveToSentItems": True,
    }
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as tf:
        json.dump(payload, tf)
        tmp = tf.name
    try:
        rc, out, err = curl([
            "-X", "POST", f"{GRAPH}/users/{mailbox}/sendMail",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
            "-w", "%{http_code}", "-o", "/dev/null",
            "--data", f"@{tmp}",
        ], timeout=40)
    finally:
        os.unlink(tmp)
    if rc != 0 or out.strip() not in ("202", "200"):
        fail(f"envoi du mail récap : http={out.strip()} {err}")
    print(f"Mail récap envoyé à {recap_to}.")


# --------------------------------------------------------------------------

USAGE = "Usage : veille_ush.py [netcheck|collect|build ENRICHED.json|push|mail-recap]"


def main():
    if len(sys.argv) < 2:
        fail(USAGE)
    cmd = sys.argv[1]
    if cmd == "netcheck":
        cmd_netcheck()
    elif cmd == "collect":
        cmd_collect()
    elif cmd == "build":
        if len(sys.argv) < 3:
            fail("build : préciser le fichier enrichi. " + USAGE)
        cmd_build(sys.argv[2])
    elif cmd == "push":
        cmd_push()
    elif cmd == "mail-recap":
        cmd_mail_recap()
    else:
        fail(f"Sous-commande inconnue : {cmd}\n{USAGE}")


if __name__ == "__main__":
    main()
