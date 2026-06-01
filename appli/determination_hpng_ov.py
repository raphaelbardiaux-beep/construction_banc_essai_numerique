from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

try:
    from .abaque_ovoide import Ovoide
    from .cotes import GeometrieVanne
except ImportError:  # Execution directe: python appli/determination_hpng_ov.py
    from abaque_ovoide import Ovoide
    from cotes import GeometrieVanne


DOSSIER_PROGRAMME = Path(__file__).resolve().parent


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
        L_up: float = 0.15,
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
        self.L_up = L_up
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
            L_up=L_up,
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
        hw = c.h_w
        hup = c.h_up
        hpngup = c.h_pngup

        k1 = (
            3.0 * hup**2 * (hpngup + hw)
            - 2.0 * hup**3
            + 3.0 * hpngup * hw**2
            + hw**3
        ) / 6.0
        k2 = (3.0 * hup**2 + 3.0 * hw * (hw + 2.0 * hpngup)) / 6.0

        return (
            (3.0 * b_w + bs) * h_png**3
            - 2.0 * (hpngup + hw) * (2.0 * b_w + bs) * h_png**2
            + 12.0 * b_w * k2 * h_png
            - 12.0 * b_w * k1
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


def determiner_hpng(T: float, aG: float, **options: float) -> ResultatHpng:
    return DeterminationHpngOvoide(T=T, aG=aG, **options).determiner()


def exporter_csv(resultat: ResultatHpng, chemin: str | Path = "hpng_ovoide.csv") -> Path:
    chemin = Path(chemin)
    if not chemin.is_absolute():
        chemin = DOSSIER_PROGRAMME / chemin

    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        writer = csv.writer(fichier, delimiter=";")
        writer.writerow(["cote", "valeur"])
        writer.writerows((nom, f"{valeur:.9f}") for nom, valeur in resultat.lignes_csv())
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
        for iteration in resultat.iterations:
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

    return chemin


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Determine h_png pour une VSR en section ovoide."
    )
    parser.add_argument("T", type=float, help="Hauteur totale de la conduite.")
    parser.add_argument("aG", type=float, help="Hauteur de l'orifice.")
    parser.add_argument("--e", type=float, default=0.1, help="Epaisseur du cadre.")
    parser.add_argument("--Lup", type=float, default=0.15, help="Hauteur fixe de la pale.")
    parser.add_argument("--tolerance", type=float, default=1e-9, help="Tolerance de resolution.")
    parser.add_argument("--max-iterations", type=int, default=100, help="Nombre maximal d'iterations.")
    parser.add_argument(
        "--ratio-initial",
        type=float,
        default=0.5,
        help="Premier essai: h_png_initial = ratio_initial*h_w.",
    )
    parser.add_argument("--csv", default="hpng_ovoide.csv", help="Chemin du CSV de sortie.")
    parser.add_argument("--no-csv", action="store_true", help="Ne pas produire de CSV.")
    parser.add_argument(
        "--iterations",
        action="store_true",
        help="Affiche les iterations avec actualisation de b_w.",
    )
    args = parser.parse_args()

    solveur = DeterminationHpngOvoide(
        T=args.T,
        aG=args.aG,
        e=args.e,
        L_up=args.Lup,
        tolerance=args.tolerance,
        max_iterations=args.max_iterations,
        ratio_initial=args.ratio_initial,
    )
    resultat = solveur.determiner()

    for nom, valeur in resultat.lignes_csv():
        print(f"{nom:12s} {valeur:.9f}")

    if args.iterations:
        print()
        print("iterations")
        for iteration in resultat.iterations:
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
        chemin = exporter_csv(resultat, args.csv)
        print(f"Resultat exporte dans {chemin}")


if __name__ == "__main__":
    main()
