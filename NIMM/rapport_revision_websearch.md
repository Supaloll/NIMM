# Rapport de révision — `modules/websearch.py` (NIMM)

## Contexte

Révision du module de recherche web (Brave Search API). Objectif : fiabiliser le
suivi du quota, améliorer la pertinence des résultats en français, nettoyer la
sortie texte et renforcer la confidentialité des requêtes — sans modifier
l'interface publique du module.

**Compatibilité : remplacement direct.** La signature `search(query, max_results=5)`,
la lecture de la clé via `get_setting('api_keys')` et l'appel `log_cost(...)` sont
conservés à l'identique. Aucun autre fichier de NIMM n'a besoin d'être modifié.

## Les modifications

### 1. Le quota n'est plus décompté en cas d'échec
Auparavant, `log_cost('brave', ...)` était appelé à chaque recherche, y compris
quand l'appel avait échoué (erreur réseau, clé invalide, etc.). Désormais
`_brave_search` renvoie un couple `(succès, texte)`, et le quota n'est incrémenté
que lorsque l'appel API a réellement abouti.

*Précision importante :* une recherche qui aboutit mais ne renvoie aucun résultat
est tout de même comptée comme succès — c'est le comportement correct, car cet
appel a bien consommé une unité du quota Brave. Seuls les vrais échecs (transport,
401, 429, etc.) ne sont plus comptés.

### 2. Requête tronquée à 380 caractères au lieu de 120
L'API Brave accepte jusqu'à 400 caractères et 50 mots. L'ancienne limite de 120
caractères amputait les recherches un peu longues. Limite portée à 380 (marge de
sécurité).

### 3. Langue et pays configurables (français par défaut)
Ajout des paramètres `country`, `search_lang` et `ui_lang`. Le français reste
appliqué par défaut (FR / fr / fr-FR), mais la langue est désormais ajustable de
deux façons :
- **côté code** : passer `lang="en"` (ou un autre code) à `search()` ;
- **côté requête** : ajouter une directive `lang:en` n'importe où dans la requête
  tapée (ex. « actualités IA lang:en ») ; elle est extraite puis retirée avant
  l'envoi. Pratique pour un changement ponctuel sans modifier l'appel.

Priorité : paramètre `lang` > directive en ligne > français par défaut.
Un jeu de préréglages (`_LANG_PRESETS`) couvre fr, en, gb, es, de, it, pt et
s'étend en une ligne. `lang:any` (ou `all` / `*`) lance une recherche sans filtre
de langue (mondiale) ; un code inconnu filtre au moins sur la langue de contenu.

### 4. Nettoyage de la sortie texte
Les descriptions Brave contiennent souvent des entités HTML (`&amp;`, `&#39;`,
`&quot;`…) même avec `text_decorations` désactivé. Application de `html.unescape()`
sur les titres et descriptions, plus normalisation des espaces multiples. La sortie
est ainsi propre, ce qui est essentiel pour une lecture sur afficheur braille et
synthèse vocale.

### 5. Messages d'erreur différenciés
L'unique `except Exception` qui renvoyait le message technique brut est remplacé
par des cas explicites et actionnables :
- délai dépassé (timeout réseau) ;
- erreur de connexion ;
- HTTP 401 : clé invalide ou expirée ;
- HTTP 429 : quota ou débit dépassé (rappel : 1 req/s, 2 000/mois) ;
- HTTP 422 : paramètres refusés ;
- JSON illisible.

### 6. Confidentialité de la journalisation
L'ancien `print` écrivait le contenu complet de chaque requête sur la sortie
standard. Un indicateur `_LOG_QUERIES` (à `False` par défaut) a été ajouté : par
défaut, le journal n'indique plus que la **longueur** de la requête, jamais son
contenu. Cela protège les recherches sensibles. Passer l'indicateur à `True`
uniquement pour du débogage local.

### 7. Filtre de préfixe « google » sécurisé
Le motif retirait « google » en tête de toute requête, transformant par exemple
« google amende RGPD » en « amende RGPD » (perte du sujet réel). Le motif ne
retire désormais que les formulations de commande « google moi » / « google-moi ».

### 8. Modernisation asyncio
`asyncio.get_event_loop()`, déconseillé à l'intérieur d'une coroutine, est remplacé
par `asyncio.get_running_loop()`. Changement d'une ligne, sans effet de bord.

### 9. Vérification des liens retournés
Brave renvoie parfois des URL périmées (pages disparues). Chaque lien est
désormais testé avant d'être renvoyé :
- requête `HEAD` (légère), avec repli en `GET` si le serveur refuse le `HEAD` ;
- en-tête `User-Agent` de navigateur, car beaucoup de sites refusent les requêtes
  anonymes ;
