# -*- coding: utf-8 -*-
"""
NIMM — garde anti-SSRF pour les récupérations d'URL.

Toute récupération d'une URL fournie par l'extérieur (résultat de recherche,
URL saisie par l'utilisateur, URL ingérée depuis un document ou une page web)
doit passer par ce module. Il refuse les cibles internes :

  - loopback (127.0.0.0/8, ::1) ;
  - adresses privées (10/8, 172.16/12, 192.168/16, fc00::/7) ;
  - link-local et métadonnées cloud (169.254.0.0/16, dont 169.254.169.254) ;
  - réservées / multicast / non spécifiées ;
  - plage Tailscale CGNAT (100.64.0.0/10) : empêche un pivot vers les appareils
    des proches sur le tailnet, ou vers les routes internes de NIMM exposées via
    tailscale serve.

Le contrôle est fait sur les IP RÉSOLUES (pas seulement sur le nom d'hôte), et
re-vérifié à CHAQUE saut de redirection (via safe_request) — sinon un nom public
qui résout en IP interne, ou une redirection 302 vers http://169.254.169.254,
contournerait le filtre.
"""
import ipaddress
import socket
from urllib.parse import urlparse, urljoin

import requests

# Plages refusées en plus de ce que python juge déjà « non global ».
# 100.64.0.0/10 (CGNAT) couvre le tailnet Tailscale.
_EXTRA_DENY = [ipaddress.ip_network("100.64.0.0/10")]

MAX_REDIRECTS = 5


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # non parsable → on refuse par prudence
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        return True
    # is_global est faux pour les ranges spéciaux ; on s'appuie dessus aussi.
    if not ip.is_global:
        return True
    for net in _EXTRA_DENY:
        if ip in net:
            return True
    return False


def is_public_url(url: str) -> bool:
    """True seulement si l'URL est http(s) et que TOUTES ses IP résolues sont
    publiques (ni loopback, ni privée, ni link-local, ni tailnet)."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    # Résolution de TOUTES les adresses (IPv4 + IPv6) ; refus si l'une est interne.
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        ip_str = info[4][0]
        if _ip_is_blocked(ip_str):
            return False
    return True


def assert_public_url(url: str) -> None:
    """Lève PermissionError si l'URL vise une cible interne."""
    if not is_public_url(url):
        raise PermissionError(
            f"NIMM a bloqué une récupération vers une cible interne ou non autorisée : {url}")


def safe_request(method: str, url: str, *, max_redirects: int = MAX_REDIRECTS, **kwargs):
    """requests.request avec validation anti-SSRF à chaque saut de redirection.

    Les redirections sont suivies manuellement et chaque cible est re-vérifiée
    AVANT d'être contactée. `allow_redirects` éventuellement fourni est ignoré.
    """
    kwargs.pop("allow_redirects", None)
    current = url
    for _ in range(max_redirects + 1):
        assert_public_url(current)
        resp = requests.request(method, current, allow_redirects=False, **kwargs)
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("Location")
            if not location:
                return resp
            current = urljoin(current, location)
            try:
                resp.close()
            except Exception:
                pass
            continue
        return resp
    raise PermissionError(f"NIMM a bloqué une chaîne de redirections trop longue depuis : {url}")
