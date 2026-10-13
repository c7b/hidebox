#!/bin/bash
# SPDX-License-Identifier: MIT
# Runs the suites as build from /home/build/work/upgrade-046/src; one log per suite, rc in logs/done.
W=/home/build/work/upgrade-046; cd $W/src || exit 1
: > $W/logs/done
run() { local name=$1; shift; echo "== $name: $*" > $W/logs/$name.log; "$@" >> $W/logs/$name.log 2>&1; echo "$name:$?" >> $W/logs/done; }
run core python3 -I web/app/tests/run_all.py
run sidecar env MUTIS_SIDECAR_DIR=$PWD/web/app python3 -I -m unittest discover -s server/tests -p test_real_sidecar.py -v
run gate-chain python3 -I web/app/tests/headless.py --page /app/tests/gates/chain.html --indexer --fragment 'mode=addr'
run server python3 -I -m unittest discover -s server/tests -v
run deploy python3 -I -m unittest discover -s deploy/tests -v
run lint python3 -I tools/lint.py --root .
run copy python3 -I tools/check-copy.py --root .
run site python3 -I web/site/tests/run.py
run ui python3 -I web/app/ui/tests/run.py
echo all-finished >> $W/logs/done
