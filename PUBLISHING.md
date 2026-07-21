# Publishing NEXCISION

## Create the repository

Create a public GitHub repository named `nexcision`, then run:

```bash
git init
git add .
git commit -m "Initial release: NEXCISION v0.1.0"
git branch -M main
git remote add origin https://github.com/RhysWhite/nexcision.git
git push -u origin main
```

## Create the first release

```bash
git tag -a v0.1.0 -m "NEXCISION v0.1.0"
git push origin v0.1.0
```

Suggested GitHub description:

> Precise region-based excision of coordinate-labelled rows from NEXUS matrices.

Suggested topics:

`bioinformatics`, `genomics`, `nexus`, `phylogenetics`, `recombination`, `python`
