# PHASE2.md — Envoi de la veille presse USH (à la demande)

Procédure exécutée par l'agent quand Maxime demande « envoie la veille presse USH ».

La **Phase 1** (collecte) est automatique chaque vendredi 09:00 — voir `COLLECTE.md`.
La **Phase 2** (choix final des articles + PDF + envoi du mail) est **manuelle** :
Maxime la déclenche en le demandant à l'agent. Il n'y a plus ni page d'envoi ni
GitHub Actions — la page web `index.html` n'est qu'un visualiseur en lecture seule.

⚠️ **Aucun secret n'est stocké dans ce dépôt.** Les identifiants Microsoft Graph
sont récupérés au moment de l'envoi via le skill `outlook-graph-api`.

## Pré-requis
- Le dépôt `maxtaillebois/veille-ush-presse` (public) cloné localement.
- Python 3 + `reportlab` + `pypdf` (`pip install reportlab pypdf`).
- Le skill `outlook-graph-api` (identifiants Graph de l'app « n8n Outlook »).

## Étape 1 — Récupérer les articles de la semaine
`articles.json` à la racine du dépôt contient les articles collectés le vendredi, avec
3 articles déjà présélectionnés (`selectionne: true`). Cloner ou mettre à jour le dépôt
pour disposer de la version courante.

## Étape 2 — Confirmer la sélection avec Maxime
Présenter les articles et la présélection des 3. Demander à Maxime lesquels envoyer
(par défaut : la présélection). Il peut en choisir d'autres et préciser l'ordre.

## Étape 3 — Appliquer la sélection dans articles.json
Mettre `selectionne: true` sur les articles retenus, `false` sur les autres. Ordonner
la liste `articles` pour que les retenus soient en premier, dans l'ordre voulu par
Maxime — c'est cet ordre qui détermine l'ordre dans le PDF.

## Étape 4 — Générer le PDF
```bash
python3 generate_pdf.py
```
Produit `Veille_Presse_USH_{semaine}.pdf` à la racine du dépôt.

## Étape 5 — Envoyer le mail
Récupérer les identifiants Graph via le skill `outlook-graph-api`, puis lancer
`send_email.py` avec ces variables d'environnement :

```bash
GRAPH_TENANT_ID=<tenant>           \
GRAPH_CLIENT_ID=<client_id>        \
GRAPH_CLIENT_SECRET=<client_secret> \
MAIL_FROM=maxime.taillebois@procivis.fr \
MAIL_TO=stephanie@papiersdesoi.fr  \
MAIL_CC=aurelie.hennetier@procivis.fr \
python3 send_email.py
```

Le mail part de la boîte pro de Maxime, PDF en pièce jointe, copie dans les Éléments
envoyés. `send_email.py` affiche un message de succès (HTTP 202 attendu).

Destinataires par défaut : TO `stephanie@papiersdesoi.fr`, CC
`aurelie.hennetier@procivis.fr`. Maxime peut les modifier au moment de la demande.

## Étape 6 — Confirmer
Annoncer à Maxime : articles envoyés, destinataire(s). La Phase 2 ne pousse rien sur
GitHub — le dépôt n'est pas modifié.