- vérifications menées **en parallèle** (jusqu'à 8 simultanées, délai de 4 s par
  lien) pour limiter la latence ajoutée.

Règle prudente : seuls les liens clairement disparus (HTTP 404 / 410) sont
écartés. Les cas ambigus (403, 405, délai dépassé, 5xx…) sont conservés mais
signalés « (lien non vérifié) », afin de ne pas supprimer à tort des sites
valides qui bloquent les robots. Pour compenser les liens écartés, on demande à
Brave quelques résultats de plus — sans coût supplémentaire (toujours une seule
requête Brave).

Réglable : `VERIFY_URLS` (interrupteur global, activé par défaut), `VERIFY_TIMEOUT`,
`VERIFY_WORKERS`, et un paramètre `verify=False` par appel pour désactiver
ponctuellement. *Limite à connaître :* cette vérification confirme qu'une page
répond, pas qu'elle contient toujours l'information attendue (certains sites
renvoient un code 200 sur une fausse page d'erreur).

### 10. Extraction des paragraphes pertinents (enrichissement)
Nouveauté la plus visible : au lieu de se contenter du titre et de la description
renvoyés par Brave, le module récupère désormais chaque page et en extrait les
paragraphes qui correspondent le mieux aux mots-clés de la requête.

Fonctionnement :
- récupération en `requests` + analyse avec BeautifulSoup (brique reprise du
  module `scrap4me`, sans le moteur Selenium, trop lourd ici) ;
- nettoyage : suppression des zones non informatives (scripts, styles,
  navigation, en-têtes, pieds de page, formulaires), décodage des entités,
  compactage des espaces ;
- découpage en paragraphes (`<p>`, complété par les `<li>` sur les pages très
  structurées), avec longueur minimale pour écarter les fragments de menu ;
- notation de chaque paragraphe selon les mots-clés de la requête (comparaison
  insensible aux accents, mots vides ignorés) : nombre de mots-clés distincts
  présents, puis nombre total d'occurrences ;
- renvoi des deux meilleurs paragraphes par page (réglable), chacun tronqué à
  600 caractères.

Comme la page entière est téléchargée, cette étape **valide aussi le lien** : elle
remplace le contrôle HEAD du point 9 quand elle est active. Les pages disparues
(404/410) sont écartées ; une page vivante mais sans extrait exploitable (PDF,
contenu protégé…) conserve la description du moteur avec la mention
« (extrait indisponible) » ; une page non joignable est marquée
« (page non récupérée) ». Le résultat n'est jamais perdu silencieusement.

Réglages : `ENRICH_PARAGRAPHS` (interrupteur, activé par défaut), `ENRICH_TIMEOUT`,
`ENRICH_WORKERS` (pages traitées en parallèle), `ENRICH_MAX_PARAS`,
`ENRICH_MIN_LEN`, et `enrich=False` par appel.

**Dépendance** : `beautifulsoup4` (déjà utilisée par `scrap4me`).

*Points d'attention pour Laurent :*
- récupérer plusieurs pages coûte de la latence ; les pages sont traitées en
  parallèle (5 en même temps, délai de 10 s par page) ;
- `ENRICH_VERIFY_TLS` est à `False` (comme dans `scrap4me`) pour joindre davantage
  de sites aux certificats imparfaits ; on ne fait que lire des pages publiques,
  mais le passer à `True` reste possible si une vérification stricte est souhaitée ;
- sans Selenium, les pages dont le contenu est intégralement généré en JavaScript
  ne livreront pas de paragraphe (elles restent renvoyées avec leur description) ;
- l'extraction renvoie le texte qui répond, pas une garantie de pertinence absolue.

## Les choix volontairement écartés (pour rester simple)

- **Passage à `httpx` en async natif** (suppression du thread `run_in_executor`) :
  écarté. Plus « pur » mais ajoute une dépendance pour un gain négligeable sur des
  appels ponctuels. `requests` est conservé.
- **Limiteur de débit interne (1 req/s)** : écarté tant que NIMM ne lance pas de
  rafales de recherches. Le code gère désormais proprement le HTTP 429 si le cas
  se présente.

## Synthèse

| Point | Bénéfice |
|---|---|
| 1 | Comptage de quota exact |
| 2 | Recherches longues préservées |
| 3 | Langue configurable (fr par défaut, autres au choix, mode mondial) |
| 4 | Sortie propre (braille / lecteur d'écran) |
| 5 | Diagnostics clairs en cas d'erreur |
| 6 | Confidentialité des requêtes |
| 7 | Plus de requêtes mutilées |
| 8 | Code à jour |
| 9 | Liens morts écartés, liens douteux signalés |
| 10 | Paragraphes pertinents extraits des pages (mots-clés de la requête) |
