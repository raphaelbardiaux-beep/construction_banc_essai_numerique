from __future__ import annotations

import argparse
import csv
import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass, fields
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


DOSSIER_PROGRAMME = Path(__file__).resolve().parent
VERSION_PROGRAMME = "v3"


def nom_cote_csv(nom: str) -> str:
    if nom.startswith("y_"):
        return "z_" + nom[2:]
    return nom


# --- Geometrie circulaire ---

@dataclass(frozen=True)
class DeterminationHpng:
    alpha_1: float
    alpha_0: float
    effort: float
    moment: float
    h_png: float
    b_w: float


class Circulaire:
    """Profil 2D symetrique d'une conduite circulaire."""

    def __init__(self, diametre: float, nb_points: int = 720) -> None:
        if diametre <= 0.0:
            raise ValueError("DN doit etre strictement positif.")
        if nb_points < 16:
            raise ValueError("nb_points doit etre au moins egal a 16.")
        self.diametre = diametre
        self.rayon = diametre / 2.0
        self.nb_points = nb_points

    def demi_largeur(self, hauteur: float) -> float:
        if hauteur < 0.0 or hauteur > self.diametre:
            raise ValueError(f"La hauteur doit etre comprise entre 0 et DN={self.diametre:.6g}.")
        valeur = hauteur * (self.diametre - hauteur)
        return math.sqrt(max(0.0, valeur))

    def largeur(self, hauteur: float) -> float:
        return 2.0 * self.demi_largeur(hauteur)

    def contour(self) -> list[Point]:
        points: list[Point] = []
        for index in range(self.nb_points + 1):
            theta = -math.pi / 2.0 + 2.0 * math.pi * index / self.nb_points
            points.append(
                Point(
                    x=self.rayon * math.cos(theta),
                    y=self.rayon + self.rayon * math.sin(theta),
                )
            )
        return points


@dataclass(frozen=True)
class ConstructionVanneCirculaire:
    """Construction complete d'une VSR dans une section circulaire."""

    DN: float
    aG: float
    b_G: float
    e: float
    h_w: float
    L_up: float
    h_up: float
    a_w: float
    h_pngup: float
    b_w: float
    b_up: float
    h_png: float
    P_w: float
    y_orifice: float
    y_axe_bas: float
    y_volet: float
    y_pale_bas: float
    y_basculement: float
    y_haut: float
    beta: float
    delta: float
    alpha_max: float
    alpha_1: float
    alpha_0: float
    effort_hydrostatique: float
    moment_hydrostatique: float
    determination_hpng: DeterminationHpng
    alertes: tuple[str, ...] = ()

    def lignes_csv(self) -> list[tuple[str, float]]:
        return [
            (nom_cote_csv(champ.name), getattr(self, champ.name))
            for champ in fields(self)
            if champ.name not in {"determination_hpng", "alertes"}
        ]


class ConstructeurVanneCirculaire:
    """
    Assemble les etapes de construction d'une VSR circulaire.

    Formules reprises de la fiche de geometrie circulaire:
    - h_w = 0.6 * DN
    - h_w + h_pngup = 0.8 * DN
    - h_up = 3/4 * L_up
    - a_w = 0.2 * DN - h_up
    - y_haut = 0.8 * DN + L_up / 4
    - b_up = b_w = largeur de la conduite a y_haut
    - beta = delta = 0 deg, alpha_max = 70 deg
    """

    def __init__(
        self,
        DN: float,
        aG: float,
        b_G: float,
        e: float = 0.0,
        L_up: float | None = None,
        niveau_volet: float = 0.6,
        niveau_basculement: float = 0.8,
        tolerance: float = 1e-9,
    ) -> None:
        self.DN = DN
        self.aG = aG
        self.b_G = b_G
        self.e = e
        self.L_up = determiner_lup(DN) if L_up is None else L_up
        self.niveau_volet = niveau_volet
        self.niveau_basculement = niveau_basculement
        self.tolerance = tolerance
        self.circulaire = Circulaire(DN)
        self._valider_entrees()

    def construire(self) -> ConstructionVanneCirculaire:
        h_w = self.niveau_volet * self.DN
        h_pngup = (self.niveau_basculement - self.niveau_volet) * self.DN
        h_up = 0.75 * self.L_up
        a_w = h_pngup - h_up
        y_volet = h_w
        y_pale_bas = y_volet + a_w
        y_basculement = y_pale_bas + h_up
        y_haut = y_pale_bas + self.L_up
        b_up = self.circulaire.largeur(y_haut)
        b_w = b_up

        determination_hpng = self._determiner_h_png_direct(
            b_w=b_w,
            h_w=h_w,
            y_pale_bas=y_pale_bas,
            y_basculement=y_basculement,
        )
        h_png = determination_hpng.h_png

        construction = ConstructionVanneCirculaire(
            DN=self.DN,
            aG=self.aG,
            b_G=self.b_G,
            e=self.e,
            h_w=h_w,
            L_up=self.L_up,
            h_up=h_up,
            a_w=a_w,
            h_pngup=h_pngup,
            b_w=b_w,
            b_up=b_up,
            h_png=h_png,
            P_w=h_w - h_png,
            y_orifice=self.aG,
            y_axe_bas=h_png,
            y_volet=y_volet,
            y_pale_bas=y_pale_bas,
            y_basculement=y_basculement,
            y_haut=y_haut,
            beta=0.0,
            delta=0.0,
            alpha_max=70.0,
            alpha_1=determination_hpng.alpha_1,
            alpha_0=determination_hpng.alpha_0,
            effort_hydrostatique=determination_hpng.effort,
            moment_hydrostatique=determination_hpng.moment,
            determination_hpng=determination_hpng,
        )
        alertes = self._alertes(construction)
        return ConstructionVanneCirculaire(
            **{
                champ.name: getattr(construction, champ.name)
                for champ in fields(ConstructionVanneCirculaire)
                if champ.name != "alertes"
            },
            alertes=alertes,
        )

    def _determiner_h_png_direct(
        self,
        b_w: float,
        h_w: float,
        y_pale_bas: float,
        y_basculement: float,
    ) -> DeterminationHpng:
        if b_w <= 0.0:
            raise ValueError("b_w doit etre strictement positif.")

        # Notations de la fiche circulaire:
        # alpha_1*h_png + alpha_0 = 0.
        h_up = y_basculement - y_pale_bas
        a_w = y_pale_bas - h_w
        A = h_up + a_w
        H_etoile = A + h_w
        R = self.DN / 2.0
        h_c = R - math.sqrt(max(0.0, R**2 - (b_w / 2.0) ** 2))
        theta_c = math.acos(max(-1.0, min(1.0, 1.0 - h_c / R)))
        h_cG = R - math.sqrt(max(0.0, R**2 - (self.b_G / 2.0) ** 2))
        theta_G = math.acos(max(-1.0, min(1.0, 1.0 - h_cG / R)))

        i1 = 2.0 * R**2 * (
            (H_etoile - R) * (theta_c / 2.0 - math.sin(2.0 * theta_c) / 4.0)
            + R * math.sin(theta_c) ** 3 / 3.0
        )
        i2 = 2.0 * R**3 * (
            (H_etoile - R) * (theta_c / 2.0 - math.sin(2.0 * theta_c) / 4.0)
            + (2.0 * R - H_etoile) * math.sin(theta_c) ** 3 / 3.0
            - R * (theta_c / 8.0 - math.sin(4.0 * theta_c) / 32.0)
        )
        j1 = 2.0 * R**2 * (
            (H_etoile - R) * (theta_G / 2.0 - math.sin(2.0 * theta_G) / 4.0)
            + R * math.sin(theta_G) ** 3 / 3.0
        )
        j2 = 2.0 * R**3 * (
            (H_etoile - R) * (theta_G / 2.0 - math.sin(2.0 * theta_G) / 4.0)
            + (2.0 * R - H_etoile) * math.sin(theta_G) ** 3 / 3.0
            - R * (theta_G / 8.0 - math.sin(4.0 * theta_G) / 32.0)
        )
        encoche_rect_alpha_1 = self.b_G * (
            H_etoile * (self.aG - h_cG)
            - (self.aG**2 - h_cG**2) / 2.0
        )
        encoche_rect_constante = self.b_G * (
            H_etoile * (self.aG**2 - h_cG**2) / 2.0
            - (self.aG**3 - h_cG**3) / 3.0
        )

        alpha_1 = (
            -b_w * h_up**2 / 2.0
            - b_w * (A * h_w + h_w**2 / 2.0)
            + b_w * (H_etoile * h_c - h_c**2 / 2.0)
            - i1
            + encoche_rect_alpha_1
            + j1
        )
        alpha_0 = (
            b_w * (H_etoile * h_up**2 / 2.0 - h_up**3 / 3.0)
            + b_w * h_w**2 * (3.0 * A + h_w) / 6.0
            - b_w * (H_etoile * h_c**2 / 2.0 - h_c**3 / 3.0)
            + i2
            - encoche_rect_constante
            - j2
        )
        if abs(alpha_1) <= self.tolerance:
            raise ValueError("alpha_1 est trop proche de zero pour determiner h_png.")
        h_png = -alpha_0 / alpha_1
        self._valider_h_png(h_png, h_w)
        return DeterminationHpng(
            alpha_1=alpha_1,
            alpha_0=alpha_0,
            effort=-alpha_1,
            moment=alpha_0,
            h_png=h_png,
            b_w=b_w,
        )

    def _effort_moment_rectangle(
        self,
        largeur: float,
        y_bas: float,
        y_haut: float,
        z_eau: float,
    ) -> tuple[float, float]:
        y0 = max(0.0, min(y_bas, z_eau))
        y1 = max(0.0, min(y_haut, z_eau))
        if y1 <= y0:
            return 0.0, 0.0
        effort = largeur * self._primitive_effort(y0, y1, z_eau)
        moment = largeur * self._primitive_moment(y0, y1, z_eau)
        return effort, moment

    def _effort_moment_volet_circulaire(
        self,
        largeur: float,
        y_haut: float,
        z_eau: float,
        nb_pas: int = 1000,
    ) -> tuple[float, float]:
        demi_largeur = largeur / 2.0
        if demi_largeur <= 0.0:
            return 0.0, 0.0
        if demi_largeur > self.circulaire.rayon + self.tolerance:
            raise ValueError("La largeur a integrer depasse le diametre de la conduite.")

        effort = 0.0
        moment = 0.0
        dx = 2.0 * demi_largeur / nb_pas
        for index in range(nb_pas + 1):
            x = -demi_largeur + index * dx
            poids = 0.5 if index in {0, nb_pas} else 1.0
            y_bas = self.circulaire.rayon - math.sqrt(
                max(0.0, self.circulaire.rayon**2 - x**2)
            )
            y0 = max(0.0, min(y_bas, z_eau))
            y1 = max(0.0, min(y_haut, z_eau))
            if y1 > y0:
                effort += poids * self._primitive_effort(y0, y1, z_eau)
                moment += poids * self._primitive_moment(y0, y1, z_eau)

        return effort * dx, moment * dx

    def _primitive_effort(self, y0: float, y1: float, z_eau: float) -> float:
        return z_eau * (y1 - y0) - (y1**2 - y0**2) / 2.0

    def _primitive_moment(self, y0: float, y1: float, z_eau: float) -> float:
        return z_eau * (y1**2 - y0**2) / 2.0 - (y1**3 - y0**3) / 3.0

    def _valider_entrees(self) -> None:
        if self.aG < 0.0:
            raise ValueError("aG doit etre positif ou nul.")
        if not 0.0 < self.niveau_volet < self.niveau_basculement <= 1.0:
            raise ValueError(
                "Les niveaux doivent verifier 0 < niveau_volet < niveau_basculement <= 1."
            )
        if self.aG >= self.niveau_volet * self.DN:
            raise ValueError(
                "aG doit rester inferieur a "
                f"h_w={self.niveau_volet:.6g}*DN."
            )
        if self.b_G <= 0.0:
            raise ValueError("b_G doit etre strictement positif.")
        if self.b_G > self.circulaire.largeur(self.aG) + self.tolerance:
            raise ValueError(
                "b_G depasse la largeur disponible dans la conduite a la cote aG "
                f"({self.b_G:.6g} > {self.circulaire.largeur(self.aG):.6g})."
            )
        if self.e < 0.0:
            raise ValueError("L'epaisseur e doit etre positive ou nulle.")
        if self.L_up < 0.0:
            raise ValueError("L_up doit etre positif ou nul.")
        if self.niveau_basculement * self.DN + self.L_up / 4.0 > self.DN:
            raise ValueError(
                "L_up est trop grand: le haut de pale depasse le sommet de la conduite."
            )
        if (self.niveau_basculement - self.niveau_volet) * self.DN - 0.75 * self.L_up < 0.0:
            raise ValueError("L_up est trop grand: a_w devient negatif.")
        if self.tolerance <= 0.0:
            raise ValueError("La tolerance doit etre strictement positive.")

    def _valider_h_png(self, h_png: float, h_w: float) -> None:
        if not 0.0 <= h_png <= h_w:
            raise ValueError(f"h_png doit etre compris entre 0 et h_w={h_w:.6g}.")

    def _alertes(self, construction: ConstructionVanneCirculaire) -> tuple[str, ...]:
        alertes: list[str] = []
        if construction.y_haut > construction.DN + self.tolerance:
            alertes.append("Le haut de pale depasse le sommet de la conduite.")
        if construction.b_w > self.circulaire.largeur(construction.y_volet) + self.tolerance:
            alertes.append("b_w depasse la largeur de conduite au seuil de surverse.")
        marge_orifice = (self.circulaire.largeur(construction.aG) - construction.b_G) / 2.0
        if marge_orifice + self.tolerance < construction.e:
            alertes.append(
                f"Ecart insuffisant entre l'orifice inferieur et la paroi: "
                f"{marge_orifice:.6g}, e={construction.e:.6g}."
            )
        return tuple(alertes)


