# Idée — Donner la vision au mode Live, sans perdre en intelligence

> Note du 21/11/2026, issue d'une discussion entre Laurent et Claude. Rien n'est codé : c'est une piste à reprendre, à discuter et à valider avant d'écrire une ligne.

## Le constat de départ

Le mode Live est excellent pour les questions rapides, mais son raisonnement reste limité. C'est le même ressenti qu'avec Gemini Live dans l'appli de Google : réponses correctes, mais moyennes. C'est normal, les modèles Live (chez NIMM : `gemini-3.1-flash-live-preview`, voir `MODELE_DEFAUT` dans `modules/live.py`) sont optimisés pour répondre vite, pas pour réfléchir longtemps.

Donner la vision directement à ce modèle reviendrait à lui confier une tâche exigeante avec ses limites actuelles.

## Le principe retenu : le Live délègue

Le modèle Live joue le standardiste : rapide, à l'aise pour la conversation. Quand une question demande de vraiment regarder ou de vraiment réfléchir, il passe la main à un modèle plus solide, attend la réponse, puis la restitue à l'oral.

Le mécanisme existe déjà dans NIMM : en Live, les outils s'exécutent hors de la boucle audio, sont annoncés en français, et le visage passe à l'état `reflexion` pendant l'attente.

Deux outils à créer :

1. **Regarder la photo.** Laurent prend une photo depuis le panneau Live (bouton dédié). L'image est analysée par le modèle de vision déjà configuré dans NIMM (`call_vision` dans `core/engine.py`, choix du fournisseur via `provider_routing` → `vision`). Le Live lit le résultat avec sa voix.
   - L'outil existant `describe_image` (`core/hub.py`) ne convient pas tel quel : il n'accepte qu'une URL publique (garde anti-SSRF `assert_public_url`). Il faut un outil distinct qui reçoit l'image prise dans le panneau.
2. **Réfléchir à fond.** Pour une question qui le mérite, le Live transmet la question au modèle du chat classique (mémoire et raisonnement complets), puis en résume la réponse à l'oral.

Bénéfice : la réactivité pour la conversation courante, la profondeur seulement quand c'est utile, au prix de quelques secondes d'attente visibles (le visage « réfléchit »).

## Photo à la demande plutôt que caméra en continu

L'API Live de Gemini accepte bien des images en entrée, mais une par seconde au maximum : inadaptée à ce qui bouge vite. Surtout, ce serait le petit modèle Live qui regarde.

La photo à la demande est préférée pour commencer :

- vie privée : NIMM est un outil familial, rien n'est filmé en permanence ;
- données mobiles : beaucoup plus léger sur la route ;
- coût : une image au lieu d'un flux ;
- compatibilité : fonctionne aussi en mode chaîne (Whisper + modèle du chat), pas seulement avec Gemini.

Le flux continu reste possible plus tard, si un vrai besoin apparaît.

## Accessibilité

Pour une personne qui navigue au lecteur d'écran, « décris-moi ce que je tiens » en pleine conversation est un usage de premier ordre. Le bouton photo doit avoir un nom accessible clair, et le résultat doit aussi apparaître dans la transcription (`#live-transcript`), pas seulement à l'oral.

## Idée liée : le visage qui s'éloigne pendant l'attente

Pendant qu'il « fait le secrétaire » (état `reflexion`), le visage recule en silhouette vers le fond de son cadre, puis revient au premier plan quand il a l'information. L'état `reflexion` est déjà déclenché aux bons moments : appel d'un outil en Gemini, attente de la réponse en mode chaîne.

Version voulue par Laurent, maquettée le 21/11 (logique vérifiée dans Chrome, sans erreur) : le visage se retourne (vue de dos), rapetisse en s'éloignant, devient un petit personnage en pied (même tête à ailettes) qui marche jusqu'à un classeur au fond, ouvre un tiroir et fouille, puis revient vers l'avant et redevient le visage qui parle. Règles retenues :

- rien ne se passe si la réflexion dure moins d'environ une demi-seconde (pas d'aller-retour nerveux) ;
- si la réponse arrive en chemin, le personnage fait demi-tour aussitôt et revient en parlant ;
- avec « réduire les animations », pas de scène : silhouette figée au fond, puis retour d'un coup ;
- à faire pour la vraie version : de vrais sprites dessinés (marche, demi-tour, fouille), et une transition tête vers personnage plus propre ;
- piste : le décor change selon l'outil appelé (classeur pour la mémoire, écran ou antenne pour le web, fenêtre pour la météo), via les noms de `LIVE_NOMS_OUTILS`.

## Points à trancher au moment de s'y mettre

- Quel modèle reçoit la délégation « réfléchir à fond » : celui du fil courant, ou un réglage dédié ?
- Durée d'attente acceptable à l'oral, et ce que dit NIMM pendant ce temps.
- Taille et compression de la photo avant envoi (qualité suffisante, poids raisonnable en 4G).
- La photo est-elle conservée ? Par défaut : non, comme le reste du Live (rien n'est enregistré sans un oui).

## Premier pas

Lire comment le Live déclare ses outils (`modules/live.py`, `LIVE_NOMS_OUTILS` dans `frontend/app.js`), puis discuter de l'architecture avant tout bloc.
