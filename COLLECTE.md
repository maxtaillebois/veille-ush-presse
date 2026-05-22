# COLLECTE.md — Routine Veille presse USH (Phase 1)

Instructions exécutées chaque **vendredi 09:00** par la routine distante Claude Code.
Objectif : produire `articles.json` de la semaine et le pousser sur GitHub, puis
notifier Maxime. La sélection finale et l'envoi du PDF (Phase 2) restent **manuels**
(page HTML + GitHub Actions) — ne rien envoyer ici.

Le script `veille_ush.py` fait toute la mécanique ; ton rôle d'agent est l'**analyse
éditoriale** (étape 3). Voir `DEPLOIEMENT_VEILLE_USH.md` pour le détail du système.

## Variables de routine attendues
`VUSH_TENANT`, `VUSH_CLIENT_ID`, `VUSH_CLIENT_SECRET` (app Graph « n8n Outlook »),
`VUSH_MAILBOX` (boîte à lire), `VUSH_GH_PAT` (PAT GitHub), `VUSH_RECAP_TO` (optionnel).

---

## Étape 1 — Collecte mécanique

```bash
python3 veille_ush.py collect
```

Le script : teste le réseau, lit la boîte Outlook (mails panorama des 7 derniers
jours), résout les `panoramaId`, appelle l'API LuQi, dédoublonne, applique le
**filtre 7 jours**, et écrit `raw_articles.json`.

Si la commande échoue :
- « Réseau sortant partiellement bloqué » → le sandbox bloque le sortant. Arrête-toi,
  signale-le dans le mail récap (ou par notification) — la routine ne peut pas tourner.
- « Aucun mail panorama » → aucun panorama reçu cette semaine. Envoie un récap court
  le signalant, puis arrête-toi.

## Étape 2 — Lire `raw_articles.json`

Lis le fichier. Chaque article a déjà : `media`, `titre`, `date_publication`,
`auteur`, `texte_integral` (brut), `url_source`, `type_contenu`, `themes_ush`,
`id_coupure`. Les champs `resume` et `mots_cles` sont vides — c'est ton travail.

## Étape 3 — Analyse éditoriale de CHAQUE article

Pour chaque article, produis :

1. **`resume`** — 2-3 phrases, ≤ 400 caractères. Factuel : sujet, faits clés, enjeu
   logement. Cite noms propres et chiffres. Ne commence pas par « Cet article… ».
   *Toujours rempli* — l'API ne fournit quasi jamais de résumé.
   Exception : article audiovisuel très court (< 500 car.) → le texte peut servir de
   résumé s'il fait office de synopsis.
2. **`mots_cles`** — **3 à 5** (personnalités, lois, dispositifs, thèmes). Minimum 3.
3. **`texte_integral` nettoyé** :
   - Corrige les artefacts OCR : espaces parasites dans les mots
     (« lo gement » → « logement », « de mande » → « demande »).
   - Supprime le bruit : crédits photo `©…`, titre répété en tête, nom d'auteur
     isolé en fin de texte. **Ne jamais tronquer ni résumer le texte intégral.**

## Étape 4 — Présélection de 3 articles

Mets `selectionne: true` sur **exactement 3** articles, dans cet ordre de critères :
1. **Diversité** : 3 thèmes différents.
2. **Grands médias nationaux fiables** : Le Monde, Les Echos, Libération, La Croix,
   Le Figaro, Le Parisien, L'Humanité, AFP, France Info, Public Sénat, Le Moniteur,
   Batiactu, BFM, RFI, RTL, Europe 1, France Inter/Culture. Exclure presse régionale
   obscure, sites spécialisés peu connus, blogs.
3. **Exclure l'Outre-mer et le hors-métropole** (public = communicants métropole).

Tous les autres articles restent `selectionne: false`. La présélection n'est qu'une
suggestion ; Maxime reste libre de (dé)cocher sur la page.

## Étape 5 — Écrire `enriched_articles.json`

Écris un fichier `enriched_articles.json` au format `{"articles": [...]}`, avec la
liste complète des articles enrichis (tous les champs de `raw_articles.json` +
`resume`, `mots_cles` remplis, `texte_integral` nettoyé, `selectionne` posé).

Contrôle qualité avant de continuer :
- [ ] Tous les articles ont un `resume` non vide.
- [ ] Tous ont ≥ 3 `mots_cles`.
- [ ] Aucun `texte_integral` ne contient d'espaces OCR parasites.
- [ ] Aucun ne commence par « © » / « (Photo » ni ne finit par un nom d'auteur isolé.
- [ ] Exactement 3 articles `selectionne: true`.

## Étape 6 — Build, push, notification

```bash
python3 veille_ush.py build enriched_articles.json   # -> articles.json (valide la QC)
python3 veille_ush.py push                            # commit + push GitHub
python3 veille_ush.py mail-recap                       # mail récap à Maxime
```

`build` refuse de continuer si la QC échoue (résumé vide, < 3 mots-clés). Si elle
échoue, corrige `enriched_articles.json` et relance `build`.

## Rapport de fin

Termine par un message court : nombre d'articles collectés (après filtre 7 j), les 3
présélectionnés (média + titre + justification d'une ligne), et le lien :
https://maxtaillebois.github.io/veille-ush-presse/