def determiner_lup(DN: float) -> float:
    if DN <= 0.0:
        raise ValueError("DN doit etre strictement positif.")
    if DN <= 1.3:
        return 0.10
    return 0.15


def exporter_csv(
    construction: ConstructionVanneCirculaire,
    chemin: str | Path = "construction_vanne_ci.csv",
) -> Path:
    chemin = _chemin_sortie(chemin)

    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        writer = csv.writer(fichier, delimiter=";")
        writer.writerow(["cote", "valeur"])
        writer.writerows((nom, f"{valeur:.9f}") for nom, valeur in construction.lignes_csv())
        writer.writerow([])
        writer.writerow(["determination_hpng", "valeur"])
        writer.writerow(["alpha_1", f"{construction.determination_hpng.alpha_1:.9f}"])
        writer.writerow(["alpha_0", f"{construction.determination_hpng.alpha_0:.9f}"])
        writer.writerow(["effort", f"{construction.determination_hpng.effort:.9f}"])
        writer.writerow(["moment", f"{construction.determination_hpng.moment:.9f}"])
        writer.writerow(["h_png", f"{construction.determination_hpng.h_png:.9f}"])
        writer.writerow(["b_w", f"{construction.determination_hpng.b_w:.9f}"])
        if construction.alertes:
            writer.writerow([])
            writer.writerow(["alerte"])
            for alerte in construction.alertes:
                writer.writerow([alerte])

    return chemin


def tracer(
    construction: ConstructionVanneCirculaire,
    chemin: str | Path = "construction_vanne_ci.png",
) -> Path:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Rectangle
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib n'est pas installe. Installe-le avec: pip install matplotlib"
        ) from exc

    chemin = _chemin_sortie(chemin)
    circulaire = Circulaire(construction.DN)
    contour = circulaire.contour()
    xs = [p.x for p in contour]
    ys = [p.y for p in contour]

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot(xs, ys, color="black", linewidth=2.0)
    ax.fill(xs, ys, color="#edf3f8", alpha=0.85)

    _tracer_ci_rectangle_centre_dans_cercle(
        ax,
        circulaire,
        construction.y_volet,
        construction.b_w,
        "#d8b6b6",
        "volet inferieur",
    )
    _tracer_ci_rectangle_centre(
        ax,
        construction.y_pale_bas,
        construction.y_haut,
        construction.b_up,
        "#c8d9ea",
        "pale haute",
    )

    cercle_clip = Circle((0.0, circulaire.rayon), circulaire.rayon, transform=ax.transData)
    orifice = Rectangle(
        (-construction.b_G / 2.0, 0.0),
        construction.b_G,
        construction.aG,
        facecolor="white",
        edgecolor="#4a4a4a",
        linewidth=1.2,
        label="orifice inferieur",
    )
    orifice.set_clip_path(cercle_clip)
    ax.add_patch(orifice)

    for y in [
        construction.aG,
        construction.y_axe_bas,
        construction.y_volet,
        construction.y_pale_bas,
        construction.y_haut,
        construction.DN,
    ]:
        _tracer_ci_ligne_cote(ax, circulaire, y, None)
    _tracer_ci_ligne_cote(
        ax,
        circulaire,
        construction.y_basculement,
        "basculement",
    )

    ax.axvline(0.0, color="#6c757d", linestyle="--", linewidth=0.8)
    ax.set_title(
        f"Construction VSR circulaire - DN={construction.DN:g}, "
        f"aG={construction.aG:g}, bG={construction.b_G:g}"
    )
    ax.set_xlabel("x")
    ax.set_ylabel("z")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.8)

    marge = 0.08 * construction.DN
    ax.set_xlim(-construction.DN / 2.0 - marge, construction.DN / 2.0 + marge)
    ax.set_ylim(-0.04 * construction.DN, 1.04 * construction.DN)
    fig.tight_layout()
    fig.savefig(chemin, dpi=200)
    plt.close(fig)
    return chemin


def _tracer_ci_rectangle_centre(ax, y0: float, y1: float, largeur: float, couleur: str, label: str) -> None:
    demi = largeur / 2.0
    ax.fill(
        [-demi, demi, demi, -demi],
        [y0, y0, y1, y1],
        color=couleur,
        alpha=0.75,
        edgecolor="#4a4a4a",
        linewidth=1.2,
        label=label,
    )


def _tracer_ci_rectangle_centre_dans_cercle(
    ax,
    circulaire: Circulaire,
    y_haut: float,
    largeur: float,
    couleur: str,
    label: str,
    nb_points: int = 160,
) -> None:
    demi = largeur / 2.0
    if demi > circulaire.rayon:
        raise ValueError("La demi-largeur du volet depasse le rayon de la conduite.")

    y_bas_cote = circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - demi**2))
    xs_bas = [
        demi - 2.0 * demi * index / nb_points
        for index in range(nb_points + 1)
    ]
    ys_bas = [
        circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - x**2))
        for x in xs_bas
    ]

    xs = [-demi, demi, demi, *xs_bas, -demi]
    ys = [y_haut, y_haut, y_bas_cote, *ys_bas, y_bas_cote]
    ax.fill(
        xs,
        ys,
        color=couleur,
        alpha=0.75,
        edgecolor="#4a4a4a",
        linewidth=1.2,
        label=label,
    )


def _tracer_ci_ligne_cote(ax, circulaire: Circulaire, y: float, label: str | None) -> None:
    y_controle = min(max(y, 0.0), circulaire.diametre)
    demi = circulaire.largeur(y_controle) / 2.0
    ax.hlines(y, -demi, demi, color="#d62828", linestyle="--", linewidth=0.9)
    if not label:
        return
    ax.text(
        demi + 0.02 * circulaire.diametre,
        y,
        label,
        va="center",
        ha="left",
        color="#7a1f1f",
        fontsize=8,
    )


exporter_csv_circulaire = exporter_csv
tracer_circulaire = tracer


# --- Profil ovoide ---

@dataclass(frozen=True)
class Point:
    x: float
    y: float


class Ovoide:
    """
    Profil 2D symetrique d'une ovoide.

    Repere utilise:
    - y = 0.0 au bas de l'ovoide
    - y = hauteur_totale au sommet
    - x = 0.0 sur l'axe de symetrie

    D'apres le croquis:
    - hauteur de reference = 1.5
    - largeur maximale = 1.0
    - demi-largeur maximale = 0.5
    - partie haute = demi-cercle de rayon 0.5 centre en (0, 1.0)
    - flancs = arcs de cercle de rayon 1.5 raccordes tangentiellement
    - bas = petit arc de cercle de rayon 0.25 centre en (0, 0.25)

    Cette construction suit l'esprit du croquis: l'ovoide est formee par un
    arc superieur, deux grands arcs lateraux et un petit arc inferieur.
    """

    HAUTEUR_REFERENCE = 1.5

    def __init__(
        self,
        hauteur_totale: float = HAUTEUR_REFERENCE,
        n_bottom: int = 160,
        n_side: int = 500,
        n_top: int = 240,
    ) -> None:
        if hauteur_totale <= 0.0:
            raise ValueError("La hauteur totale doit etre positive.")

        self.hauteur_totale = hauteur_totale
        self.echelle = hauteur_totale / self.HAUTEUR_REFERENCE

        self.r_top = self._echelle(0.5)
        self.r_side = self._echelle(1.5)
        self.r_bottom = self._echelle(0.25)
        self.top_center = self._point_echelle(0.0, 1.0)
        self.bottom_center = self._point_echelle(0.0, 0.25)
        self.side_center = self._point_echelle(-1.0, 1.0)
        self.bottom = Point(0.0, 0.0)
        self.tangent_bottom = self._point_echelle(0.20, 0.10)
        self.tangent_top = self._point_echelle(0.50, 1.00)
        self.points_droits = self._discretiser_demi_profil(n_bottom, n_side, n_top)

    def _echelle(self, valeur: float) -> float:
        return valeur * self.echelle

    def _point_echelle(self, x: float, y: float) -> Point:
        return Point(self._echelle(x), self._echelle(y))

    def _chemin_sortie(self, chemin: str | Path) -> Path:
        chemin = Path(chemin)
        if chemin.is_absolute():
            return chemin
        return DOSSIER_PROGRAMME / chemin

    def _point_sur_cercle(self, centre: Point, rayon: float, angle: float) -> Point:
        return Point(
            x=centre.x + rayon * math.cos(angle),
            y=centre.y + rayon * math.sin(angle),
        )

    def _ajouter_arc(
        self,
        points: list[Point],
        centre: Point,
        rayon: float,
        angle_debut: float,
        angle_fin: float,
        n: int,
        inclure_debut: bool = False,
    ) -> None:
        debut = 0 if inclure_debut else 1
        for i in range(debut, n + 1):
            t = i / n
            angle = angle_debut + t * (angle_fin - angle_debut)
            points.append(self._point_sur_cercle(centre, rayon, angle))

    def _discretiser_demi_profil(
        self,
        n_bottom: int,
        n_side: int,
        n_top: int,
    ) -> list[Point]:
        points: list[Point] = []

        # Bas -> raccord avec le flanc droit, petit arc inferieur.
        angle_bottom_start = -math.pi / 2.0
        angle_bottom_end = math.atan2(
            self.tangent_bottom.y - self.bottom_center.y,
            self.tangent_bottom.x - self.bottom_center.x,
        )
        self._ajouter_arc(
            points,
            self.bottom_center,
            self.r_bottom,
            angle_bottom_start,
            angle_bottom_end,
            n_bottom,
            inclure_debut=True,
        )

        # Raccord bas -> largeur maximale, grand arc lateral droit.
        angle_side_start = math.atan2(
            self.tangent_bottom.y - self.side_center.y,
            self.tangent_bottom.x - self.side_center.x,
        )
        angle_side_end = math.atan2(
            self.tangent_top.y - self.side_center.y,
            self.tangent_top.x - self.side_center.x,
        )
        self._ajouter_arc(
            points,
            self.side_center,
            self.r_side,
            angle_side_start,
            angle_side_end,
            n_side,
        )

        # Largeur maximale -> sommet, demi-cercle superieur.
        angle_top_start = math.atan2(
            self.tangent_top.y - self.top_center.y,
            self.tangent_top.x - self.top_center.x,
        )
        angle_top_end = math.pi / 2.0
        self._ajouter_arc(
            points,
            self.top_center,
            self.r_top,
            angle_top_start,
            angle_top_end,
            n_top,
        )

        return sorted(points, key=lambda p: p.y)

    def demi_largeur(self, hauteur: float) -> float:
        """Retourne la demi-largeur x pour une hauteur y donnee."""
        if hauteur < 0.0 or hauteur > self.hauteur_totale:
            raise ValueError(
                f"La hauteur doit etre comprise entre 0.0 et {self.hauteur_totale}."
            )

        pts = self.points_droits
        if hauteur == pts[0].y:
            return pts[0].x
        if hauteur == pts[-1].y:
            return pts[-1].x

        for a, b in zip(pts, pts[1:]):
            if a.y <= hauteur <= b.y:
                if math.isclose(a.y, b.y):
                    return max(a.x, b.x)
                ratio = (hauteur - a.y) / (b.y - a.y)
                return a.x + ratio * (b.x - a.x)

        # Petite securite contre les erreurs d'arrondi en bout de profil.
        return pts[-1].x

    def largeur(self, hauteur: float) -> float:
        """Retourne la largeur totale de l'ovoide a la hauteur y."""
        return 2.0 * self.demi_largeur(hauteur)

    def contour(self) -> list[Point]:
        """Retourne le contour complet de l'ovoide, dans le sens horaire."""
        cote_droit = self.points_droits
        cote_gauche = [Point(-p.x, p.y) for p in reversed(cote_droit)]
        return cote_droit + cote_gauche


# --- Cotes ovoide ---

@dataclass(frozen=True)
class CotesVanne:
    """Cotes principales d'une VSR en section ovoide."""

    T: float
    aG: float
    B: float
    e: float
    h_w: float
    L_up: float
    h_up: float
    a_w: float
    h_png: float
    P_w: float
    h_pngup: float
    b_G: float
    b_w: float
    b_s: float
    y_orifice: float
    y_volet: float
    y_basculement: float
    y_haut: float

    def lignes_csv(self) -> list[tuple[str, float]]:
        return [(nom_cote_csv(champ.name), getattr(self, champ.name)) for champ in fields(self)]


