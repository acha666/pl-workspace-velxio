# Source

Based on [Velxio revision 94fd947](https://github.com/davidmonterocrespo24/velxio/tree/94fd947d6d85afddc7e66c927c7d494e7759f55b) and its `Dockerfile.standalone`. The workspace target keeps the official frontend/Python/nginx design. Both images copy Arduino CLI from the official image pinned in `toolchain.lock.json`; the grader also links [simavr](https://github.com/buserror/simavr) (GNU GPL v3) from the commit pinned there.

Velxio, this adapter and the grader use [GNU AGPL v3](LICENSE). The workspace's **Source & licenses** link serves `workspace/` (adapter, patches and dependency locks) and the build inputs; the exact upstream source is [available here](https://github.com/davidmonterocrespo24/velxio/archive/94fd947d6d85afddc7e66c927c7d494e7759f55b.tar.gz). Course templates, the grader, test solutions and student work are excluded from that archive; the grader is published in this repository. Dependency licenses remain with their respective projects.
