from __future__ import annotations

import argparse

from construction_vanne_ov import ConstructeurVanneOvoide, exporter_csv, tracer


def determiner_lup(T: float) -> float:
    if 1.0 < T < 1.5:
        return 0.1
    if 1.5 <= T < 2.5:
        return 0.15
    if 2.5 <= T:
        return 0.2
    raise ValueError("T doit etre strictement superieur a 1.0 pour appliquer la regle Lup.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construit une VSR ovoide avec Lup choisi automatiquement selon T."
    )
    parser.add_argument("T", type=float, help="Hauteur totale de la conduite ovoide.")
    parser.add_argument("aG", type=float, help="Hauteur de l'orifice.")
    parser.add_argument("--e", type=float, default=0.1, help="Epaisseur du cadre.")
    parser.add_argument("--csv", default="construction_vanne_ov_lup_auto.csv", help="Chemin du CSV de sortie.")
    parser.add_argument("--png", default="construction_vanne_ov_lup_auto.png", help="Chemin du trace de controle.")
    parser.add_argument("--no-csv", action="store_true", help="Ne pas produire de CSV.")
    parser.add_argument("--no-plot", action="store_true", help="Ne pas produire de PNG.")
    parser.add_argument("--iterations", action="store_true", help="Affiche les iterations de h_png.")
    args = parser.parse_args()

    L_up = determiner_lup(args.T)
    constructeur = ConstructeurVanneOvoide(T=args.T, aG=args.aG, e=args.e, L_up=L_up)
    construction = constructeur.construire()

    print(f"L_up automatique {L_up:.6f}")
    for nom, valeur in construction.lignes_csv():
        print(f"{nom:16s} {valeur:.9f}")

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

    for alerte in construction.alertes:
        print(f"ALERTE: {alerte}")

    if not args.no_csv:
        chemin_csv = exporter_csv(construction, args.csv)
        print(f"Construction exportee dans {chemin_csv}")

    if not args.no_plot:
        chemin_png = tracer(construction, args.png)
        print(f"Trace exporte dans {chemin_png}")


if __name__ == "__main__":
    main()