class GeometrieVanne:
    """
    Geometrie parametrique d'une vanne en conduite ovoide.

    Entrees minimales:
    - T: hauteur totale de conduite
    - aG: hauteur de l'orifice

    Formules reprises de la fiche:
    - B = T / 1.5 pour le gabarit ovoide 1.5
    - e = 0.1
    - L_up = 0.10 si T <= 1.3, sinon 0.15
    - h_w = 0.7*T - aG
    - h_up = 0.75*L_up, position du basculement depuis le bas de la pale
    - y_basculement = 0.9*T
    - y_haut = y_basculement + (L_up - h_up)
    - a_w = y_basculement - h_up - h_w - aG
    - h_pngup = a_w + h_up

    La position de l'axe inferieur h_png n'est pas entierement fixee par la
    fiche: elle est calibree par une methode de predimensionnement separee.
    Le parametre ratio_axe permet donc de la choisir dans [0, 1].
    """

    def __init__(
        self,
        T: float,
        aG: float,
        e: float = 0.1,
        L_up: float | None = None,
        ratio_ovoide: float = 1.5,
        niveau_volet: float = 0.7,
        niveau_haut: float = 0.9,
        ratio_hup_lup: float = 0.75,
        ratio_axe: float = 0.5,
    ) -> None:
        self.T = T
        self.aG = aG
        self.e = e
        self.L_up = determiner_lup(T) if L_up is None else L_up
        self.ratio_ovoide = ratio_ovoide
        self.niveau_volet = niveau_volet
        self.niveau_haut = niveau_haut
        self.ratio_hup_lup = ratio_hup_lup
        self.ratio_axe = ratio_axe
        self._valider_entrees()
        self.ovoide = Ovoide(hauteur_totale=T)
        self.cotes = self._calculer_cotes()

    def _valider_entrees(self) -> None:
        if self.T <= 0.0:
            raise ValueError("T doit etre strictement positif.")
        if self.ratio_ovoide <= 0.0:
            raise ValueError("Le ratio d'ovoide doit etre strictement positif.")
        if not 0.0 < self.niveau_volet < self.niveau_haut <= 1.0:
            raise ValueError("Les niveaux doivent verifier 0 < niveau_volet < niveau_haut <= 1.")
        if not 0.0 <= self.ratio_hup_lup <= 1.0:
            raise ValueError("ratio_hup_lup doit etre compris entre 0 et 1.")
        if self.L_up < 0.0:
            raise ValueError("L_up doit etre positif ou nul.")
        max_aG = self.niveau_volet * self.T
        if not 0.0 <= self.aG <= max_aG:
            raise ValueError(
                "aG doit etre compris entre 0 et "
                f"{max_aG:.6g} pour conserver h_w positif avec les formules du document."
            )
        h_up = self.ratio_hup_lup * self.L_up
        y_basculement = self.niveau_haut * self.T
        y_haut = y_basculement + self.L_up - h_up
        y_pale_bas = y_basculement - h_up
        if y_haut > self.T:
            raise ValueError("L_up est trop grand: le haut de pale depasse le sommet de la conduite.")
        if y_pale_bas < self.niveau_volet * self.T:
            raise ValueError("L_up est trop grand: la pale recouvre le volet inferieur.")
        if self.e < 0.0:
            raise ValueError("L'epaisseur e doit etre positive ou nulle.")
        if not 0.0 <= self.ratio_axe <= 1.0:
            raise ValueError("ratio_axe doit etre compris entre 0 et 1.")

    def _largeur_utile(self, hauteur: float) -> float:
        return self.ovoide.largeur(hauteur)

    def _calculer_cotes(self) -> CotesVanne:
        B = self.T / self.ratio_ovoide

        y_orifice = self.aG
        niveau_volet = self.niveau_volet * self.T
        y_basculement = self.niveau_haut * self.T

        L_up = self.L_up
        h_up = self.ratio_hup_lup * L_up
        y_pale_bas = y_basculement - h_up
        h_w = niveau_volet - self.aG
        a_w = y_pale_bas - h_w - self.aG

        h_png = self.ratio_axe * h_w
        P_w = h_w - h_png
        h_pngup = a_w + h_up

        y_volet = self.aG + h_w
        y_haut = y_pale_bas + L_up

        b_G = self._largeur_utile(y_orifice)
        b_w = self._largeur_utile(y_haut)
        b_s = max(0.0, b_G - 2.0 * self.e)

        return CotesVanne(
            T=self.T,
            aG=self.aG,
            B=B,
            e=self.e,
            h_w=h_w,
            L_up=L_up,
            h_up=h_up,
            a_w=a_w,
            h_png=h_png,
            P_w=P_w,
            h_pngup=h_pngup,
            b_G=b_G,
            b_w=b_w,
            b_s=b_s,
            y_orifice=y_orifice,
            y_volet=y_volet,
            y_basculement=y_basculement,
            y_haut=y_haut,
        )

# --- Determination h_png ovoide ---

@dataclass(frozen=True)
class IterationHpng:
    iteration: int
    b_w_entree: float
    h_png: float
    y_bw: float
    b_w: float
    ecart_h_png: float
    ecart_b_w: float
    residu: float


@dataclass(frozen=True)
class ResultatHpng:
    T: float
    aG: float
    B: float
    e: float
    h_w: float
    L_up: float
    h_up: float
    a_w: float
    h_pngup: float
    b_G: float
    b_s: float
    h_png: float
    P_w: float
    b_w: float
    residu: float
    iterations: tuple[IterationHpng, ...]

    def lignes_csv(self) -> list[tuple[str, float]]:
        return [
            ("T", self.T),
            ("aG", self.aG),
            ("B", self.B),
            ("e", self.e),
            ("h_w", self.h_w),
            ("L_up", self.L_up),
            ("h_up", self.h_up),
            ("a_w", self.a_w),
            ("h_pngup", self.h_pngup),
            ("b_G", self.b_G),
            ("b_s", self.b_s),
            ("h_png", self.h_png),
            ("P_w", self.P_w),
            ("b_w", self.b_w),
            ("residu", self.residu),
        ]


class DeterminationHpngOvoide:
    """
    Predimensionne h_png pour une VSR en section ovoide.

    La methode reprend la logique de la fiche:
    - on calcule les cotes geometriques de la vanne;
    - on choisit un premier h_png, donc un premier b_w;
    - on resout l'equation de moment avec ce b_w fige;
    - on recalcule b_w a la cote aG + h_png;
    - on recommence jusqu'a stabilisation de h_png et b_w.
    """

    def __init__(
        self,
        T: float,
        aG: float,
        e: float = 0.1,
        L_up: float | None = None,
        ratio_ovoide: float = 1.5,
        niveau_volet: float = 0.7,
        niveau_haut: float = 0.9,
        ratio_hup_lup: float = 0.75,
        tolerance: float = 1e-9,
        max_iterations: int = 100,
        ratio_initial: float = 0.5,
    ) -> None:
        self.T = T
        self.aG = aG
        self.e = e
        self.L_up = determiner_lup(T) if L_up is None else L_up
        self.ratio_ovoide = ratio_ovoide
        self.niveau_volet = niveau_volet
        self.niveau_haut = niveau_haut
        self.ratio_hup_lup = ratio_hup_lup
        self.tolerance = tolerance
        self.max_iterations = max_iterations
        self.ratio_initial = ratio_initial

        self.geometrie = GeometrieVanne(
            T=T,
            aG=aG,
            e=e,
            L_up=self.L_up,
            ratio_ovoide=ratio_ovoide,
            niveau_volet=niveau_volet,
            niveau_haut=niveau_haut,
            ratio_hup_lup=ratio_hup_lup,
            ratio_axe=0.0,
        )
        self.ovoide = Ovoide(hauteur_totale=T)
        self._valider_options_resolution()

    def determiner(self) -> ResultatHpng:
        c = self.geometrie.cotes
        iterations: list[IterationHpng] = []

        h_png = self.ratio_initial * c.h_w
        b_w = self.largeur_bw(h_png)

        for numero in range(1, self.max_iterations + 1):
            h_png_precedent = h_png
            b_w_entree = b_w

            h_png = self._resoudre_h_png_pour_bw(b_w_entree)
            b_w = self.largeur_bw(h_png)
            iteration = IterationHpng(
                iteration=numero,
                b_w_entree=b_w_entree,
                h_png=h_png,
                y_bw=self.aG + h_png,
                b_w=b_w,
                ecart_h_png=abs(h_png - h_png_precedent),
                ecart_b_w=abs(b_w - b_w_entree),
                residu=self.equation_avec_bw(h_png, b_w),
            )
            iterations.append(iteration)

            if (
                iteration.ecart_h_png <= self.tolerance
                and iteration.ecart_b_w <= self.tolerance
            ):
                break
        else:
            raise RuntimeError(
                "La determination iterative de h_png n'a pas converge "
                f"apres {self.max_iterations} iterations."
            )

        return ResultatHpng(
            T=c.T,
            aG=c.aG,
            B=c.B,
            e=c.e,
            h_w=c.h_w,
            L_up=c.L_up,
            h_up=c.h_up,
            a_w=c.a_w,
            h_pngup=c.h_pngup,
            b_G=c.b_G,
            b_s=c.b_s,
            h_png=h_png,
            P_w=c.h_w - h_png,
            b_w=b_w,
            residu=self.equation_avec_bw(h_png, b_w),
            iterations=tuple(iterations),
        )

    def largeur_bw(self, h_png: float) -> float:
        self._valider_h_png(h_png)
        return self.ovoide.largeur(self.aG + h_png)

    def equation(self, h_png: float) -> float:
        return self.equation_avec_bw(h_png, self.largeur_bw(h_png))

    def equation_avec_bw(self, h_png: float, b_w: float) -> float:
        self._valider_h_png(h_png)
        if b_w <= 0.0:
            raise ValueError("b_w doit etre strictement positif.")

        c = self.geometrie.cotes
        bs = c.b_s
        bw = b_w
        hw = c.h_w
        hup = c.h_up
        A = c.a_w + hup
        delta_b = bw - bs
        k1 = 2.0 * A * hw + hw**2 + hup**2
        k2 = 3.0 * A * hw**2 + hw**3 + 3.0 * (A + hw) * hup**2 - 2.0 * hup**3

        return (
            delta_b * h_png**3
            - 4.0 * (A + hw) * delta_b * h_png**2
            + 6.0 * bw * k1 * h_png
            - 2.0 * bw * k2
        )

    def _resoudre_h_png_pour_bw(self, b_w: float) -> float:
        c = self.geometrie.cotes
        a, b = self._trouver_intervalle_racine(b_w, 0.0, c.h_w)
        fa = self.equation_avec_bw(a, b_w)
        fb = self.equation_avec_bw(b, b_w)

        if abs(fa) <= self.tolerance:
            return a
        if abs(fb) <= self.tolerance:
            return b

        for _ in range(1, self.max_iterations + 1):
            h_png = (a + b) / 2.0
            residu = self.equation_avec_bw(h_png, b_w)

            if abs(residu) <= self.tolerance or (b - a) / 2.0 <= self.tolerance:
                return h_png
            if fa * residu <= 0.0:
                b = h_png
                fb = residu
            else:
                a = h_png
                fa = residu

        raise RuntimeError(
            "La resolution de h_png a b_w fixe n'a pas converge "
            f"apres {self.max_iterations} iterations."
        )

    def _trouver_intervalle_racine(self, b_w: float, h_min: float, h_max: float) -> tuple[float, float]:
        nb_pas = 400
        precedent_h = h_min
        precedent_f = self.equation_avec_bw(precedent_h, b_w)
        meilleur_h = precedent_h
        meilleur_f = abs(precedent_f)

        for index in range(1, nb_pas + 1):
            h = h_min + (h_max - h_min) * index / nb_pas
            f = self.equation_avec_bw(h, b_w)
            if abs(f) < meilleur_f:
                meilleur_h = h
                meilleur_f = abs(f)
            if precedent_f * f <= 0.0:
                return precedent_h, h
            precedent_h = h
            precedent_f = f

        raise ValueError(
            "Aucune racine de l'equation de moment n'a ete trouvee dans "
            f"[0, h_w]=[0, {h_max:.6g}] pour b_w={b_w:.6g}. "
            f"Le meilleur point balaye est h_png={meilleur_h:.6g} "
            f"avec un residu de {meilleur_f:.6g}."
        )

    def _valider_h_png(self, h_png: float) -> None:
        h_w = self.geometrie.cotes.h_w
        if not 0.0 <= h_png <= h_w:
            raise ValueError(f"h_png doit etre compris entre 0 et h_w={h_w:.6g}.")

    def _valider_options_resolution(self) -> None:
        if self.tolerance <= 0.0:
            raise ValueError("La tolerance doit etre strictement positive.")
        if self.max_iterations <= 0:
            raise ValueError("max_iterations doit etre strictement positif.")
        if not 0.0 <= self.ratio_initial <= 1.0:
            raise ValueError("ratio_initial doit etre compris entre 0 et 1.")


# --- Construction ovoide ---


def largeur_orifice_equivalente(T: float, aG: float, nb_pas: int = 1000) -> float:
    if aG <= 0.0:
        return 0.0

    ovoide = Ovoide(hauteur_totale=T)
    dz = aG / nb_pas
    aire = 0.0
    for index in range(nb_pas + 1):
        z = index * dz
        poids = 0.5 if index in {0, nb_pas} else 1.0
        aire += poids * ovoide.largeur(z)
    aire *= dz
    return aire / aG


