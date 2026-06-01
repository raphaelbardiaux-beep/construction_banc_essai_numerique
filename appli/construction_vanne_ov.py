from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, fields
from pathlib import Path

from appli.abaque_ovoide import Ovoide
from appli.determination_hpng_ov import (
    DeterminationHpngOvoide,
    IterationHpng,
    ResultatHpng,
)


DOSSIER_PROGRAMME = Path(__file__).resolve().parent


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
        return [
            (champ.name, getattr(self, champ.name))
            for champ in fields(self)
            if champ.name not in {"iterations", "alertes"}
        ]


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
        L_up: float = 0.15,
        ratio_ovoide: float = 1.5,
        niveau_volet: float = 0.7,
        niveau_haut: float = 0.9,
        ratio_hup_lup: float = 0.75,
        tolerance: float = 1e-9,
        max_iterations: int = 100,
        ratio_initial: float = 0.5,
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

    def construire(self) -> ConstructionVanneOvoide:
        resultat_reference = self.solveur.determiner()
        y_haut = (
            resultat_reference.aG
            + resultat_reference.h_w
            + resultat_reference.a_w
            + resultat_reference.L_up
        )
        b_w = self.ovoide.largeur(y_haut)
        h_png = self.solveur._resoudre_h_png_pour_bw(b_w)
        b_w_hpng = self.ovoide.largeur(resultat_reference.aG + h_png)
        residu = self.solveur.equation_avec_bw(h_png, b_w)
        iterations = (
            IterationHpng(
                iteration=1,
                b_w_entree=b_w,
                h_png=h_png,
                y_bw=resultat_reference.aG + h_png,
                b_w=b_w,
                ecart_h_png=0.0,
                ecart_b_w=0.0,
                residu=residu,
            ),
        )
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

    def _controler_largeurs(self, construction: ConstructionVanneOvoide) -> None:
        b_w_hpng_abaque = self.ovoide.largeur(construction.y_axe_bas)
        if abs(b_w_hpng_abaque - construction.b_w_hpng) > self.solveur.tolerance * 10.0:
            raise RuntimeError(
                "Incoherence de largeur b_w_hpng entre l'abaque et la determination "
                f"h_png: {b_w_hpng_abaque:.9f} != {construction.b_w_hpng:.9f}."
            )
        b_w_abaque = self.ovoide.largeur(construction.y_haut)
        if abs(b_w_abaque - construction.b_w) > self.solveur.tolerance * 10.0:
            raise RuntimeError(
                "Incoherence de largeur b_w entre l'abaque et la construction "
                f"{b_w_abaque:.9f} != {construction.b_w:.9f}."
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
            ),
            (
                "volet superieur",
                construction.y_axe_bas,
                construction.y_volet,
                construction.b_w,
                construction.b_w,
                False,
            ),
        ]

        alertes: list[str] = []
        for nom, y0, y1, largeur0, largeur1, ignorer_haut in controles:
            marge_min, y_marge = self._marge_minimale(y0, y1, largeur0, largeur1, ignorer_haut)
            if marge_min + self.solveur.tolerance < construction.e:
                alertes.append(
                    f"Ecart insuffisant entre la paroi et {nom}: "
                    f"{marge_min:.6g} a y={y_marge:.6g}, e={construction.e:.6g}."
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


def construire_vanne(T: float, aG: float, **options: float) -> ConstructionVanneOvoide:
    return ConstructeurVanneOvoide(T=T, aG=aG, **options).construire()


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

    _tracer_trapeze_centre(
        ax,
        construction.y_orifice,
        construction.y_axe_bas,
        construction.b_s,
        construction.b_w,
        "#d8b6b6",
        "volet inferieur",
    )
    _tracer_rectangle_centre(
        ax,
        construction.y_axe_bas,
        construction.y_volet,
        construction.b_w,
        "#d8b6b6",
        "volet superieur",
    )
    _tracer_rectangle_centre(
        ax,
        construction.y_pale_bas,
        construction.y_haut,
        construction.b_w,
        "#c8d9ea",
        "pale haute",
    )

    lignes_cotes = [
        (construction.y_orifice, "aG"),
        (construction.y_axe_bas, "aG + h_png"),
        (construction.y_volet, "aG + h_w"),
        (construction.y_pale_bas, "bas pale"),
        (construction.y_basculement, "basculement"),
        (construction.y_haut, f"{construction.y_haut / construction.T:g}DN"),
        (construction.T, "DN"),
    ]
    for y, label, y_texte in _placer_etiquettes(lignes_cotes, construction.T):
        _tracer_ligne_cote(ax, ovoide, y, label, y_texte)

    ax.axvline(0.0, color="#6c757d", linestyle="--", linewidth=0.8)
    ax.set_title(f"Construction VSR ovoide - DN={construction.T:g}, aG={construction.aG:g}")
    ax.set_xlabel("x")
    ax.set_ylabel("hauteur")
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


def _tracer_trapeze_centre(
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


def _tracer_ligne_cote(ax, ovoide: Ovoide, y: float, label: str, y_texte: float | None = None) -> None:
    y_controle = min(max(y, 0.0), ovoide.hauteur_totale)
    demi = ovoide.largeur(y_controle) / 2.0
    ax.hlines(y, -demi, demi, color="#d62828", linestyle="--", linewidth=0.9)
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construit une VSR pour une section ovoide quelconque."
    )
    parser.add_argument("T", type=float, help="Hauteur totale de la conduite ovoide.")
    parser.add_argument("aG", type=float, help="Hauteur de l'orifice.")
    parser.add_argument("--e", type=float, default=0.1, help="Epaisseur du cadre.")
    parser.add_argument("--Lup", type=float, default=0.15, help="Hauteur fixe de la pale.")
    parser.add_argument("--ratio-ovoide", type=float, default=1.5, help="Ratio T/B de l'ovoide.")
    parser.add_argument("--niveau-volet", type=float, default=0.7, help="Niveau relatif du haut du volet.")
    parser.add_argument("--niveau-haut", type=float, default=0.9, help="Niveau relatif du haut de la pale.")
    parser.add_argument("--ratio-hup-lup", type=float, default=0.75, help="Position relative du basculement.")
    parser.add_argument("--tolerance", type=float, default=1e-9, help="Tolerance de resolution.")
    parser.add_argument("--max-iterations", type=int, default=100, help="Nombre maximal d'iterations.")
    parser.add_argument(
        "--ratio-initial",
        type=float,
        default=0.5,
        help="Premier essai: h_png_initial = ratio_initial*h_w.",
    )
    parser.add_argument("--csv", default="construction_vanne_ov.csv", help="Chemin du CSV de sortie.")
    parser.add_argument("--png", default="construction_vanne_ov.png", help="Chemin du trace de controle.")
    parser.add_argument("--no-csv", action="store_true", help="Ne pas produire de CSV.")
    parser.add_argument("--no-plot", action="store_true", help="Ne pas produire de PNG.")
    parser.add_argument("--iterations", action="store_true", help="Affiche les iterations de h_png.")
    args = parser.parse_args()

    constructeur = ConstructeurVanneOvoide(
        T=args.T,
        aG=args.aG,
        e=args.e,
        L_up=args.Lup,
        ratio_ovoide=args.ratio_ovoide,
        niveau_volet=args.niveau_volet,
        niveau_haut=args.niveau_haut,
        ratio_hup_lup=args.ratio_hup_lup,
        tolerance=args.tolerance,
        max_iterations=args.max_iterations,
        ratio_initial=args.ratio_initial,
    )
    construction = constructeur.construire()

    for nom, valeur in construction.lignes_csv():
        print(f"{nom:16s} {valeur:.9f}")

    for alerte in construction.alertes:
        print(f"ALERTE: {alerte}", file=sys.stderr)

    if args.iterations:
        print()
        print("iterations")
        for iteration in construction.iterations:
            print(
                f"{iteration.iteration:3d} "
                f"b_w_in={iteration.b_w_entree:.9f} "
                f"h_png={iteration.h_png:.9f} "
                f"aG+h_png={iteration.y_bw:.9f} "
                f"b_w={iteration.b_w:.9f} "
                f"dh={iteration.ecart_h_png:.3e} "
                f"dbw={iteration.ecart_b_w:.3e} "
                f"residu={iteration.residu:.3e}"
            )

    if not args.no_csv:
        chemin_csv = exporter_csv(construction, args.csv)
        print(f"Construction exportee dans {chemin_csv}")

    if not args.no_plot:
        chemin_png = tracer(construction, args.png)
        print(f"Trace exporte dans {chemin_png}")


if __name__ == "__main__":
    main()
