from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, fields
from pathlib import Path


DOSSIER_PROGRAMME = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Point:
    x: float
    y: float


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
            (champ.name, getattr(self, champ.name))
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

        # Notations proches de la fiche:
        # h_png est le centre de pression, donc le rapport moment / effort.
        z_eau = y_basculement
        b_s = self.b_G

        f_volet, m_volet = self._effort_moment_volet_circulaire(
            largeur=b_w,
            y_haut=h_w,
            z_eau=z_eau,
        )
        f_orifice, m_orifice = self._effort_moment_volet_circulaire(
            largeur=b_s,
            y_haut=self.aG,
            z_eau=z_eau,
        )
        f_pale, m_pale = self._effort_moment_rectangle(
            largeur=b_w,
            y_bas=y_pale_bas,
            y_haut=y_basculement,
            z_eau=z_eau,
        )

        effort_total = f_volet - f_orifice + f_pale
        moment_total = m_volet - m_orifice + m_pale
        if effort_total <= 0.0:
            raise ValueError("L'effort hydrostatique doit etre strictement positif.")

        # Forme de la fiche: alpha_1*h_png + alpha_0 = 0.
        # alpha_1 regroupe les termes en h_png, alpha_0 les termes constants.
        alpha_1 = -effort_total
        alpha_0 = moment_total
        h_png = -alpha_0 / alpha_1
        self._valider_h_png(h_png, h_w)
        return DeterminationHpng(
            alpha_1=alpha_1,
            alpha_0=alpha_0,
            effort=effort_total,
            moment=moment_total,
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


def construire_vanne(DN: float, aG: float, b_G: float, **options: float) -> ConstructionVanneCirculaire:
    return ConstructeurVanneCirculaire(DN=DN, aG=aG, b_G=b_G, **options).construire()


def _chemin_sortie(chemin: str | Path) -> Path:
    chemin = Path(chemin)
    if chemin.is_absolute():
        return chemin
    return DOSSIER_PROGRAMME / chemin


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

    _tracer_rectangle_centre_dans_cercle(
        ax,
        circulaire,
        construction.y_volet,
        construction.b_w,
        "#d8b6b6",
        "volet inferieur",
    )
    _tracer_rectangle_centre(
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

    for y, label in [
        (construction.aG, "aG"),
        (construction.y_axe_bas, "h_png"),
        (construction.y_volet, "h_w"),
        (construction.y_pale_bas, "bas pale"),
        (construction.y_basculement, "0.8 DN"),
        (construction.y_haut, "haut pale"),
        (construction.DN, "DN"),
    ]:
        _tracer_ligne_cote(ax, circulaire, y, label)

    ax.axvline(0.0, color="#6c757d", linestyle="--", linewidth=0.8)
    ax.set_title(
        f"Construction VSR circulaire - DN={construction.DN:g}, "
        f"aG={construction.aG:g}, bG={construction.b_G:g}"
    )
    ax.set_xlabel("x")
    ax.set_ylabel("hauteur")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.8)

    marge = 0.08 * construction.DN
    ax.set_xlim(-construction.DN / 2.0 - marge, construction.DN / 2.0 + marge)
    ax.set_ylim(-0.04 * construction.DN, 1.04 * construction.DN)
    fig.tight_layout()
    fig.savefig(chemin, dpi=200)
    plt.close(fig)
    return chemin


def _tracer_rectangle_centre(ax, y0: float, y1: float, largeur: float, couleur: str, label: str) -> None:
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


def _tracer_rectangle_centre_dans_cercle(
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


def _tracer_ligne_cote(ax, circulaire: Circulaire, y: float, label: str) -> None:
    y_controle = min(max(y, 0.0), circulaire.diametre)
    demi = circulaire.largeur(y_controle) / 2.0
    ax.hlines(y, -demi, demi, color="#d62828", linestyle="--", linewidth=0.9)
    ax.text(
        demi + 0.02 * circulaire.diametre,
        y,
        label,
        va="center",
        ha="left",
        color="#7a1f1f",
        fontsize=8,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construit une VSR pour une section circulaire."
    )
    parser.add_argument("DN", type=float, help="Diametre de la conduite circulaire.")
    parser.add_argument("aG", type=float, help="Hauteur de l'orifice inferieur.")
    parser.add_argument("b_G", type=float, help="Largeur de l'orifice inferieur.")
    parser.add_argument("--e", type=float, default=0.0, help="Epaisseur de controle autour de l'orifice.")
    parser.add_argument("--Lup", type=float, default=None, help="Hauteur de la pale. Auto si omis.")
    parser.add_argument("--niveau-volet", type=float, default=0.6, help="Niveau relatif du seuil.")
    parser.add_argument(
        "--niveau-basculement",
        type=float,
        default=0.8,
        help="Niveau relatif du basculement.",
    )
    parser.add_argument("--tolerance", type=float, default=1e-9, help="Tolerance de resolution.")
    parser.add_argument("--csv", default="construction_vanne_ci.csv", help="Chemin du CSV de sortie.")
    parser.add_argument("--png", default="construction_vanne_ci.png", help="Chemin du trace de controle.")
    parser.add_argument("--no-csv", action="store_true", help="Ne pas produire de CSV.")
    parser.add_argument("--no-plot", action="store_true", help="Ne pas produire de PNG.")
    parser.add_argument("--details", action="store_true", help="Affiche le calcul direct de h_png.")
    args = parser.parse_args()

    constructeur = ConstructeurVanneCirculaire(
        DN=args.DN,
        aG=args.aG,
        b_G=args.b_G,
        e=args.e,
        L_up=args.Lup,
        niveau_volet=args.niveau_volet,
        niveau_basculement=args.niveau_basculement,
        tolerance=args.tolerance,
    )
    construction = constructeur.construire()

    for nom, valeur in construction.lignes_csv():
        print(f"{nom:16s} {valeur:.9f}")

    for alerte in construction.alertes:
        print(f"ALERTE: {alerte}", file=sys.stderr)

    if args.details:
        d = construction.determination_hpng
        print()
        print("determination directe de h_png")
        print("equation: alpha_1*h_png + alpha_0 = 0")
        print(f"alpha_1={d.alpha_1:.9f}")
        print(f"alpha_0={d.alpha_0:.9f}")
        print(f"effort={d.effort:.9f}")
        print(f"moment={d.moment:.9f}")
        print(f"h_png=-alpha_0/alpha_1={d.h_png:.9f}")
        print(f"b_w={d.b_w:.9f}")

    if not args.no_csv:
        chemin_csv = exporter_csv(construction, args.csv)
        print(f"Construction exportee dans {chemin_csv}")

    if not args.no_plot:
        chemin_png = tracer(construction, args.png)
        print(f"Trace exporte dans {chemin_png}")


if __name__ == "__main__":
    main()