@dataclass(frozen=True)
class ConstructionVanneOvoide:
    """Construction complete d'une VSR dans une section ovoide."""

    T: float
    aG: float
    B: float
    e: float
    h_w: float
    L_up: float
    h_up: float
    a_w: float
    h_pngup: float
    b_G: float
    bG_eq: float
    b_s: float
    h_png: float
    P_w: float
    b_w_hpng: float
    b_w: float
    y_orifice: float
    y_axe_bas: float
    y_volet: float
    y_pale_bas: float
    y_basculement: float
    y_haut: float
    residu_hpng: float
    iterations: tuple[IterationHpng, ...]
    alertes: tuple[str, ...] = ()

    @classmethod
    def depuis_hpng(cls, resultat: ResultatHpng) -> "ConstructionVanneOvoide":
        y_orifice = resultat.aG
        y_axe_bas = resultat.aG + resultat.h_png
        y_volet = resultat.aG + resultat.h_w
        y_pale_bas = resultat.aG + resultat.h_w + resultat.a_w
        y_basculement = y_pale_bas + resultat.h_up
        y_haut = y_pale_bas + resultat.L_up
        b_w = Ovoide(hauteur_totale=resultat.T).largeur(y_haut)

        return cls(
            T=resultat.T,
            aG=resultat.aG,
            B=resultat.B,
            e=resultat.e,
            h_w=resultat.h_w,
            L_up=resultat.L_up,
            h_up=resultat.h_up,
            a_w=resultat.a_w,
            h_pngup=resultat.h_pngup,
            b_G=resultat.b_G,
            bG_eq=largeur_orifice_equivalente(resultat.T, resultat.aG),
            b_s=resultat.b_s,
            h_png=resultat.h_png,
            P_w=resultat.P_w,
            b_w_hpng=resultat.b_w,
            b_w=b_w,
            y_orifice=y_orifice,
            y_axe_bas=y_axe_bas,
            y_volet=y_volet,
            y_pale_bas=y_pale_bas,
            y_basculement=y_basculement,
            y_haut=y_haut,
            residu_hpng=resultat.residu,
            iterations=resultat.iterations,
        )

    @classmethod
    def depuis_resultat(
        cls,
        resultat: ResultatHpng,
        h_png: float,
        b_w_hpng: float,
        b_w: float,
        residu_hpng: float,
        iterations: tuple[IterationHpng, ...],
        alertes: tuple[str, ...] = (),
    ) -> "ConstructionVanneOvoide":
        y_orifice = resultat.aG
        y_axe_bas = resultat.aG + h_png
        y_volet = resultat.aG + resultat.h_w
        y_pale_bas = resultat.aG + resultat.h_w + resultat.a_w
        y_basculement = y_pale_bas + resultat.h_up
        y_haut = y_pale_bas + resultat.L_up

        return cls(
            T=resultat.T,
            aG=resultat.aG,
            B=resultat.B,
            e=resultat.e,
            h_w=resultat.h_w,
            L_up=resultat.L_up,
            h_up=resultat.h_up,
            a_w=resultat.a_w,
            h_pngup=resultat.h_pngup,
            b_G=resultat.b_G,
            bG_eq=largeur_orifice_equivalente(resultat.T, resultat.aG),
            b_s=resultat.b_s,
            h_png=h_png,
            P_w=resultat.h_w - h_png,
            b_w_hpng=b_w_hpng,
            b_w=b_w,
            y_orifice=y_orifice,
            y_axe_bas=y_axe_bas,
            y_volet=y_volet,
            y_pale_bas=y_pale_bas,
            y_basculement=y_basculement,
            y_haut=y_haut,
            residu_hpng=residu_hpng,
            iterations=iterations,
            alertes=alertes,
        )

    def lignes_csv(self) -> list[tuple[str, float]]:
        lignes: list[tuple[str, float]] = []
        for champ in fields(self):
            if champ.name in {"b_w_hpng", "iterations", "alertes"}:
                continue
            lignes.append((nom_cote_csv(champ.name), getattr(self, champ.name)))
        return lignes


class ConstructeurVanneOvoide:
    """
    Assemble les etapes de construction d'une VSR ovoide.

    Les calculs de profil viennent de abaque_ovoide.py, les cotes de base de
    cotes.py via le solveur, et la position de l'axe h_png de
    determination_hpng_ov.py.
    """

    def __init__(
        self,
        T: float,
        aG: float,
        e: float = 0.1,
        L_up: float | None = None,
        ratio_ovoide: float = 1.5,
        niveau_volet: float = 0.7,
        niveau_haut: float = 0.9,
        ratio_hup_lup: float = 0.75,
        tolerance: float = 1e-9,
        max_iterations: int = 100,
        ratio_initial: float = 0.5,
        marge_paroi: float = 0.01,
        marge_pale: float = 0.0,
    ) -> None:
        self.solveur = DeterminationHpngOvoide(
            T=T,
            aG=aG,
            e=e,
            L_up=L_up,
            ratio_ovoide=ratio_ovoide,
            niveau_volet=niveau_volet,
            niveau_haut=niveau_haut,
            ratio_hup_lup=ratio_hup_lup,
            tolerance=tolerance,
            max_iterations=max_iterations,
            ratio_initial=ratio_initial,
        )
        self.niveau_haut = niveau_haut
        self.ovoide = Ovoide(hauteur_totale=T)
        self.marge_paroi = marge_paroi
        self.marge_pale = marge_pale

    def construire(self) -> ConstructionVanneOvoide:
        resultat_reference = self.solveur.determiner()
        y_haut = (
            resultat_reference.aG
            + resultat_reference.h_w
            + resultat_reference.a_w
            + resultat_reference.L_up
        )
        b_w, h_png, iterations = self._determiner_bw_avec_marge(resultat_reference, y_haut)
        b_w_hpng = self.ovoide.largeur(resultat_reference.aG + h_png)
        residu = self.solveur.equation_avec_bw(h_png, b_w)
        construction_sans_alertes = ConstructionVanneOvoide.depuis_resultat(
            resultat=resultat_reference,
            h_png=h_png,
            b_w_hpng=b_w_hpng,
            b_w=b_w,
            residu_hpng=residu,
            iterations=iterations,
        )
        self._controler_largeurs(construction_sans_alertes)
        alertes = self._alertes_ecart_paroi(construction_sans_alertes)
        return ConstructionVanneOvoide.depuis_resultat(
            resultat=resultat_reference,
            h_png=h_png,
            b_w_hpng=b_w_hpng,
            b_w=b_w,
            residu_hpng=residu,
            iterations=iterations,
            alertes=alertes,
        )

    def _determiner_bw_avec_marge(
        self,
        resultat_reference: ResultatHpng,
        y_haut: float,
    ) -> tuple[float, float, tuple[IterationHpng, ...]]:
        b_w = self.ovoide.largeur(y_haut) - 2.0 * self.marge_pale
        h_png_precedent = 0.0
        iterations: list[IterationHpng] = []

        for numero in range(1, self.solveur.max_iterations + 1):
            b_w_entree = b_w
            h_png = self.solveur._resoudre_h_png_pour_bw(b_w_entree)
            y_axe_bas = resultat_reference.aG + h_png
            b_w_limite = self._largeur_bw_maximale(
                resultat_reference=resultat_reference,
                y_axe_bas=y_axe_bas,
                y_haut=y_haut,
            )
            b_w = min(b_w_entree, b_w_limite)
            if b_w <= 0.0:
                raise ValueError(
                    "Impossible de respecter la marge a la paroi avec une largeur b_w positive."
                )

            iterations.append(
                IterationHpng(
                    iteration=numero,
                    b_w_entree=b_w_entree,
                    h_png=h_png,
                    y_bw=y_axe_bas,
                    b_w=b_w,
                    ecart_h_png=abs(h_png - h_png_precedent),
                    ecart_b_w=abs(b_w - b_w_entree),
                    residu=self.solveur.equation_avec_bw(h_png, b_w),
                )
            )

            if (
                abs(b_w - b_w_entree) <= self.solveur.tolerance
                and abs(h_png - h_png_precedent) <= self.solveur.tolerance
            ):
                return b_w, h_png, tuple(iterations)

            h_png_precedent = h_png

        raise RuntimeError(
            "La determination iterative de b_w n'a pas converge "
            f"apres {self.solveur.max_iterations} iterations."
        )

    def _largeur_bw_maximale(
        self,
        resultat_reference: ResultatHpng,
        y_axe_bas: float,
        y_haut: float,
        nb_pas: int = 300,
    ) -> float:
        marge_orifice = resultat_reference.e
        marge_bw = resultat_reference.e + self.marge_paroi
        limite = self.ovoide.largeur(y_haut) - 2.0 * self.marge_pale

        # Volet inferieur trapezoidal: l'orifice bas respecte e, la largeur b_w
        # est reduite si les flancs du trapeze approchent trop la paroi.
        if y_axe_bas > resultat_reference.aG:
            for index in range(1, nb_pas + 1):
                t = index / nb_pas
                y = resultat_reference.aG + (y_axe_bas - resultat_reference.aG) * t
                largeur_disponible = self.ovoide.largeur(y) - 2.0 * marge_orifice
                limite = min(
                    limite,
                    resultat_reference.b_s + (largeur_disponible - resultat_reference.b_s) / t,
                )

        # Volet superieur: partie a largeur constante b_w, avec marge
        # supplementaire de 0.01 par rapport a e. La regle de e ne s'applique
        # pas sur la pale.
        y_debut_constante = min(y_axe_bas, resultat_reference.aG + resultat_reference.h_w)
        y_fin_constante = resultat_reference.aG + resultat_reference.h_w
        for index in range(nb_pas + 1):
            y = y_debut_constante + (y_fin_constante - y_debut_constante) * index / nb_pas
            limite = min(limite, self.ovoide.largeur(y) - 2.0 * marge_bw)

        # Pale: la marge hydraulique e ne s'applique pas. Par defaut, la pale
        # va jusqu'a la paroi au niveau de son haut.
        y_pale_bas = resultat_reference.aG + resultat_reference.h_w + resultat_reference.a_w
        for index in range(nb_pas + 1):
            y = y_pale_bas + (y_haut - y_pale_bas) * index / nb_pas
            limite = min(limite, self.ovoide.largeur(y) - 2.0 * self.marge_pale)

        return max(0.0, limite)

    def _controler_largeurs(self, construction: ConstructionVanneOvoide) -> None:
        b_w_hpng_abaque = self.ovoide.largeur(construction.y_axe_bas)
        if abs(b_w_hpng_abaque - construction.b_w_hpng) > self.solveur.tolerance * 10.0:
            raise RuntimeError(
                "Incoherence de largeur b_w_hpng entre l'abaque et la determination "
                f"h_png: {b_w_hpng_abaque:.9f} != {construction.b_w_hpng:.9f}."
            )
        b_w_abaque = self.ovoide.largeur(construction.y_haut)
        if construction.b_w > b_w_abaque + self.solveur.tolerance * 10.0:
            raise RuntimeError(
                "Incoherence de largeur b_w: la construction depasse la largeur "
                f"aux coins superieurs de la pale ({construction.b_w:.9f} > {b_w_abaque:.9f})."
            )

    def _alertes_ecart_paroi(self, construction: ConstructionVanneOvoide) -> tuple[str, ...]:
        controles = [
            (
                "volet inferieur",
                construction.y_orifice,
                construction.y_axe_bas,
                construction.b_s,
                construction.b_w,
                False,
                construction.e,
            ),
            (
                "volet superieur",
                construction.y_axe_bas,
                construction.y_volet,
                construction.b_w,
                construction.b_w,
                False,
                construction.e + self.marge_paroi,
            ),
            (
                "pale",
                construction.y_pale_bas,
                construction.y_haut,
                construction.b_w,
                construction.b_w,
                False,
                self.marge_pale,
            ),
        ]

        alertes: list[str] = []
        for nom, y0, y1, largeur0, largeur1, ignorer_haut, marge_requise in controles:
            marge_min, y_marge = self._marge_minimale(y0, y1, largeur0, largeur1, ignorer_haut)
            if marge_min + self.solveur.tolerance < marge_requise:
                alertes.append(
                    f"Ecart insuffisant entre la paroi et {nom}: "
                    f"{marge_min:.6g} a y={y_marge:.6g}, "
                    f"marge requise={marge_requise:.6g}."
                )
        return tuple(alertes)

    def _marge_minimale(
        self,
        y0: float,
        y1: float,
        largeur0: float,
        largeur1: float,
        ignorer_haut: bool,
        nb_pas: int = 200,
    ) -> tuple[float, float]:
        marge_min = float("inf")
        y_marge = y0

        for index in range(nb_pas + 1):
            if ignorer_haut and index == nb_pas:
                continue
            t = index / nb_pas
            y = y0 + (y1 - y0) * t
            largeur = largeur0 + (largeur1 - largeur0) * t
            marge = (self.ovoide.largeur(y) - largeur) / 2.0
            if marge < marge_min:
                marge_min = marge
                y_marge = y

        return marge_min, y_marge


def _chemin_sortie(chemin: str | Path) -> Path:
    chemin = Path(chemin)
    if chemin.is_absolute():
        return chemin
    return DOSSIER_PROGRAMME / chemin


def exporter_csv(
    construction: ConstructionVanneOvoide,
    chemin: str | Path = "construction_vanne_ov.csv",
) -> Path:
    chemin = _chemin_sortie(chemin)

    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        writer = csv.writer(fichier, delimiter=";")
        writer.writerow(["cote", "valeur"])
        writer.writerows((nom, f"{valeur:.9f}") for nom, valeur in construction.lignes_csv())
        writer.writerow([])
        writer.writerow(
            [
                "iteration",
                "b_w_entree",
                "h_png",
                "aG_plus_h_png",
                "b_w_actualise",
                "ecart_h_png",
                "ecart_b_w",
                "residu_actualise",
            ]
        )
        for iteration in construction.iterations:
            writer.writerow(
                [
                    iteration.iteration,
                    f"{iteration.b_w_entree:.9f}",
                    f"{iteration.h_png:.9f}",
                    f"{iteration.y_bw:.9f}",
                    f"{iteration.b_w:.9f}",
                    f"{iteration.ecart_h_png:.9e}",
                    f"{iteration.ecart_b_w:.9e}",
                    f"{iteration.residu:.9e}",
                ]
            )
        if construction.alertes:
            writer.writerow([])
            writer.writerow(["alerte"])
            for alerte in construction.alertes:
                writer.writerow([alerte])

    return chemin


