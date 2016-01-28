#!/bin/bash

# ===================================
# mdiag.sh: MongoDB Diagnostic Report
# ===================================
#
# Copyright MongoDB, Inc, 2014, 2015, 2016
#
# Gather a wide variety of system and hardware diagnostic information.
#
#
# DISCLAIMER
#
# Please note: all tools/ scripts in this repo are released for use "AS
# IS" without any warranties of any kind, including, but not limited to
# their installation, use, or performance. We disclaim any and all
# warranties, either express or implied, including but not limited to
# any warranty of noninfringement, merchantability, and/ or fitness for
# a particular purpose. We do not warrant that the technology will
# meet your requirements, that the operation thereof will be
# uninterrupted or error-free, or that any errors will be corrected.
#
# Any use of these scripts and tools is at your own risk. There is no
# guarantee that they have been through thorough testing in a
# comparable environment and we are not responsible for any damage
# or data loss incurred with their use.
#
# You are responsible for reviewing and testing any scripts you run
# thoroughly before use in any non-testing environment.
#
#
# LICENSE
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


version="1.6.3"

diagfile="/tmp/mdiag-`hostname`.txt"

msection() {
	section="$1"
	shift
	echo -n "Gathering $section info... "
	(
		echo ""
		echo ""
		echo "=========== start section $section ==========="
		if [ $# -eq 0 ]; then
			eval "`cat`"
		else
			"$@"
		fi
		echo "============ end section $section ============"
	) >> "$diagfile" 2>&1
	echo "done"
}

msubsection() {
	subsection="$1"
	shift
	echo "--> start subsection $subsection <--"
	if [ $# -eq 0 ]; then
		eval "`cat`"
	else
		"$@"
	fi
	echo "--> end subsection $subsection <--"
}

printeach() {
	for i; do
		echo "$i"
	done
}

getfiles() {
	for f; do
		echo ""
		ls -l "$f"
		msubsection "$f" cat "$f"
	done
}

getstdinfiles() {
	while read i; do
		getfiles "$i"
	done
}

getfilesfromcommand() {
	"$@" | getstdinfiles
}

lsfiles() {
	somefiles=
	restfiles=
	for f; do
		if [ "x$restfiles" = "x" ]; then
			case "$f" in
				--) restfiles=y ;;
				-*) ;;
				*)
					somefiles=y
					break
					;;
			esac
		else
			somefiles=y
			break
		fi
	done
	if [ "x$somefiles" != "x" ]; then
		ls -la "$@"
	fi
}


PATH="$PATH${PATH+:}/usr/sbin:/sbin:/usr/bin:/bin"

echo "========================="
echo "MongoDB Diagnostic Report"
echo "mdiag.sh version $version"
echo "========================="
if [ "$1" ]; then
	echo
	echo "Ticket: https://jira.mongodb.org/browse/$1"
fi
echo 
echo "Please wait while diagnostic information is gathered"
echo "into the $diagfile file..."
echo
echo "If the display remains stuck for more than 5 minutes,"
echo "please press Control-C."
echo

[ -e "$diagfile" ] && mv -f "$diagfile" "$diagfile.old"
(
echo "========================="
echo "MongoDB Diagnostic Report"
echo "mdiag.sh version $version"
echo "========================="
) > "$diagfile" 2>&1

shopt -s nullglob >> "$diagfile" 2>&1

