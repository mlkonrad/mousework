# Copr's "make srpm" build method runs:
#   make -f .copr/Makefile srpm outdir=<dir> spec=<spec path from the form>
# It downloads Source0 (the GitHub release tarball for the spec's Version)
# and builds the source RPM from it, so building from master still ships the
# released code.

spec ?= packaging/rpm/mousework.spec
outdir ?= $(CURDIR)

srpm:
	dnf -y install rpmdevtools rpm-build
	spectool -g -C $(outdir) $(spec)
	rpmbuild -bs --define "_sourcedir $(outdir)" --define "_srcrpmdir $(outdir)" $(spec)

.PHONY: srpm