def tracer(
    construction: ConstructionVanneOvoide,
    chemin: str | Path = "construction_vanne_ov.png",
) -> Path:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib n'est pas installe. Installe-le avec: pip install matplotlib"
        ) from exc

    chemin = _chemin_sortie(chemin)
    ovoide = Ovoide(hauteur_totale=construction.T)
    contour = ovoide.contour()
    xs = [p.x for p in contour]
    ys = [p.y for p in contour]

    fig, ax = plt.subplots(figsize=(6, 7))
    ax.plot(xs, ys, color="black", linewidth=2.0)
    ax.fill(xs, ys, color="#edf3f8", alpha=0.85)

    _tracer_ov_trapeze_centre(
        ax,
        construction.y_orifice,
        construction.y_axe_bas,
        construction.b_s,
        construction.b_w,
        "#d8b6b6",
        "volet inferieur",
    )
    _tracer_ov_rectangle_centre(
        ax,
        construction.y_axe_bas,
        construction.y_volet,
        construction.b_w,
        "#d8b6b6",
        "volet superieur",
    )
    _tracer_ov_rectangle_centre(
        ax,
        construction.y_pale_bas,
        construction.y_haut,
        construction.b_w,
        "#c8d9ea",
        "pale haute",
    )

    for y in [
        construction.y_orifice,
        construction.y_axe_bas,
        construction.y_volet,
        construction.y_pale_bas,
        construction.y_basculement,
        construction.T,
    ]:
        _tracer_ov_ligne_cote(ax, ovoide, y, None)
    _tracer_ov_ligne_cote(
        ax,
        ovoide,
        construction.y_basculement,
        "basculement",
    )

    ax.axvline(0.0, color="#6c757d", linestyle="--", linewidth=0.8)
    ax.set_title(f"Construction VSR ovoide - DN={construction.T:g}, aG={construction.aG:g}")
    ax.set_xlabel("x")
    ax.set_ylabel("z")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.8)

    marge_gauche = 0.08 * construction.T
    marge_droite = 0.28 * construction.T
    ax.set_xlim(-construction.B / 2.0 - marge_gauche, construction.B / 2.0 + marge_droite)
    ax.set_ylim(-0.04 * construction.T, 1.04 * construction.T)
    fig.tight_layout()
    fig.savefig(chemin, dpi=200)
    plt.close(fig)
    return chemin


def _tracer_ov_rectangle_centre(ax, y0: float, y1: float, largeur: float, couleur: str, label: str) -> None:
    demi = largeur / 2.0
    ax.fill(
        [-demi, demi, demi, -demi],
        [y0, y0, y1, y1],
        color=couleur,
        alpha=0.75,
        edgecolor="#4a4a4a",
        linewidth=1.2,
        label=label,
    )


def _tracer_ov_trapeze_centre(
    ax,
    y0: float,
    y1: float,
    largeur_bas: float,
    largeur_haut: float,
    couleur: str,
    label: str,
) -> None:
    demi_bas = largeur_bas / 2.0
    demi_haut = largeur_haut / 2.0
    ax.fill(
        [-demi_bas, demi_bas, demi_haut, -demi_haut],
        [y0, y0, y1, y1],
        color=couleur,
        alpha=0.75,
        edgecolor="#4a4a4a",
        linewidth=1.2,
        label=label,
    )


def _placer_etiquettes(
    lignes_cotes: list[tuple[float, str]],
    hauteur: float,
) -> list[tuple[float, str, float]]:
    espacement_min = 0.045 * hauteur
    marge_basse = -0.02 * hauteur
    marge_haute = 1.02 * hauteur
    etiquettes: list[tuple[float, str, float]] = []

    for y, label in sorted(lignes_cotes, key=lambda item: item[0]):
        y_texte = y
        if etiquettes and y_texte - etiquettes[-1][2] < espacement_min:
            y_texte = etiquettes[-1][2] + espacement_min
        etiquettes.append((y, label, min(max(y_texte, marge_basse), marge_haute)))

    decalage = max(0.0, etiquettes[-1][2] - marge_haute) if etiquettes else 0.0
    if decalage:
        etiquettes = [(y, label, max(y_texte - decalage, marge_basse)) for y, label, y_texte in etiquettes]
    return etiquettes


def _tracer_ov_ligne_cote(ax, ovoide: Ovoide, y: float, label: str | None, y_texte: float | None = None) -> None:
    y_controle = min(max(y, 0.0), ovoide.hauteur_totale)
    demi = ovoide.largeur(y_controle) / 2.0
    ax.hlines(y, -demi, demi, color="#d62828", linestyle="--", linewidth=0.9)
    if not label:
        return
    x_texte = demi + 0.02 * ovoide.hauteur_totale
    y_texte = y if y_texte is None else y_texte
    if abs(y_texte - y) > 1e-12:
        ax.plot(
            [demi, x_texte - 0.006 * ovoide.hauteur_totale],
            [y, y_texte],
            color="#7a1f1f",
            linewidth=0.6,
        )
    ax.text(
        x_texte,
        y_texte,
        label,
        va="center",
        ha="left",
        color="#7a1f1f",
        fontsize=8,
    )


exporter_csv_ovoide = exporter_csv
tracer_ovoide = tracer


# --- Export SALOME ---

def exporter_salome_circulaire(
    construction: ConstructionVanneCirculaire,
    chemin: str | Path = "construction_vanne_ci_salome.py",
    position_vanne: str = "ouverte",
) -> Path:
    chemin = _chemin_sortie(chemin)
    circulaire = Circulaire(construction.DN)
    y_bas_joues = circulaire.rayon - math.sqrt(
        max(0.0, circulaire.rayon**2 - (construction.b_w / 2.0) ** 2)
    )
    elements = [
        ("face", "conduite", [(p.x, p.y) for p in circulaire.contour()]),
        *_faces_joues_laterales(
            circulaire.largeur,
            y_bas_joues,
            construction.y_haut,
            [
                (y_bas_joues, construction.b_w),
                (construction.y_haut, construction.b_w),
            ],
        ),
        (
            "face",
            "volet_inferieur",
            _points_rectangle_centre_dans_cercle_avec_orifice(
                circulaire,
                construction.y_volet,
                construction.b_w,
                construction.aG,
                construction.b_G,
            ),
        ),
        (
            "face",
            "pale_haute",
            _points_rectangle_centre(
                construction.y_pale_bas,
                construction.y_haut,
                construction.b_up,
            ),
        ),
    ]
    lignes = [
        (
            "trait_orifice",
            _segment_centre(construction.b_G, construction.aG),
        ),
        (
            "trait_seuil",
            _segment_centre(circulaire.largeur(construction.y_volet), construction.y_volet),
        ),
        (
            "trait_pale_bas",
            _segment_centre(circulaire.largeur(construction.y_pale_bas), construction.y_pale_bas),
        ),
        *_segments_verticaux_bords(
            "trait_seuil_pale",
            construction.b_up,
            construction.y_volet,
            construction.y_haut,
        ),
        ("trait_haut_pale", _segment_centre(construction.b_up, construction.y_haut)),
    ]
    _ecrire_script_salome(chemin, "circulaire", construction.lignes_csv(), elements, lignes, position_vanne)
    return chemin


def exporter_salome_ovoide(
    construction: ConstructionVanneOvoide,
    chemin: str | Path = "construction_vanne_ov_salome.py",
    position_vanne: str = "ouverte",
) -> Path:
    chemin = _chemin_sortie(chemin)
    ovoide = Ovoide(hauteur_totale=construction.T)
    largeur_pale = construction.b_w
    elements = [
        ("face", "conduite", [(p.x, p.y) for p in ovoide.contour()]),
        *_faces_joues_laterales(
            ovoide.largeur,
            construction.y_orifice,
            construction.y_haut,
            [
                (construction.y_orifice, construction.b_s),
                (construction.y_axe_bas, largeur_pale),
                (construction.y_haut, largeur_pale),
            ],
        ),
        (
            "face",
            "volet_inferieur",
            _points_volet_ovoide(
                construction.y_orifice,
                construction.y_axe_bas,
                construction.y_volet,
                construction.b_s,
                largeur_pale,
            ),
        ),
        (
            "face",
            "pale_haute",
            _points_rectangle_centre(
                construction.y_pale_bas,
                construction.y_haut,
                largeur_pale,
            ),
        ),
    ]
    lignes = [
        (
            "trait_orifice",
            _segment_centre(ovoide.largeur(construction.y_orifice), construction.y_orifice),
        ),
        (
            "trait_seuil",
            _segment_centre(ovoide.largeur(construction.y_volet), construction.y_volet),
        ),
        (
            "trait_pale_bas",
            _segment_centre(ovoide.largeur(construction.y_pale_bas), construction.y_pale_bas),
        ),
        (
            "trait_volet_bas_gauche",
            [
                (-construction.b_s / 2.0, construction.y_orifice),
                (-largeur_pale / 2.0, construction.y_axe_bas),
            ],
        ),
        (
            "trait_volet_bas_droite",
            [
                (construction.b_s / 2.0, construction.y_orifice),
                (largeur_pale / 2.0, construction.y_axe_bas),
            ],
        ),
        *_segments_verticaux_bords(
            "trait_bw",
            largeur_pale,
            construction.y_axe_bas,
            construction.y_haut,
        ),
        ("trait_haut_pale", _segment_centre(largeur_pale, construction.y_haut)),
    ]
    _ecrire_script_salome(chemin, "ovoide", construction.lignes_csv(), elements, lignes, position_vanne)
    return chemin


def _points_rectangle_centre(y0: float, y1: float, largeur: float) -> list[tuple[float, float]]:
    demi = largeur / 2.0
    return [(-demi, y0), (demi, y0), (demi, y1), (-demi, y1)]


def _faces_joues_laterales(
    largeur_section,
    y_bas: float,
    y_haut: float,
    largeurs_interieures: list[tuple[float, float]],
    nb_points: int = 80,
) -> list[tuple[str, str, list[tuple[float, float]]]]:
    if y_haut <= y_bas:
        return []
    profils = sorted(largeurs_interieures)
    if len(profils) < 2:
        raise ValueError("Il faut au moins deux largeurs interieures pour creer les joues.")

    def demi_interieur(y: float) -> float:
        if y <= profils[0][0]:
            return profils[0][1] / 2.0
        for (y0, l0), (y1, l1) in zip(profils, profils[1:]):
            if y <= y1:
                if abs(y1 - y0) <= 1e-12:
                    return l1 / 2.0
                t = (y - y0) / (y1 - y0)
                return (l0 + (l1 - l0) * t) / 2.0
        return profils[-1][1] / 2.0

    ys_uniformes = [
        y_bas + (y_haut - y_bas) * index / nb_points
        for index in range(nb_points + 1)
    ]
    ys_ruptures = [y for y, _ in profils if y_bas <= y <= y_haut]
    ys = sorted({round(y, 12) for y in [*ys_uniformes, *ys_ruptures]})
    droite_exterieure = [(largeur_section(y) / 2.0, y) for y in ys]
    droite_interieure = [(demi_interieur(y), y) for y in reversed(ys)]
    gauche_exterieure = [(-largeur_section(y) / 2.0, y) for y in reversed(ys)]
    gauche_interieure = [(-demi_interieur(y), y) for y in ys]
    return [
        ("face", "joue_laterale_droite", droite_exterieure + droite_interieure),
        ("face", "joue_laterale_gauche", gauche_exterieure + gauche_interieure),
    ]


def _segment_centre(largeur: float, y: float) -> list[tuple[float, float]]:
    demi = largeur / 2.0
    return [(-demi, y), (demi, y)]


def _segments_verticaux_bords(
    prefixe: str,
    largeur: float,
    y_bas: float,
    y_haut: float,
) -> list[tuple[str, list[tuple[float, float]]]]:
    demi = largeur / 2.0
    return [
        (f"{prefixe}_gauche", [(-demi, y_bas), (-demi, y_haut)]),
        (f"{prefixe}_droite", [(demi, y_bas), (demi, y_haut)]),
    ]


def _points_trapeze_centre(
    y0: float,
    y1: float,
    largeur_bas: float,
    largeur_haut: float,
) -> list[tuple[float, float]]:
    demi_bas = largeur_bas / 2.0
    demi_haut = largeur_haut / 2.0
    return [(-demi_bas, y0), (demi_bas, y0), (demi_haut, y1), (-demi_haut, y1)]


def _points_volet_ovoide(
    y_orifice: float,
    y_axe_bas: float,
    y_volet: float,
    largeur_orifice: float,
    largeur_volet: float,
) -> list[tuple[float, float]]:
    demi_orifice = largeur_orifice / 2.0
    demi_volet = largeur_volet / 2.0
    return [
        (-demi_orifice, y_orifice),
        (demi_orifice, y_orifice),
        (demi_volet, y_axe_bas),
        (demi_volet, y_volet),
        (-demi_volet, y_volet),
        (-demi_volet, y_axe_bas),
    ]


def _points_rectangle_centre_dans_cercle(
    circulaire: Circulaire,
    y_haut: float,
    largeur: float,
    nb_points: int = 80,
) -> list[tuple[float, float]]:
    demi = largeur / 2.0
    if demi > circulaire.rayon:
        raise ValueError("La demi-largeur du volet depasse le rayon de la conduite.")
    y_bas_cote = circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - demi**2))
    points = [(-demi, y_haut), (demi, y_haut), (demi, y_bas_cote)]
    for index in range(nb_points + 1):
        x = demi - 2.0 * demi * index / nb_points
        y = circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - x**2))
        points.append((x, y))
    points.append((-demi, y_bas_cote))
    return points


