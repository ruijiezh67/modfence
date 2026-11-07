# Data: Fisher's Iris

`data/iris.csv` is the UCI Machine Learning Repository copy of the Iris dataset, unchanged except for format.

| Field | Value |
|---|---|
| Source file | https://archive.ics.uci.edu/ml/machine-learning-databases/iris/iris.data |
| Dataset page | https://archive.ics.uci.edu/dataset/53/iris |
| Retrieved | 2026-11-07 |
| SHA-256 of the downloaded `iris.data` | `6f608b71a7317216319b4d27b4d9bc84e6abd734eda7872b71a458569e2656c0` |
| License | Creative Commons Attribution 4.0 International (CC BY 4.0), as stated on the dataset page |
| Citation | Fisher, R. (1936). Iris [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C56C76 |
| Original paper | Fisher, R.A. "The use of multiple measurements in taxonomic problems". Annals of Eugenics, 7, Part II, 179-188 (1936) |

## Contents

150 rows, 50 per class, no missing values. Columns:

| Column | Meaning |
|---|---|
| `sepal_length` | sepal length in cm |
| `sepal_width` | sepal width in cm |
| `petal_length` | petal length in cm |
| `petal_width` | petal width in cm |
| `species` | `Iris-setosa`, `Iris-versicolor` or `Iris-virginica` |

## What was changed from the download

- Added the header row `sepal_length,sepal_width,petal_length,petal_width,species` (the UCI file has none).
- Dropped the trailing empty line at the end of the UCI file.
- No values were edited. Row order is the UCI order, so data row N of the CSV is UCI sample N.

## Known discrepancy with Fisher's paper

The UCI copy differs from the data printed in Fisher's 1936 article in two samples. Both the dataset page and the `iris.names` file that ships with the data say so (identified by Steve Chadwick):

| Sample | UCI copy (this file) | Fisher's paper | Differing features |
|---|---|---|---|
| 35 | `4.9,3.1,1.5,0.1,Iris-setosa` | `4.9,3.1,1.5,0.2,Iris-setosa` | 4th (petal width) |
| 38 | `4.9,3.1,1.5,0.1,Iris-setosa` | `4.9,3.6,1.4,0.1,Iris-setosa` | 2nd and 3rd (sepal width, petal length) |

The "UCI copy" column was checked against the downloaded file; the "Fisher's paper" column is quoted from the UCI note, not checked against the 1936 paper itself. This project keeps the UCI values as they are, so its results are comparable to the many published results that use the UCI copy.
