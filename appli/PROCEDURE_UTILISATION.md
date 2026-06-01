# Procedure d'utilisation

## Principe

L'utilisateur utilise seulement :

```text
appli\parametres_vanne.xlsx
```

et une seule fonction Python :

```python
lancer_construction()
```

## 1. Remplir le fichier Excel

Ouvre `appli\parametres_vanne.xlsx` dans Excel.

Le fichier est organise en deux colonnes :

```text
parametre              valeur
section                circulaire ou ovoide
DN                     diametre ou hauteur de reference
aG                     hauteur de l'orifice
bG                     largeur de l'orifice, vide si ovoide
rapport_seuil          0.6 en circulaire, 0.7 en ovoide
rapport_basculement    0.8 en circulaire, 0.9 en ovoide
```

Les deux rapports peuvent rester vides. Dans ce cas, le programme applique
automatiquement les valeurs usuelles :

```text
Circulaire : rapport_seuil = 0.6, rapport_basculement = 0.8
Ovoide     : rapport_seuil = 0.7, rapport_basculement = 0.9
```

Enregistre le fichier Excel avant de lancer le calcul.

## 2. Lancer la construction

Depuis Python :

```python
from construction_vanne_générale import lancer_construction

lancer_construction()
```

Ou depuis PowerShell, si tu preferes lancer directement le script :

```powershell
cd "C:\Users\rapha\Documents\A&M\stage\codex"
py -B construction_vanne_générale.py
```

Si le fichier Excel n'existe pas encore, la fonction le cree automatiquement.
Il suffit alors de le remplir, de l'enregistrer, puis de relancer :

```powershell
py -B construction_vanne_générale.py
```

Les fichiers de sortie sont crees dans le dossier `appli` :

```text
VSR_section_DN..._aG..._bG..._cotes.csv
VSR_section_DN..._aG..._bG....png
```

Le fichier CSV contient toutes les cotes. Le fichier PNG contient le trace de controle.