def _points_rectangle_centre_dans_cercle_avec_orifice(
    circulaire: Circulaire,
    y_haut: float,
    largeur: float,
    hauteur_orifice: float,
    largeur_orifice: float,
    nb_points: int = 80,
) -> list[tuple[float, float]]:
    demi = largeur / 2.0
    demi_orifice = largeur_orifice / 2.0
    if demi > circulaire.rayon:
        raise ValueError("La demi-largeur du volet depasse le rayon de la conduite.")
    if demi_orifice > demi:
        raise ValueError("La demi-largeur de l'orifice depasse celle du volet.")

    y_bas_cote = circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - demi**2))
    y_bas_orifice = circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - demi_orifice**2))
    if hauteur_orifice <= y_bas_orifice:
        return _points_rectangle_centre_dans_cercle(circulaire, y_haut, largeur, nb_points)

    points = [(-demi, y_haut), (demi, y_haut), (demi, y_bas_cote)]
    for index in range(nb_points + 1):
        x = demi - (demi - demi_orifice) * index / nb_points
        y = circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - x**2))
        points.append((x, y))
    points.extend(
        [
            (demi_orifice, hauteur_orifice),
            (-demi_orifice, hauteur_orifice),
        ]
    )
    for index in range(nb_points + 1):
        x = -demi_orifice - (demi - demi_orifice) * index / nb_points
        y = circulaire.rayon - math.sqrt(max(0.0, circulaire.rayon**2 - x**2))
        points.append((x, y))
    points.append((-demi, y_bas_cote))
    return points


def _ecrire_script_salome(
    chemin: Path,
    section: str,
    cotes: list[tuple[str, float]],
    elements: list[tuple[str, str, list[tuple[float, float]]]],
    lignes: list[tuple[str, list[tuple[float, float]]]],
    position_vanne: str,
) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = _script_salome(section, cotes, elements, lignes, position_vanne)
    chemin.write_text(texte, encoding="utf-8")


