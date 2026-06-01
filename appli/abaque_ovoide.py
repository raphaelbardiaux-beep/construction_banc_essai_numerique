from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import csv
import math


DOSSIER_PROGRAMME = Path(__file__).resolve().parent


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

    def abaque(self, pas: float = 0.01) -> list[tuple[float, float]]:
        """Construit une table [(hauteur, largeur), ...]."""
        if pas <= 0.0:
            raise ValueError("Le pas doit etre positif.")

        table: list[tuple[float, float]] = []
        n = int(round(self.hauteur_totale / pas))
        for i in range(n + 1):
            y = min(i * pas, self.hauteur_totale)
            table.append((y, self.largeur(y)))
        if table[-1][0] < self.hauteur_totale:
            table.append((self.hauteur_totale, self.largeur(self.hauteur_totale)))
        return table

    def exporter_csv(self, chemin: str | Path = "abaque_ovoide.csv", pas: float = 0.01) -> None:
        """Exporte l'abaque hauteur/largeur dans un fichier CSV."""
        chemin = self._chemin_sortie(chemin)
        with chemin.open("w", newline="", encoding="utf-8") as fichier:
            writer = csv.writer(fichier, delimiter=";")
            writer.writerow(["hauteur", "largeur"])
            writer.writerows((f"{h:.5f}", f"{l:.5f}") for h, l in self.abaque(pas))

    def contour(self) -> list[Point]:
        """Retourne le contour complet de l'ovoide, dans le sens horaire."""
        cote_droit = self.points_droits
        cote_gauche = [Point(-p.x, p.y) for p in reversed(cote_droit)]
        return cote_droit + cote_gauche

    def tracer(
        self,
        hauteur: float | None = None,
        chemin: str | Path = "ovoide.png",
        afficher_construction: bool = True,
    ) -> None:
        """Trace l'ovoide avec matplotlib et enregistre l'image."""
        try:
            import matplotlib.pyplot as plt
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "matplotlib n'est pas installe. Installe-le avec: pip install matplotlib"
            ) from exc

        chemin = self._chemin_sortie(chemin)
        contour = self.contour()
        xs = [p.x for p in contour]
        ys = [p.y for p in contour]

        fig, ax = plt.subplots(figsize=(5, 7))
        ax.plot(xs, ys, color="black", linewidth=2.0, label="Contour ovoide")
        ax.fill(xs, ys, color="#dcecff", alpha=0.45)

        if afficher_construction:
            self._tracer_construction(ax)

        if hauteur is not None:
            largeur = self.largeur(hauteur)
            demi = largeur / 2.0
            ax.hlines(hauteur, -demi, demi, colors="#d62828", linewidth=2.0)
            ax.scatter([-demi, demi], [hauteur, hauteur], color="#d62828", zorder=3)
            ax.text(
                0.0,
                hauteur + 0.035,
                f"h = {hauteur:.2f}, largeur = {largeur:.3f}",
                ha="center",
                va="bottom",
                color="#d62828",
            )

        ax.axvline(0.0, color="gray", linewidth=0.8, linestyle="--")
        ax.set_title("Ovoide discretisee")
        ax.set_xlabel("x")
        ax.set_ylabel("hauteur y")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, linestyle=":", linewidth=0.8)
        marge = 0.10 * self.hauteur_totale
        demi_largeur_max = max(abs(p.x) for p in contour)
        ax.set_xlim(-demi_largeur_max - marge, demi_largeur_max + marge)
        ax.set_ylim(-0.05 * self.hauteur_totale, 1.05 * self.hauteur_totale)
        fig.tight_layout()
        fig.savefig(chemin, dpi=200)
        plt.show()

    def _tracer_construction(self, ax) -> None:
        from matplotlib.patches import Circle

        centres = [
            (self.top_center, self.r_top, "haut R=0.5"),
            (self.bottom_center, self.r_bottom, "bas R=0.25"),
            (self.side_center, self.r_side, "flanc R=1.5"),
            (Point(-self.side_center.x, self.side_center.y), self.r_side, "flanc R=1.5"),
        ]
        for centre, rayon, label in centres:
            cercle = Circle(
                (centre.x, centre.y),
                rayon,
                fill=False,
                linestyle="--",
                linewidth=0.8,
                color="#6c757d",
                alpha=0.45,
            )
            ax.add_patch(cercle)
            ax.scatter([centre.x], [centre.y], color="#495057", s=18, zorder=4)
            ax.text(
                centre.x,
                centre.y,
                label,
                fontsize=8,
                ha="center",
                va="bottom",
                color="#495057",
            )

        points_remarquables = [
            self.bottom,
            self.tangent_bottom,
            self.tangent_top,
            Point(-self.tangent_bottom.x, self.tangent_bottom.y),
            Point(-self.tangent_top.x, self.tangent_top.y),
        ]
        ax.scatter(
            [p.x for p in points_remarquables],
            [p.y for p in points_remarquables],
            color="#2b8a3e",
            s=16,
            zorder=5,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calcule et trace une ovoide mise a l'echelle.")
    parser.add_argument(
        "--hauteur-ovoide",
        type=float,
        default=1.5,
        help="Hauteur totale de l'ovoide. Reference du croquis: 1.5.",
    )
    parser.add_argument(
        "--hauteur-mesure",
        type=float,
        default=None,
        help="Hauteur a laquelle calculer la largeur. Par defaut: moitie de la hauteur totale.",
    )
    parser.add_argument(
        "--pas",
        type=float,
        default=None,
        help="Pas de l'abaque. Par defaut: hauteur_ovoide / 150.",
    )
    args = parser.parse_args()

    ovoide = Ovoide(hauteur_totale=args.hauteur_ovoide)

    hauteur = args.hauteur_mesure
    if hauteur is None:
        hauteur = args.hauteur_ovoide / 2.0

    pas = args.pas
    if pas is None:
        pas = args.hauteur_ovoide / 150.0

    print(f"Largeur pour h = {hauteur:.2f} : {ovoide.largeur(hauteur):.4f}")

    ovoide.exporter_csv("abaque_ovoide.csv", pas=pas)
    print("Abaque exporte dans abaque_ovoide.csv")

    ovoide.tracer(hauteur=hauteur, chemin="ovoide.png")
    print("Trace exporte dans ovoide.png")


if __name__ == "__main__":
    main()
