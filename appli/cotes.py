from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, fields
from pathlib import Path

try:
    from .abaque_ovoide import Ovoide, Point
except ImportError:  # Execution directe: python appli/cotes.py
    from abaque_ovoide import Ovoide, Point


DOSSIER_PROGRAMME = Path(__file__).resolve().parent


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
        return [(champ.name, getattr(self, champ.name)) for champ in fields(self)]


class GeometrieVanne:
    """
    Geometrie parametrique d'une vanne en conduite ovoide.

    Entrees minimales:
    - T: hauteur totale de conduite
    - aG: hauteur de l'orifice

    Formules reprises de la fiche:
    - B = T / 1.5 pour le gabarit ovoide 1.5
    - e = 0.1
    - L_up = 0.15
    - h_w = 0.7*T - aG
    - h_up = 0.75*L_up, position du basculement depuis le bas de la pale
    - a_w = 0.9*T - L_up - h_w - aG
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
        L_up: float = 0.15,
        ratio_ovoide: float = 1.5,
        niveau_volet: float = 0.7,
        niveau_haut: float = 0.9,
        ratio_hup_lup: float = 0.75,
        ratio_axe: float = 0.5,
    ) -> None:
        self.T = T
        self.aG = aG
        self.e = e
        self.L_up = L_up
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
        if self.niveau_haut * self.T - self.L_up < self.niveau_volet * self.T:
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
        niveau_haut = self.niveau_haut * self.T
        y_pale_bas = niveau_haut - self.L_up

        L_up = self.L_up
        h_up = self.ratio_hup_lup * L_up
        h_w = niveau_volet - self.aG
        a_w = y_pale_bas - h_w - self.aG

        h_png = self.ratio_axe * h_w
        P_w = h_w - h_png
        h_pngup = a_w + h_up

        y_volet = self.aG + h_w
        y_basculement = y_pale_bas + h_up
        y_haut = niveau_haut

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

    def contour_conduite(self) -> list[Point]:
        return self.ovoide.contour()

    def niveaux(self) -> dict[str, float]:
        c = self.cotes
        return {
            "bas": 0.0,
            "aG": c.y_orifice,
            "axe_bas": c.y_orifice + c.h_png,
            "volet": c.y_volet,
            "bas_pale": c.y_basculement - c.h_up,
            "basculement": c.y_basculement,
            "haut": c.y_haut,
            "T": c.T,
        }

    def exporter_csv(self, chemin: str | Path = "cotes_vanne.csv") -> Path:
        chemin = Path(chemin)
        if not chemin.is_absolute():
            chemin = DOSSIER_PROGRAMME / chemin

        with chemin.open("w", newline="", encoding="utf-8") as fichier:
            writer = csv.writer(fichier, delimiter=";")
            writer.writerow(["cote", "valeur"])
            writer.writerows((nom, f"{valeur:.6f}") for nom, valeur in self.cotes.lignes_csv())

        return chemin

    def tracer(self, chemin: str | Path = "vanne_ovoide.png") -> Path:
        try:
            import matplotlib.pyplot as plt
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "matplotlib n'est pas installe. Installe-le avec: pip install matplotlib"
            ) from exc

        chemin = Path(chemin)
        if not chemin.is_absolute():
            chemin = DOSSIER_PROGRAMME / chemin

        c = self.cotes
        contour = self.contour_conduite()
        xs = [p.x for p in contour]
        ys = [p.y for p in contour]

        fig, ax = plt.subplots(figsize=(6, 7))
        ax.plot(xs, ys, color="black", linewidth=2.0)
        ax.fill(xs, ys, color="#edf3f8", alpha=0.85)

        y_axe_bas = c.y_orifice + c.h_png
        y_pale_bas = c.y_basculement - c.h_up

        self._tracer_trapeze_centre(
            ax,
            c.y_orifice,
            y_axe_bas,
            c.b_s,
            c.b_w,
            "#d8b6b6",
            "volet inferieur",
        )
        self._tracer_rectangle_centre(ax, y_axe_bas, c.y_volet, c.b_w, "#d8b6b6", "volet superieur")
        self._tracer_rectangle_centre(
            ax,
            y_pale_bas,
            c.y_haut,
            c.b_w,
            "#d8b6b6",
            "pale haute",
        )
        self._tracer_ligne_cote(ax, c.y_orifice, "aG")
        self._tracer_ligne_cote(ax, y_axe_bas, "hpng")
        self._tracer_ligne_cote(ax, c.y_volet, "aG + h_w")
        self._tracer_ligne_cote(ax, c.y_basculement, "basculement")
        self._tracer_ligne_cote(ax, c.y_haut, "0.9 T")
        self._tracer_ligne_cote(ax, c.T, "T")

        ax.axvline(0.0, color="#6c757d", linestyle="--", linewidth=0.8)
        ax.set_title(f"Vanne ovoide - T={c.T:g}, aG={c.aG:g}")
        ax.set_xlabel("x")
        ax.set_ylabel("hauteur")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, linestyle=":", linewidth=0.8)

        marge = 0.08 * c.T
        ax.set_xlim(-c.B / 2.0 - marge, c.B / 2.0 + marge)
        ax.set_ylim(-0.04 * c.T, 1.04 * c.T)
        fig.tight_layout()
        fig.savefig(chemin, dpi=200)
        plt.close(fig)
        return chemin

    def _tracer_rectangle_centre(self, ax, y0: float, y1: float, largeur: float, couleur: str, label: str) -> None:
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
        self,
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

    def _tracer_ligne_cote(self, ax, y: float, label: str) -> None:
        demi = self._largeur_utile(min(max(y, 0.0), self.T)) / 2.0
        ax.hlines(y, -demi, demi, color="#d62828", linestyle="--", linewidth=0.9)
        ax.text(demi + 0.02 * self.T, y, label, va="center", ha="left", color="#7a1f1f", fontsize=8)


def construire_cotes(T: float, aG: float, **options: float) -> CotesVanne:
    return GeometrieVanne(T=T, aG=aG, **options).cotes


def main() -> None:
    parser = argparse.ArgumentParser(description="Calcule les cotes d'une VSR en section ovoide.")
    parser.add_argument("T", type=float, help="Hauteur totale de la conduite.")
    parser.add_argument("aG", type=float, help="Hauteur de l'orifice.")
    parser.add_argument("--e", type=float, default=0.1, help="Epaisseur du cadre.")
    parser.add_argument("--Lup", type=float, default=0.15, help="Hauteur fixe de la pale.")
    parser.add_argument(
        "--ratio-axe",
        type=float,
        default=0.5,
        help="Position de l'axe inferieur: h_png = ratio_axe*h_w.",
    )
    parser.add_argument("--csv", default="cotes_vanne.csv", help="Chemin du CSV de sortie.")
    parser.add_argument("--png", default="vanne_ovoide.png", help="Chemin du trace de controle.")
    parser.add_argument("--no-plot", action="store_true", help="Ne pas produire de trace PNG.")
    args = parser.parse_args()

    geometrie = GeometrieVanne(T=args.T, aG=args.aG, e=args.e, L_up=args.Lup, ratio_axe=args.ratio_axe)

    for nom, valeur in geometrie.cotes.lignes_csv():
        print(f"{nom:15s} {valeur:.6f}")

    csv_path = geometrie.exporter_csv(args.csv)
    print(f"Cotes exportees dans {csv_path}")

    if not args.no_plot:
        png_path = geometrie.tracer(args.png)
        print(f"Trace exporte dans {png_path}")


if __name__ == "__main__":
    main()