def _script_salome(
    section: str,
    cotes: list[tuple[str, float]],
    elements: list[tuple[str, str, list[tuple[float, float]]]],
    lignes: list[tuple[str, list[tuple[float, float]]]],
    position_vanne: str,
) -> str:
    return f'''# Script genere par construction_vanne.py.
# A lancer dans le Python de SALOME.

import salome
salome.salome_init()

import math
from salome.geom import geomBuilder

geompy = geomBuilder.New()

SECTION = {section!r}
COTES = {_format_salome_cotes(cotes)}
ELEMENTS = {_format_salome_elements(elements)}
LIGNES = {_format_salome_lignes(lignes)}
POSITION_VANNE = {position_vanne!r}
EPAISSEUR_VANNE_X = 0.01
EPAISSEUR_JOUE_Y = 0.01
MARGE_AVAL_JOUE = 0.01
ANGLE_VANNE_DEGRE = 70.0
NOMS_FACES_VANNE = {{"volet_inferieur", "pale_haute"}}
NOMS_FACES_JOUES = {{"joue_laterale_gauche", "joue_laterale_droite"}}


def vertex(point):
    y, z = point
    return geompy.MakeVertex(0.0, float(y), float(z))


def vertex_xyz(x, y, z):
    return geompy.MakeVertex(float(x), float(y), float(z))


def distance2(a, b):
    return (float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2


def nettoyer_points(points, closed=True, tolerance=1e-9):
    tolerance2 = tolerance ** 2
    propres = []
    for point in points:
        if not propres or distance2(point, propres[-1]) > tolerance2:
            propres.append(point)
    if closed and len(propres) > 1 and distance2(propres[0], propres[-1]) <= tolerance2:
        propres.pop()
    minimum = 3 if closed else 2
    if len(propres) < minimum:
        if closed:
            raise RuntimeError("Pas assez de points distincts pour creer " + str(points))
        return []
    return propres


def wire_from_points(name, points, closed=True):
    points = nettoyer_points(points, closed=closed)
    if not points:
        return None
    vertices = [vertex(point) for point in points]
    edges = []
    limite = len(vertices) if closed else len(vertices) - 1
    for index in range(limite):
        edges.append(geompy.MakeLineTwoPnt(vertices[index], vertices[(index + 1) % len(vertices)]))
    try:
        wire = geompy.MakeWire(edges)
    except TypeError:
        wire = geompy.MakeWire(edges, 1e-7)
    return wire


def face_from_points(name, points):
    wire = wire_from_points(name, points, closed=True)
    if wire is None:
        raise RuntimeError("Impossible de creer la face " + name)
    try:
        face = geompy.MakeFaceWires([wire], 1)
    except TypeError:
        face = geompy.MakeFace(wire, 1)
    return face


def line_from_points(name, points):
    wire = wire_from_points(name, points, closed=False)
    if wire is None:
        return None
    return wire


def line_xyz_from_points(points):
    vertices = [vertex_xyz(*point) for point in points]
    edges = []
    for index in range(len(vertices) - 1):
        edges.append(geompy.MakeLineTwoPnt(vertices[index], vertices[index + 1]))
    try:
        return geompy.MakeWire(edges)
    except TypeError:
        return geompy.MakeWire(edges, 1e-7)


def extruder_x(objet, longueur):
    try:
        return geompy.MakePrismDXDYDZ(objet, float(longueur), 0.0, 0.0)
    except AttributeError:
        vecteur = geompy.MakeVectorDXDYDZ(float(longueur), 0.0, 0.0)
    return geompy.MakePrismVecH(objet, vecteur, 1.0)


def extruder_z(objet, longueur):
    try:
        return geompy.MakePrismDXDYDZ(objet, 0.0, 0.0, float(longueur))
    except AttributeError:
        vecteur = geompy.MakeVectorDXDYDZ(0.0, 0.0, float(longueur))
    return geompy.MakePrismVecH(objet, vecteur, 1.0)


def face_xy_rectangle(x_centre, y_centre, largeur_x, largeur_y, z):
    demi_x = largeur_x / 2.0
    demi_y = largeur_y / 2.0
    return face_xyz_from_points(
        "rectangle_xy",
        [
            (x_centre - demi_x, y_centre - demi_y, z),
            (x_centre + demi_x, y_centre - demi_y, z),
            (x_centre + demi_x, y_centre + demi_y, z),
            (x_centre - demi_x, y_centre + demi_y, z),
        ],
    )


def face_xyz_from_points(name, points):
    vertices = [vertex_xyz(*point) for point in points]
    edges = []
    for index in range(len(vertices)):
        edges.append(geompy.MakeLineTwoPnt(vertices[index], vertices[(index + 1) % len(vertices)]))
    try:
        wire = geompy.MakeWire(edges)
    except TypeError:
        wire = geompy.MakeWire(edges, 1e-7)
    try:
        return geompy.MakeFaceWires([wire], 1)
    except TypeError:
        return geompy.MakeFace(wire, 1)


COTES_DICT = dict(COTES)
TRANSLATION_Z = 1.5 * COTES_DICT.get("DN", COTES_DICT.get("T", 1.0))


def lignes_avec_trait_orifice_force(lignes):
    z_orifice = COTES_DICT.get("z_orifice", COTES_DICT.get("y_orifice", COTES_DICT.get("aG")))
    if z_orifice is None:
        return lignes
    if SECTION == "circulaire" and "b_G" in COTES_DICT:
        demi = COTES_DICT["b_G"] / 2.0
        return [
            (name, [(-demi, z_orifice), (demi, z_orifice)])
            if name == "trait_orifice" and len(points) >= 2
            else (name, points)
            for name, points in lignes
        ]
    points_conduite = []
    for _, name, points in ELEMENTS:
        if name == "conduite":
            points_conduite = points
            break
    intersections = []
    if points_conduite:
        for index, (y0, z0) in enumerate(points_conduite):
            y1, z1 = points_conduite[(index + 1) % len(points_conduite)]
            if abs(z1 - z0) <= 1e-12:
                if abs(z_orifice - z0) <= 1e-12:
                    intersections.extend([y0, y1])
                continue
            if min(z0, z1) - 1e-12 <= z_orifice <= max(z0, z1) + 1e-12:
                t = (z_orifice - z0) / (z1 - z0)
                if -1e-12 <= t <= 1.0 + 1e-12:
                    intersections.append(y0 + (y1 - y0) * t)
    if len(intersections) >= 2:
        y_gauche = min(intersections)
        y_droite = max(intersections)
    else:
        y_gauche = min(points[0][0] for name, points in lignes if name == "trait_orifice")
        y_droite = max(points[-1][0] for name, points in lignes if name == "trait_orifice")
    lignes_corrigees = []
    for name, points in lignes:
        if name == "trait_orifice" and len(points) >= 2:
            lignes_corrigees.append((name, [(y_gauche, z_orifice), (y_droite, z_orifice)]))
        else:
            lignes_corrigees.append((name, points))
    return lignes_corrigees


def demi_largeur_conduite(z):
    points_conduite = []
    for _, name, points in ELEMENTS:
        if name == "conduite":
            points_conduite = points
            break
    intersections = []
    for index, (y0, z0) in enumerate(points_conduite):
        y1, z1 = points_conduite[(index + 1) % len(points_conduite)]
        if abs(z1 - z0) <= 1e-12:
            if abs(z - z0) <= 1e-12:
                intersections.extend([y0, y1])
            continue
        if min(z0, z1) - 1e-12 <= z <= max(z0, z1) + 1e-12:
            t = (z - z0) / (z1 - z0)
            if -1e-12 <= t <= 1.0 + 1e-12:
                intersections.append(y0 + (y1 - y0) * t)
    if len(intersections) < 2:
        return 0.0
    return max(abs(min(intersections)), abs(max(intersections)))


def face_debit_rectangulaire(z_bas, z_haut, largeur):
    demi = largeur / 2.0
    return face_from_points(
        "face_debit",
        [(-demi, z_bas), (demi, z_bas), (demi, z_haut), (-demi, z_haut)],
    )


def face_debit_orifice(z_limite):
    if SECTION == "circulaire" and "b_G" in COTES_DICT:
        demi = COTES_DICT["b_G"] / 2.0
        return face_from_points(
            "orifice_debit",
            [(-demi, 0.0), (demi, 0.0), (demi, z_limite), (-demi, z_limite)],
        )
    points_conduite = []
    for _, name, points in ELEMENTS:
        if name == "conduite":
            points_conduite = points
            break
    points_clippes = []
    for index, point0 in enumerate(points_conduite):
        point1 = points_conduite[(index + 1) % len(points_conduite)]
        y0, z0 = point0
        y1, z1 = point1
        dedans0 = z0 <= z_limite + 1e-12
        dedans1 = z1 <= z_limite + 1e-12
        if dedans0:
            points_clippes.append(point0)
        if dedans0 != dedans1 and abs(z1 - z0) > 1e-12:
            t = (z_limite - z0) / (z1 - z0)
            points_clippes.append((y0 + (y1 - y0) * t, z_limite))
    return face_from_points("orifice_debit", points_clippes)


def face_debit_surverse(z_limite):
    points_conduite = []
    for _, name, points in ELEMENTS:
        if name == "conduite":
            points_conduite = points
            break
    points_clippes = []
    for index, point0 in enumerate(points_conduite):
        point1 = points_conduite[(index + 1) % len(points_conduite)]
        y0, z0 = point0
        y1, z1 = point1
        dedans0 = z0 >= z_limite - 1e-12
        dedans1 = z1 >= z_limite - 1e-12
        if dedans0:
            points_clippes.append(point0)
        if dedans0 != dedans1 and abs(z1 - z0) > 1e-12:
            t = (z_limite - z0) / (z1 - z0)
            points_clippes.append((y0 + (y1 - y0) * t, z_limite))
    return face_from_points("Surverse_debit", points_clippes)


def chemin_haut_conduite(z_limite):
    points_conduite = []
    for _, name, points in ELEMENTS:
        if name == "conduite":
            points_conduite = points
            break
    points_clippes = []
    for index, point0 in enumerate(points_conduite):
        point1 = points_conduite[(index + 1) % len(points_conduite)]
        y0, z0 = point0
        y1, z1 = point1
        dedans0 = z0 >= z_limite - 1e-12
        dedans1 = z1 >= z_limite - 1e-12
        if dedans0:
            points_clippes.append(point0)
        if dedans0 != dedans1 and abs(z1 - z0) > 1e-12:
            t = (z_limite - z0) / (z1 - z0)
            points_clippes.append((y0 + (y1 - y0) * t, z_limite))
    points_sur_limite = [
        (index, point)
        for index, point in enumerate(points_clippes)
        if abs(point[1] - z_limite) <= 1e-9
    ]
    if len(points_sur_limite) < 2:
        return points_clippes
    index_droit, _ = max(points_sur_limite, key=lambda item: item[1][0])
    index_gauche, _ = min(points_sur_limite, key=lambda item: item[1][0])
    if index_droit <= index_gauche:
        chemin = points_clippes[index_droit : index_gauche + 1]
    else:
        chemin = points_clippes[index_droit:] + points_clippes[: index_gauche + 1]
    return nettoyer_points(chemin, closed=False)


def face_debit_surverse_sans_joues(z_bas, z_haut_joues, largeur_interieure):
    chemin_haut = chemin_haut_conduite(z_haut_joues)
    if len(chemin_haut) < 2:
        return face_debit_surverse(z_bas)
    demi = largeur_interieure / 2.0
    points = [
        (demi, z_bas),
        (demi, z_haut_joues),
        *chemin_haut,
        (-demi, z_haut_joues),
        (-demi, z_bas),
    ]
    return face_from_points("Surverse_debit", nettoyer_points(points))


def chemin_bas_conduite(z_limite):
    points_conduite = []
    for _, name, points in ELEMENTS:
        if name == "conduite":
            points_conduite = points
            break
    points_clippes = []
    for index, point0 in enumerate(points_conduite):
        point1 = points_conduite[(index + 1) % len(points_conduite)]
        y0, z0 = point0
        y1, z1 = point1
        dedans0 = z0 <= z_limite + 1e-12
        dedans1 = z1 <= z_limite + 1e-12
        if dedans0:
            points_clippes.append(point0)
        if dedans0 != dedans1 and abs(z1 - z0) > 1e-12:
            t = (z_limite - z0) / (z1 - z0)
            points_clippes.append((y0 + (y1 - y0) * t, z_limite))
    points_sur_limite = [
        (index, point)
        for index, point in enumerate(points_clippes)
        if abs(point[1] - z_limite) <= 1e-9
    ]
    if len(points_sur_limite) < 2:
        return points_clippes
    index_droit, point_droit = max(points_sur_limite, key=lambda item: item[1][0])
    index_gauche, point_gauche = min(points_sur_limite, key=lambda item: item[1][0])
    chemin = [point_droit]
    chemin.extend(reversed(points_clippes[:index_droit]))
    branche_gauche = list(reversed(points_clippes[index_gauche + 1 :]))
    if chemin and branche_gauche and distance2(chemin[-1], branche_gauche[0]) <= 1e-18:
        branche_gauche = branche_gauche[1:]
    chemin.extend(branche_gauche)
    chemin.append(point_gauche)
    return nettoyer_points(chemin, closed=False)


def face_debit_orifice_sans_joues(z_limite, z_axe, z_volet, largeur_basse, largeur_haute):
    chemin_bas = chemin_bas_conduite(z_limite)
    if len(chemin_bas) < 2:
        return face_debit_orifice(z_limite)
    demi_bas = largeur_basse / 2.0
    demi_haut = largeur_haute / 2.0
    points = [
        (demi_haut, z_volet),
        (demi_haut, z_axe),
        (demi_bas, z_limite),
        *chemin_bas,
        (-demi_bas, z_limite),
        (-demi_haut, z_axe),
        (-demi_haut, z_volet),
    ]
    return face_from_points("orifice_debit", nettoyer_points(points))


def face_debit_orifice_circulaire_ouverte(z_haut, largeur_interieure, nb_points=80):
    rayon = COTES_DICT["DN"] / 2.0
    demi = largeur_interieure / 2.0
    if demi > rayon:
        raise RuntimeError("La demi-largeur de orifice_debit depasse le rayon circulaire.")
    z_bas_cote = rayon - math.sqrt(max(0.0, rayon**2 - demi**2))
    points = [(-demi, z_haut), (demi, z_haut), (demi, z_bas_cote)]
    for index in range(nb_points + 1):
        y = demi - 2.0 * demi * index / nb_points
        z = rayon - math.sqrt(max(0.0, rayon**2 - y**2))
        points.append((y, z))
    points.append((-demi, z_bas_cote))
    return face_from_points("orifice_debit", nettoyer_points(points))


LIGNES = lignes_avec_trait_orifice_force(LIGNES)


def translater_scene(objet):
    return geompy.MakeTranslation(objet, 0.0, 0.0, TRANSLATION_Z)


objets = []
objets_2d = []
objets_solides = []
faces = []
faces_nommees = []
faces_joues = []
face_conduite = None
traits_construction = []
bati_solide = None
longueur_joue = None
for nature, name, points in ELEMENTS:
    if nature == "face":
        objet = face_from_points(name, points)
        faces.append(objet)
        faces_nommees.append((name, objet))
        if name == "conduite":
            face_conduite = objet
        if name in NOMS_FACES_JOUES:
            faces_joues.append(objet)
    else:
        objet = wire_from_points(name, points)
    if objet is not None:
        objets_2d.append(objet)

for name, points in LIGNES:
    objet = line_from_points(name, points)
    if objet is not None:
        traits_construction.append(objet)

points_reference = [point for _, _, points in ELEMENTS for point in points]
largeur_reference = max(abs(x) for x, _ in points_reference) if points_reference else 1.0
hauteur_reference = max(abs(z) for _, z in points_reference) if points_reference else 1.0
origine = geompy.MakeVertex(0.0, 0.0, 0.0)
repere_x = geompy.MakeLineTwoPnt(origine, geompy.MakeVertex(largeur_reference, 0.0, 0.0))
repere_y = geompy.MakeLineTwoPnt(origine, vertex((largeur_reference, 0.0)))
repere_z = geompy.MakeLineTwoPnt(vertex((0.0, 0.0)), vertex((0.0, hauteur_reference)))
geompy.addToStudy(repere_x, "axe_X")
geompy.addToStudy(repere_y, "axe_Y")
geompy.addToStudy(repere_z, "axe_Z")

if face_conduite is not None:
    longueur_reference_conduite = COTES_DICT.get("DN", COTES_DICT.get("T", hauteur_reference))
    longueur_amont = 10.0 * longueur_reference_conduite
    facteur_aval = 5.0 if POSITION_VANNE == "fermee" else 10.0
    longueur_aval = facteur_aval * longueur_reference_conduite
    conduite_amont = extruder_x(face_conduite, -longueur_amont)
    conduite_aval = extruder_x(face_conduite, longueur_aval)
    cote_regard = 0.25 * longueur_reference_conduite
    hauteur_regard = longueur_reference_conduite
    z_base_regard = 0.95 * longueur_reference_conduite
    positions_regards = [-3.0, 3.0, -8.0]
    if POSITION_VANNE == "ouverte":
        positions_regards.append(8.0)
    regards = []
    for position_regard in positions_regards:
        face_regard = face_xy_rectangle(
            position_regard * longueur_reference_conduite,
            0.0,
            cote_regard,
            cote_regard,
            z_base_regard,
        )
        regards.append(extruder_z(face_regard, hauteur_regard))
    solides_conduite = [conduite_amont, conduite_aval, *regards]
    try:
        conduite = geompy.MakeFuseList(solides_conduite, True, True)
    except Exception:
        conduite = geompy.MakeCompound(solides_conduite)
    conduite = translater_scene(conduite)
    objets_solides.append(conduite)
    geompy.addToStudy(conduite, "conduite")

points_vanne = [
    point
    for _, name, points in ELEMENTS
    if name in NOMS_FACES_VANNE
    for point in points
]
solides_vanne_fermee = []
solides_vanne_ouverte = []
angle_vanne = math.radians(ANGLE_VANNE_DEGRE)
z_rotation = COTES_DICT.get("z_axe_bas", COTES_DICT.get("y_axe_bas", hauteur_reference))
demi_largeur_axe = max(abs(y) for y, _ in points_vanne) if points_vanne else largeur_reference
x_axe_rotation = EPAISSEUR_VANNE_X / 2.0
axe_rotation_hpng_reference = geompy.MakeLineTwoPnt(
    vertex_xyz(x_axe_rotation, -demi_largeur_axe, z_rotation),
    vertex_xyz(x_axe_rotation, demi_largeur_axe, z_rotation),
)
axe_rotation_hpng = translater_scene(axe_rotation_hpng_reference)
geompy.addToStudy(axe_rotation_hpng, "axe_rotation_h_png_70deg")


def x_apres_rotation_vanne(x, z):
    return (
        x_axe_rotation
        + (x - x_axe_rotation) * math.cos(angle_vanne)
        + (z - z_rotation) * math.sin(angle_vanne)
    )


def z_apres_rotation_vanne(x, z):
    return (
        z_rotation
        - (x - x_axe_rotation) * math.sin(angle_vanne)
        + (z - z_rotation) * math.cos(angle_vanne)
    )


z_orifice = COTES_DICT.get("z_orifice", COTES_DICT.get("aG", 0.0))
z_volet = COTES_DICT["z_volet"]
z_pale_bas = COTES_DICT["z_pale_bas"]
z_haut = COTES_DICT["z_haut"]
largeur_pale = max(abs(y) for _, name, points in ELEMENTS if name in NOMS_FACES_VANNE for y, _ in points) * 2.0
if POSITION_VANNE == "ouverte":
    x_surverse_ouverte = x_apres_rotation_vanne(0.0, z_haut)
    z_surverse_bas_ouverte = z_apres_rotation_vanne(0.0, z_haut)
    faces_debit = [
        (
            "Surverse_debit",
            geompy.MakeTranslation(
                face_debit_surverse_sans_joues(
                    z_surverse_bas_ouverte,
                    z_haut,
                    largeur_pale,
                ),
                x_surverse_ouverte,
                0.0,
                0.0,
            ),
        ),
        ("Seuil_debit", face_debit_rectangulaire(z_volet, z_pale_bas, largeur_pale)),
        (
            "orifice_debit",
            face_debit_orifice_circulaire_ouverte(
                COTES_DICT.get("z_axe_bas", COTES_DICT.get("y_axe_bas", z_orifice)),
                largeur_pale,
            )
            if SECTION == "circulaire"
            else face_debit_orifice_sans_joues(
                z_orifice,
                COTES_DICT.get("z_axe_bas", COTES_DICT.get("y_axe_bas", z_orifice)),
                COTES_DICT.get("z_axe_bas", COTES_DICT.get("y_axe_bas", z_orifice)),
                COTES_DICT.get("b_s", COTES_DICT.get("b_G", 2.0 * demi_largeur_conduite(z_orifice))),
                largeur_pale,
            ),
        ),
    ]
    faces_debit = [
        (
            nom_face_debit,
            geompy.MakeRotation(face_debit, axe_rotation_hpng_reference, angle_vanne)
            if face_debit is not None and nom_face_debit == "Seuil_debit"
            else face_debit,
        )
        for nom_face_debit, face_debit in faces_debit
    ]
else:
    faces_debit = [
        ("Surverse_debit", face_debit_surverse(z_haut)),
        ("Seuil_debit", face_debit_rectangulaire(z_volet, z_pale_bas, largeur_pale)),
        ("orifice_debit", face_debit_orifice(z_orifice)),
    ]
for nom_face_debit, face_debit in faces_debit:
    if face_debit is not None:
        geompy.addToStudy(translater_scene(face_debit), nom_face_debit)

for name, face in faces_nommees:
    if name not in NOMS_FACES_VANNE:
        continue
    solide = extruder_x(face, EPAISSEUR_VANNE_X)
    if POSITION_VANNE == "fermee":
        solides_vanne_fermee.append(solide)
    else:
        solide_oriente = geompy.MakeRotation(solide, axe_rotation_hpng_reference, angle_vanne)
        solides_vanne_ouverte.append(solide_oriente)

if solides_vanne_fermee:
    try:
        vanne_fermee = geompy.MakeFuseList(solides_vanne_fermee, True, True)
    except Exception:
        vanne_fermee = geompy.MakeCompound(solides_vanne_fermee)
    vanne_fermee = translater_scene(vanne_fermee)
    objets_solides.append(vanne_fermee)
    geompy.addToStudy(vanne_fermee, "vanne_fermee")

if solides_vanne_ouverte:
    try:
        vanne_ouverte = geompy.MakeFuseList(solides_vanne_ouverte, True, True)
    except Exception:
        vanne_ouverte = geompy.MakeCompound(solides_vanne_ouverte)
    vanne_ouverte = translater_scene(vanne_ouverte)
    objets_solides.append(vanne_ouverte)
    geompy.addToStudy(vanne_ouverte, "vanne_ouverte")

if points_vanne and faces_joues:
    longueur_volet_ouvert = (
        COTES_DICT["P_w"]
        + COTES_DICT["a_w"]
        + COTES_DICT["L_up"]
    )
    longueur_joue = longueur_volet_ouvert * math.sin(angle_vanne) + MARGE_AVAL_JOUE
    solides_joues = [extruder_x(face, longueur_joue) for face in faces_joues]
    try:
        joues_laterales = geompy.MakeFuseList(solides_joues, True, True)
    except Exception:
        joues_laterales = geompy.MakeCompound(solides_joues)
    bati_solide = joues_laterales

if bati_solide is not None:
    traits_bati = list(traits_construction)
    if longueur_joue is not None:
        for name, points in LIGNES:
            if name == "trait_orifice" and len(points) >= 2:
                traits_bati.append(
                    line_xyz_from_points(
                        [
                            (longueur_joue, points[0][0], points[0][1]),
                            (longueur_joue, points[-1][0], points[-1][1]),
                        ]
                    )
                )
                break
    bati_elements = [bati_solide] + traits_bati
    bati = geompy.MakeCompound(bati_elements)
    bati = translater_scene(bati)
    objets_solides.append(bati)
    geompy.addToStudy(bati, "bati")

if objets_2d:
    coupe_2d = geompy.MakeCompound(objets_2d)
    coupe_2d = translater_scene(coupe_2d)
    geompy.addToStudy(coupe_2d, "coupe_2D_" + SECTION)

if objets_solides:
    assemblage = geompy.MakeCompound(objets_solides)
else:
    assemblage = geompy.MakeCompound(objets_2d)
geompy.addToStudy(assemblage, "VSR_" + SECTION)

if salome.sg.hasDesktop():
    salome.sg.updateObjBrowser()
'''


def _format_salome_cotes(cotes: list[tuple[str, float]]) -> str:
    lignes = ["["]
    for nom, valeur in cotes:
        lignes.append(f"    ({nom!r}, {valeur:.12g}),")
    lignes.append("]")
    return "\n".join(lignes)


def _format_salome_elements(elements: list[tuple[str, str, list[tuple[float, float]]]]) -> str:
    lignes = ["["]
    for nature, nom, points in elements:
        lignes.append(f"    ({nature!r}, {nom!r}, {_format_salome_points(points)}),")
    lignes.append("]")
    return "\n".join(lignes)


def _format_salome_lignes(lignes_cotes: list[tuple[str, list[tuple[float, float]]]]) -> str:
    lignes = ["["]
    for nom, points in lignes_cotes:
        lignes.append(f"    ({nom!r}, {_format_salome_points(points)}),")
    lignes.append("]")
    return "\n".join(lignes)


def _format_salome_points(points: list[tuple[float, float]]) -> str:
    valeurs = ", ".join(f"({x:.12g}, {y:.12g})" for x, y in points)
    return f"[{valeurs}]"


