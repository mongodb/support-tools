#!/bin/bash
# USAGE: stacks.sh
 
DELAY=15
SAMPLES=10

hostname=$(hostname -f)
dstdir="/tmp/${hostname}-stacks"
 
mkdir -p 
$dstdir
for i in $(seq 1 $SAMPLES); do
   sudo gdb -p $(pidof mongod) -batch -ex 'thread apply all bt' > 
$dstdir
/stacks-$(date '+%Y-%m-%dT%H-%M-%S').txt
   sleep $DELAY
done

