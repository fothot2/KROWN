# Virtuoso Open Source 7.2.17 container

This Docker context builds the Virtuoso server used by KROWN. It downloads the official 7.2.17 generic Linux archive and verifies its SHA-256 value before extraction.

The image tag is `kgconstruct/virtuoso:v7.2.17`. The binary reports `7.2.17.3243` and build commit `c4fd28e38e`. The image installs `libncurses5` because the official `isql` binary requires `libncurses.so.5`.

The `/database` volume stores the database. The `/usr/share/proj` mount provides RDF input. Ports 1111 and 8890 expose SQL and SPARQL services. Environment variables named `VIRT_<section>_<key>` update `virtuoso.ini` during first initialization.

Docker Compose is optional. KROWN uses its own Docker abstraction for experiments.