# --- Interface utilisateur Excel ---

COLONNES_MODELE = [
    "section",
    "DN",
    "aG",
    "bG",
    "rapport_seuil",
    "rapport_basculement",
    "position_vanne",
]
PARAMETRES_MODELE = [
    ("section", "Circulaire"),
    ("DN", 1.5),
    ("aG", 0.2),
    ("bG", 0.6),
    ("rapport_seuil", ""),
    ("rapport_basculement", ""),
    ("position_vanne", "ouverte"),
]


@dataclass(frozen=True)
class ParametresVanne:
    section: str
    DN: float
    aG: float
    bG: float | None
    rapport_seuil: float | None
    rapport_basculement: float | None
    position_vanne: str = "ouverte"


def normaliser_nom(valeur: object) -> str:
    texte = "" if valeur is None else str(valeur).strip()
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    texte = texte.lower()
    return re.sub(r"[^a-z0-9]+", "_", texte).strip("_")


def normaliser_section(valeur: object) -> str:
    section = normaliser_nom(valeur)
    if section in {"circulaire", "cercle", "ci"}:
        return "circulaire"
    if section in {"ovoide", "ovo", "ov"}:
        return "ovoide"
    raise ValueError("La section doit etre 'circulaire' ou 'ovoide'.")


def normaliser_position_vanne(valeur: object) -> str:
    position = normaliser_nom("ouverte" if valeur in (None, "") else valeur)
    if position in {"ouverte", "ouvert", "open"}:
        return "ouverte"
    if position in {"fermee", "ferme", "fermee", "closed"}:
        return "fermee"
    raise ValueError("La position de vanne doit etre 'ouverte' ou 'fermee'.")


def convertir_float(valeur: object, nom: str, obligatoire: bool = True) -> float | None:
    if valeur is None or str(valeur).strip() == "":
        if obligatoire:
            raise ValueError(f"Le parametre '{nom}' est obligatoire.")
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).strip().replace(",", ".")
    try:
        return float(texte)
    except ValueError as exc:
        raise ValueError(f"Le parametre '{nom}' doit etre numerique: {valeur!r}.") from exc


def lire_parametres_xlsx(chemin: str | Path) -> ParametresVanne:
    lignes = lire_table_xlsx(chemin)
    lignes_non_vides = [ligne for ligne in lignes if any(cellule not in (None, "") for cellule in ligne)]
    if len(lignes_non_vides) < 2:
        raise ValueError("Le fichier Excel doit contenir les parametres et leurs valeurs.")

    if _est_format_vertical(lignes_non_vides):
        ligne = {
            normaliser_nom(ligne_excel[0]): ligne_excel[1] if len(ligne_excel) > 1 else None
            for ligne_excel in lignes_non_vides
            if normaliser_nom(ligne_excel[0]) not in {"parametre", "parametre_requis"}
        }
    else:
        entetes = [normaliser_nom(cellule) for cellule in lignes_non_vides[0]]
        valeurs = lignes_non_vides[1]
        ligne = {
            entete: valeurs[index] if index < len(valeurs) else None
            for index, entete in enumerate(entetes)
            if entete
        }

    section = normaliser_section(_valeur(ligne, "section"))
    DN = convertir_float(_valeur(ligne, "dn", "diametre", "diameter"), "DN")
    aG = convertir_float(_valeur(ligne, "ag", "a_g"), "aG")
    bG = convertir_float(_valeur(ligne, "bg", "b_g"), "bG", obligatoire=section == "circulaire")
    rapport_seuil = convertir_float(
        _valeur(ligne, "rapport_seuil", "niveau_seuil", "hauteur_seuil"),
        "rapport_seuil",
        obligatoire=False,
    )
    rapport_basculement = convertir_float(
        _valeur(ligne, "rapport_basculement", "niveau_basculement", "hauteur_basculement"),
        "rapport_basculement",
        obligatoire=False,
    )
    position_vanne = normaliser_position_vanne(
        _valeur(ligne, "position_vanne", "position", "vanne", "etat_vanne", "ouverture")
    )

    return ParametresVanne(section, DN, aG, bG, rapport_seuil, rapport_basculement, position_vanne)


def _est_format_vertical(lignes: list[list[object]]) -> bool:
    noms_parametres = {normaliser_nom(nom) for nom in COLONNES_MODELE}
    premiere_colonne = {normaliser_nom(ligne[0]) for ligne in lignes if ligne}
    return bool(premiere_colonne & noms_parametres)


def _valeur(ligne: dict[str, object], *noms: str) -> object:
    for nom in noms:
        cle = normaliser_nom(nom)
        if cle in ligne:
            return ligne[cle]
    return None


def lire_table_xlsx(chemin: str | Path) -> list[list[object]]:
    chemin = Path(chemin)
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier Excel introuvable: {chemin}")

    with zipfile.ZipFile(chemin) as archive:
        chaines = _lire_shared_strings(archive)
        feuille = _chemin_premiere_feuille(archive)
        racine = ET.fromstring(archive.read(feuille))

    lignes: list[list[object]] = []
    for row in racine.findall(".//{*}sheetData/{*}row"):
        cellules: dict[int, object] = {}
        for cellule in row.findall("{*}c"):
            reference = cellule.attrib.get("r", "")
            colonne = _index_colonne(reference)
            cellules[colonne] = _lire_cellule(cellule, chaines)
        if cellules:
            taille = max(cellules) + 1
            lignes.append([cellules.get(index) for index in range(taille)])
    return lignes


def _lire_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    racine = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    chaines: list[str] = []
    for si in racine.findall("{*}si"):
        morceaux = [texte.text or "" for texte in si.findall(".//{*}t")]
        chaines.append("".join(morceaux))
    return chaines


def _chemin_premiere_feuille(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    premiere_feuille = workbook.find(".//{*}sheets/{*}sheet")
    if premiere_feuille is None:
        raise ValueError("Le classeur Excel ne contient pas de feuille.")
    relation_id = premiere_feuille.attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    if not relation_id:
        return "xl/worksheets/sheet1.xml"
    relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relation in relations.findall("{*}Relationship"):
        if relation.attrib.get("Id") == relation_id:
            return str(PurePosixPath("xl") / relation.attrib["Target"])
    raise ValueError("Impossible de trouver la premiere feuille du classeur.")


def _index_colonne(reference: str) -> int:
    lettres = re.match(r"[A-Z]+", reference.upper())
    if lettres is None:
        return 0
    index = 0
    for lettre in lettres.group(0):
        index = index * 26 + ord(lettre) - ord("A") + 1
    return index - 1


def _lire_cellule(cellule: ET.Element, chaines: list[str]) -> object:
    type_cellule = cellule.attrib.get("t")
    if type_cellule == "inlineStr":
        return "".join(texte.text or "" for texte in cellule.findall(".//{*}t"))
    valeur = cellule.find("{*}v")
    if valeur is None or valeur.text is None:
        return None
    texte = valeur.text
    if type_cellule == "s":
        return chaines[int(texte)]
    if type_cellule == "b":
        return texte == "1"
    try:
        nombre = float(texte)
    except ValueError:
        return texte
    if nombre.is_integer():
        return int(nombre)
    return nombre


def construire_depuis_parametres(parametres: ParametresVanne, dossier_sortie: str | Path = ".") -> tuple[Path, Path, Path]:
    dossier_sortie = Path(dossier_sortie)
    if not dossier_sortie.is_absolute():
        dossier_sortie = DOSSIER_PROGRAMME / dossier_sortie
    dossier_sortie.mkdir(parents=True, exist_ok=True)

    base = nom_base_sortie(parametres)
    chemin_csv = dossier_sortie / f"{base}_cotes.csv"
    chemin_png = dossier_sortie / f"{base}.png"
    chemin_salome = dossier_sortie / f"{base}_salome.py"
    rapport_seuil, rapport_basculement = rapports_effectifs(parametres)

    if parametres.section == "circulaire":
        construction = ConstructeurVanneCirculaire(
            DN=parametres.DN,
            aG=parametres.aG,
            b_G=parametres.bG if parametres.bG is not None else 0.0,
            niveau_volet=rapport_seuil,
            niveau_basculement=rapport_basculement,
        ).construire()
        csv = exporter_csv_circulaire(construction, chemin_csv)
        png = tracer_circulaire(construction, chemin_png)
        salome_py = exporter_salome_circulaire(
            construction,
            chemin_salome,
            parametres.position_vanne,
        )
    else:
        construction = ConstructeurVanneOvoide(
            T=parametres.DN,
            aG=parametres.aG,
            niveau_volet=rapport_seuil,
            niveau_haut=rapport_basculement,
        ).construire()
        csv = exporter_csv_ovoide(construction, chemin_csv)
        png = tracer_ovoide(construction, chemin_png)
        salome_py = exporter_salome_ovoide(
            construction,
            chemin_salome,
            parametres.position_vanne,
        )

    for alerte in construction.alertes:
        print(f"ALERTE: {alerte}")
    return csv, png, salome_py


def lancer_construction(
    fichier_excel: str | Path = "parametres_vanne.xlsx",
    dossier_sortie: str | Path = ".",
) -> tuple[Path, Path, Path]:
    chemin_excel = Path(fichier_excel)
    if not chemin_excel.is_absolute():
        chemin_excel = DOSSIER_PROGRAMME / chemin_excel

    if not chemin_excel.exists():
        creer_modele_xlsx(chemin_excel)
        print(f"Modele Excel cree: {chemin_excel}")
        print("Remplis ce fichier, enregistre-le, puis relance la fonction.")
        return chemin_excel, chemin_excel, chemin_excel

    parametres = lire_parametres_xlsx(chemin_excel)
    chemin_csv, chemin_png, chemin_salome = construire_depuis_parametres(parametres, dossier_sortie)
    print(f"Cotes exportees dans {chemin_csv}")
    print(f"Trace exporte dans {chemin_png}")
    print(f"Script SALOME exporte dans {chemin_salome}")
    return chemin_csv, chemin_png, chemin_salome


def rapports_effectifs(parametres: ParametresVanne) -> tuple[float, float]:
    if parametres.section == "circulaire":
        return parametres.rapport_seuil or 0.6, parametres.rapport_basculement or 0.8
    return parametres.rapport_seuil or 0.7, parametres.rapport_basculement or 0.9


def nom_base_sortie(parametres: ParametresVanne) -> str:
    bG = "auto" if parametres.bG is None else _format_nombre(parametres.bG)
    nom = (
        f"VSR_{parametres.section}_DN{_format_nombre(parametres.DN)}_"
        f"aG{_format_nombre(parametres.aG)}_bG{bG}_"
        f"{parametres.position_vanne}_{VERSION_PROGRAMME}"
    )
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", nom)


def _format_nombre(valeur: float) -> str:
    return f"{valeur:g}".replace(",", ".")


def creer_modele_xlsx(chemin: str | Path = "parametres_vanne.xlsx") -> Path:
    chemin = Path(chemin)
    if not chemin.is_absolute():
        chemin = DOSSIER_PROGRAMME / chemin
    valeurs = [["parametre", "valeur"], *PARAMETRES_MODELE]
    _ecrire_xlsx_simple(chemin, valeurs)
    return chemin


def _ecrire_xlsx_simple(chemin: Path, lignes: list[list[object]]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types())
        archive.writestr("_rels/.rels", _rels_racine())
        archive.writestr("xl/workbook.xml", _workbook())
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels())
        archive.writestr("xl/worksheets/sheet1.xml", _feuille(lignes))


def _cellule(reference: str, valeur: object) -> str:
    if isinstance(valeur, (int, float)):
        return f'<c r="{reference}"><v>{valeur}</v></c>'
    texte = escape(str(valeur))
    return f'<c r="{reference}" t="inlineStr"><is><t>{texte}</t></is></c>'


def _feuille(lignes: list[list[object]]) -> str:
    rows: list[str] = []
    for index_ligne, ligne in enumerate(lignes, start=1):
        cellules = []
        for index_colonne, valeur in enumerate(ligne):
            reference = f"{_nom_colonne(index_colonne)}{index_ligne}"
            cellules.append(_cellule(reference, valeur))
        rows.append(f'<row r="{index_ligne}">{"".join(cellules)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows)}</sheetData>'
        '<dataValidations count="2">'
        '<dataValidation type="list" allowBlank="0" showErrorMessage="1" sqref="B2">'
        '<formula1>"Ovoide,Circulaire"</formula1>'
        '</dataValidation>'
        '<dataValidation type="list" allowBlank="0" showErrorMessage="1" sqref="B8">'
        '<formula1>"ouverte,fermee"</formula1>'
        '</dataValidation>'
        '</dataValidations>'
        '</worksheet>'
    )


def _nom_colonne(index: int) -> str:
    nom = ""
    index += 1
    while index:
        index, reste = divmod(index - 1, 26)
        nom = chr(ord("A") + reste) + nom
    return nom


def _content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""


def _rels_racine() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="parametres" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""


def _workbook_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construit une VSR avec le programme v2 a partir d'un fichier Excel de parametres."
    )
    parser.add_argument("xlsx", nargs="?", default="parametres_vanne.xlsx", help="Fichier .xlsx de parametres.")
    parser.add_argument("--sortie", default=".", help="Dossier des fichiers generes.")
    parser.add_argument("--modele", action="store_true", help="Cree un modele .xlsx puis s'arrete.")
    args = parser.parse_args()

    if args.modele:
        chemin_modele = creer_modele_xlsx(args.xlsx)
        print(f"Modele Excel cree: {chemin_modele}")
        return

    lancer_construction(args.xlsx, args.sortie)


if __name__ == "__main__":
    main()