# Generic/system/distro/boot info
msection args printeach "$@"
msection date date
msection whoami whoami
msection path echo "$PATH"
msection ld_library_path echo "$LD_LIBRARY_PATH"
msection ld_preload echo "$LD_PRELOAD"
msection pythonpath echo "$PYTHONPATH"
msection pythonhome echo "$PYTHONHOME"
msection distro getfiles /etc/*release /etc/*version
msection uname uname -a
msection glibc lsfiles /lib*/libc.so* /lib/*/libc.so*
msection glibc2 /lib*/libc.so* '||' /lib/*/libc.so*
msection ld.so.conf getfiles /etc/ld.so.conf /etc/ld.so.conf.d/*
msection lsb lsb_release -a
msection rc.local getfiles /etc/rc.local
msection sysctl sysctl -a
msection sysctl.conf getfiles /etc/sysctl.conf /etc/sysctl.d/*
msection ulimit ulimit -a
msection limits.conf getfiles /etc/security/limits.conf /etc/security/limits.d/*
msection selinux sestatus
msection timezone_config getfiles /etc/timezone /etc/sysconfig/clock
msection timedatectl timedatectl
msection localtime lsfiles /etc/localtime
msection localtime_matches find /usr/share/zoneinfo -type f -exec cmp -s \{\} /etc/localtime \; -print

# Block device/filesystem info
msection scsi getfiles /proc/scsi/scsi
DISK_DEVS=$(cat /proc/partitions | awk 'match($4, /^[sh]d[a-z]$/) { print $4 }')
OUT_S=
for disk in $DISK_DEVS; do
  OUT_T="$(udevadm info --query=all --name=$disk | grep 'E: ID_MODEL=')"
  if [ -n "$OUT_S" ]; then
     OUT_S="${OUT_S}, "
  fi
  OUT_S="${OUT_S}${disk}-->${OUT_T##*=}"
done
msection scsi-map echo "$OUT_S"
msection blockdev blockdev --report
msection lsblk lsblk

msection fstab getfiles /etc/fstab
msection mount mount
msection df-h df -h
msection df-k df -k

msection mdstat getfiles /proc/mdstat
msection mdadm_detail_scan mdadm --detail --scan
msection mdadm_detail <<EOF
sed -ne 's,^\(md[0-9]\+\) : .*$,/dev/\1,p' < /proc/mdstat | xargs -n1 --no-run-if-empty mdstat --detail
EOF

msection dmsetup dmsetup ls
msection device_mapper lsfiles -R /dev/mapper /dev/dm-*

# Logical Volume Manage info
msection lvm_pvs pvs -v
msection lvm_vgs vgs -v
msection lvm_lvs lvs -v
msection lvm_pvdisplay pvdisplay -m
msection lvm_vgdisplay vgdisplay -v
msection lvm_lvdisplay lvdisplay -am

msection nr_requests getfilesfromcommand find /sys -name nr_requests
msection read_ahead_kb getfilesfromcommand find /sys -name read_ahead_kb
msection scheduler getfilesfromcommand find /sys -name scheduler
msection rotational getfilesfromcommand find /sys -name rotational

# Network info
msection ifconfig ifconfig -a
msection route route -n
msection iptables iptables -L -v -n
msection iptables_nat iptables -t nat -L -v -n
msection ip_link ip link
msection ip_addr ip addr
msection ip_route ip route
msection ip_rule ip rule
msection hosts getfiles /etc/hosts
msection host.conf getfiles /etc/host.conf
msection resolv getfiles /etc/resolv.conf
msection nsswitch getfiles /etc/nsswitch.conf
msection networks getfiles /etc/networks
msection rpcinfo rpcinfo -p
msection netstat netstat -anpoe

# Network time info
msection ntpd_configuration chkconfig --list ntpd
msection ntpd_status ntpstat
msection ntpd_timeinfo ntpq -p
msection chronyc_tracking chronyc tracking
msection chronyc_sources chronyc sources
msection chronyc_sourcestats chronyc sourcestats

# Hardware info
msection dmesg dmesg
msection lspci lspci -vvv
msection dmidecode dmidecode --type memory
msection sensors sensors
msection mcelog getfiles /var/log/mcelog

# Process/kernel info
msection procinfo getfiles /proc/mounts /proc/self/mountinfo /proc/cpuinfo /proc/meminfo /proc/zoneinfo /proc/swaps /proc/modules /proc/vmstat /proc/loadavg /proc/cgroups
msection transparent_hugepage getfilesfromcommand find /sys/kernel/mm/{redhat_,}transparent_hugepage -type f
msection ps ps -eLFww

# Dynamic/monitoring info
msection top <<EOF
COLUMNS=512
export COLUMNS
top -b -d 1 -n 30 -c | sed -e 's/ *$//g'
EOF
msection top_threads <<EOF
COLUMNS=512
export COLUMNS
top -b -d 1 -n 30 -c -H | sed -e 's/ *$//g'
EOF
msection iostat iostat -xtm 1 120

# Mongo process info
mongo_pids="`pgrep mongo`"
msection mongo_summary ps -Fww -p $mongo_pids
for pid in $mongo_pids; do
msection proc/$pid <<EOF
lsfiles /proc/$pid/cmdline
msubsection cmdline xargs -n1 -0 < /proc/$pid/cmdline
xargs -n1 -0 < /proc/$pid/cmdline | awk '\$0 == "-f" || \$0 == "--config" { getline; print; }' | getstdinfiles
getfiles /proc/$pid/limits /proc/$pid/mounts /proc/$pid/mountinfo /proc/$pid/smaps /proc/$pid/numa_maps
lsfiles /proc/$pid/fd 
getfiles /proc/$pid/fdinfo/*
getfiles /proc/$pid/cgroup
EOF
done
msection global_mongodb_conf getfiles /etc/mongodb.conf /etc/mongod.conf
msection global_mms_conf getfiles /etc/mongodb-mms/*

#check numa capabilities and alignment
msection numactl <<EOF
which numactl && echo "numactl is INSTALLED" || echo "numactl is NOT installed";
msubsection Hardware numactl --hardware 2> /dev/null;
msubsection Show numactl --show 2> /dev/null;
EOF

# Hardware info with a risk of hanging
msection smartctl <<EOF
smartctl --scan | sed -e "s/#.*$//" | while read i; do smartctl --all \$i; done
EOF
msection scsidevices getfiles /sys/bus/scsi/devices/*/model

cat <<EOF

==============================================================
MongoDB Diagnostic information has been recorded in: $diagfile
Please attach the contents of $diagfile to the Jira ticket${1+ at:
    https://jira.mongodb.org/browse/$1}
==============================================================

EOF

