/*
 * Relais Veille presse USH — Cloudflare Worker.
 *
 * Rôle : recevoir la sélection envoyée par index.html (page publique, sans secret)
 * et pousser `selection.json` sur le dépôt GitHub, ce qui déclenche le workflow
 * GitHub Actions (génération du PDF + envoi du mail via la boîte pro).
 *
 * Le token GitHub est stocké comme SECRET du Worker (variable GH_TOKEN) — il ne
 * quitte jamais le serveur et n'apparaît jamais dans le navigateur.
 *
 * Déploiement : dashboard Cloudflare → Workers → Create → coller ce code →
 * Settings → Variables → ajouter GH_TOKEN (type "Secret") = un PAT GitHub
 * (fine-grained, Contents: Read and write sur le dépôt veille-ush-presse).
 */

const REPO = 'maxtaillebois/veille-ush-presse';
const ALLOWED_ORIGIN = 'https://maxtaillebois.github.io';

export default {
  async fetch(request, env) {
    const cors = {
      'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: cors });
    }
    if (request.method !== 'POST') {
      return new Response('Method Not Allowed', { status: 405, headers: cors });
    }
    // N'accepter que les requêtes venant de la page de veille.
    if (request.headers.get('Origin') !== ALLOWED_ORIGIN) {
      return new Response('Origine non autorisée', { status: 403, headers: cors });
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return new Response('JSON invalide', { status: 400, headers: cors });
    }

    const titles = payload.selected_titles;
    if (!Array.isArray(titles) || titles.length === 0) {
      return new Response('Aucun article sélectionné', { status: 400, headers: cors });
    }

    const apiUrl = `https://api.github.com/repos/${REPO}/contents/selection.json`;
    const ghHeaders = {
      'Authorization': `token ${env.GH_TOKEN}`,
      'User-Agent': 'veille-ush-relay',
      'Accept': 'application/vnd.github+json',
    };

    // Récupérer le sha si selection.json existe déjà (sinon création).
    let sha = null;
    const getResp = await fetch(apiUrl, { headers: ghHeaders });
    if (getResp.ok) {
      sha = (await getResp.json()).sha;
    }

    const content = JSON.stringify(payload, null, 2);
    const body = {
      message: `Sélection veille presse — ${titles.length} article(s)`,
      content: btoa(unescape(encodeURIComponent(content))),
    };
    if (sha) body.sha = sha;

    const putResp = await fetch(apiUrl, {
      method: 'PUT',
      headers: { ...ghHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!putResp.ok) {
      const err = await putResp.text();
      return new Response('Erreur GitHub : ' + err.slice(0, 300), { status: 502, headers: cors });
    }

    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { ...cors, 'Content-Type': 'application/json' },
    });
  },
};
