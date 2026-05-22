# COLLECTE.md — Routine Veille presse USH (Phase 1)

Instructions exécutées chaque **vendredi 09:00** par la routine distante Claude Code.
Objectif : produire `articles.json` de la semaine, le pousser sur GitHub, notifier
Maxime. La sélection finale et l'envoi du PDF (Phase 2) restent **manuels** (page HTML
+ GitHub Actions) — ne rien envoyer ici.

Le script `veille_ush.py` fait toute la mécanique. Ton seul travail d'agent est
**léger** : écrire un résumé et des mots-clés par article (étape 3).

## ⚠️ EXÉCUTION SANS INTERRUPTION — À LIRE EN PREMIER

Cette routine doit aller **jusqu'au bout en une seule traite**. Tu ne rends la main
(ne termines ton tour) que lorsque `push` ET `mail-recap` ont été exécutés avec succès,
ou en cas d'échec bloquant explicite.

- Après chaque commande, **enchaîne immédiatement la suivante**. Ne considère jamais
  « collecter » ou « lire un fichier » comme une fin de tâche.
- Ne demande aucune confirmation. Personne ne lit pendant l'exécution.
- Ton travail d'analyse est volontairement **petit** (résumé + mots-clés, ~10 lignes
  de JSON par article). Tu ne réécris JAMAIS le texte intégral. Inutile donc de
  t'arrêter : 15 à 30 articles courts à résumer, ça se fait d'un trait.

## Variables de routine attendues
`VUSH_TENANT`, `VUSH_CLIENT_ID`, `VUSH_CLIENT_SECRET` (app Graph « n8n Outlook »),
`VUSH_MAILBOX` (boîte à lire), `VUSH_GH_PAT` (PAT GitHub), `VUSH_RECAP_TO` (optionnel).

---

## Étape 1 — Collecte mécanique

```bash
python3 veille_ush.py collect
```

Le script teste le réseau, lit la boîte Outlook (mails panorama des 7 derniers jours),
résout les `panoramaId`, appelle l'API LuQi, dédoublonne, applique le **filtre 7
jours**, et écrit `raw_articles.json`.

Si la commande échoue :
- « Réseau sortant partiellement bloqué » → le sandbox bloque le sortant. Arrête-toi
  et signale-le (la routine ne peut pas tourner).
- « Aucun mail panorama » → aucun panorama reçu cette semaine : c'est un cas normal,
  rien à produire. Passe directement à `mail-recap` n'est pas possible (pas
  d'`articles.json`) — termine en signalant simplement « aucun panorama cette
  semaine », sans build ni push.

## Étape 2 — Lire `raw_articles.json`

Lis le fichier. Chaque article a déjà tous ses champs : `media`, `titre`,
`date_publication`, `auteur`, `texte_integral`, `url_source`, `type_contenu`,
`themes_ush`, `id_coupure`, etc. **Tu ne modifies aucun de ces champs.**

## Étape 3 — Analyse éditoriale (résumé + mots-clés)

Pour **chaque** article, à partir de son `texte_integral`, produis seulement deux
choses :

1. **`resume`** — 2-3 phrases, ≤ 400 caractères. Factuel : sujet, faits clés, enjeu
   logement. Cite noms propres et chiffres. Ne commence pas par « Cet article… ».
   *Toujours rempli.* Exception : article audiovisuel très court (< 500 car.) → le
   texte peut servir de résumé s'il fait office de synopsis.
2. **`mots_cles`** — **3 à 5** (personnalités, lois, dispositifs, thèmes). Minimum 3.

Tu ne nettoies pas le texte et tu ne le recopies pas : le rendu (PDF / page) s'en
charge en aval.

## Étape 4 — Présélection de 3 articles

Choisis **exactement 3** articles à marquer `selectionne: true`, dans cet ordre de
critères :
1. **Diversité** : 3 thèmes différents.
2. **Grands médias nationaux fiables** : Le Monde, Les Echos, Libération, La Croix,
   Le Figaro, Le Parisien, L'Humanité, AFP, France Info, Public Sénat, Le Moniteur,
   Batiactu, BFM, RFI, RTL, Europe 1, France Inter/Culture. Exclure presse régionale
   obscure, sites spécialisés peu connus, blogs.
3. **Exclure l'Outre-mer et le hors-métropole** (public = communicants métropole).

Tous les autres : `selectionne: false`. C'est une suggestion ; Maxime reste libre de
(dé)cocher sur la page.

## Étape 5 — Écrire `analyse.json`

Écris un fichier `analyse.json` à la racine du dépôt, au format :

```json
{
  "articles": [
    {"id_coupure": "10000000071516305", "resume": "…", "mots_cles": ["…","…","…"], "selectionne": true},
    {"id_coupure": "…", "resume": "…", "mots_cles": ["…","…","…"], "selectionne": false}
  ]
}
```

Une entrée par article de `raw_articles.json`, **identifiée par son `id_coupure`**.
N'oublie aucun article : `build` échoue si un `id_coupure` manque.

## Étape 6 — Build, push, notification (enchaîne sans pause)

```bash
python3 veille_ush.py build        # fusionne raw + analyse -> articles.json (valide la QC)
python3 veille_ush.py push          # commit + push GitHub
python3 veille_ush.py mail-recap    # mail récap à Maxime
```

`build` refuse de continuer si la QC échoue (résumé vide, < 3 mots-clés, article
manquant). Dans ce cas : corrige `analyse.json` et relance `build` — ne t'arrête pas.

## Rapport de fin

Termine par un message court : nombre d'articles collectés (après filtre 7 j), les 3
présélectionnés (média + titre + justification d'une ligne), et le lien :
https://maxtaillebois.github.io/veille-ush-presse/
