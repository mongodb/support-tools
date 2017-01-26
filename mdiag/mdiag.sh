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


version="2.0.2"
revdate="2017-01-16"

PATH="$PATH${PATH+:}/usr/sbin:/sbin:/usr/bin:/bin"

_os="`uname -o`"
if test "$_os" != "GNU/Linux"; then
	echo "mdiag.sh: ERROR: Unsupported Operating System: $_os"
	echo "mdiag.sh: Supported Operating Systems are: Linux"
	exit 1
fi

function showversion {
	echo "mdiag.sh: MongoDB System Diagnostic Information Gathering Tool"
	echo "version $version, copyright (c) 2014-2016, MongoDB, Inc."
}

function showhelp {
	echo ""
	showversion
	echo ""
	echo "Usage:"
	echo "    sudo bash mdiag.sh [options] [reference]"
	echo ""
	echo "Parameters:"
	echo "    [reference]      Reference to ticket, e.g. CS-12435"
	echo "    --format <fmt>   Output in given format (txt or json)"
	echo "    --txt, --text    Output in legacy plain text format"
	echo "    --json           Output in JSON format"
	echo "    --answer [ynqd]  At prompts, answer \"yes\", \"no\", \"quit\" or the default"
	echo "    --help, -h       Show this help"
	echo "    --version, -v    Show the mdiag.sh version"
	echo ""
}

function user_error_fatal {
	echo ""
	echo "mdiag.sh: ERROR: $*"
	echo "Run \"bash mdiag.sh --help\" for help."
	echo ""
	exit 1
}

declare -A validoutputformat
validoutputformat[txt]=txt
validoutputformat[text]=txt
validoutputformat[json]=json

outputformat=json
inhibit_new_version_check=n
inhibit_version_update=n

while [ "${1%%-*}" = "" -a "x$1" != "x" ]; do
	case "$1" in
		--txt|--text|--json)
			outputformat="${1#--}"
			;;
		--format)
			shift
			outputformat="$1"
			;;
		--answer)
			shift
			case "$1" in
				[yYnNqQ])
					auto_answer="$1"
					;;
				[dD])
					auto_answer=""  # simulates pressing Enter
					;;
				*)
					user_error_fatal "unknown value for --answer: \"$1\""
					;;
			esac
			;;
		--inhibit-new-version-check)
			inhibit_new_version_check=y
			;;
		--inhibit-version-update)
			inhibit_version_update=y
			;;
		--internal-updated-from)
			shift
			updated_from="$1"
			;;
		--internal-relaunched-from)
			shift
			relaunched_from="$1"
			;;
		--help|-h)
			showhelp
			exit 0
			;;
		--version|-v)
			showversion
			exit 0
			;;
		*)
			user_error_fatal "unknown parameter \"$1\""
			;;
	esac
	shift
done

ref="$1"
host="$(hostname)"
# Deferred to after the definition of _now
#tag="$(_now)"

case "$ref" in
	CS-*|SUPPORT-*|MMSSUPPORT-*)
		ticket_url="https://jira.mongodb.org/browse/$ref"
		;;
esac

# FIXME: put everything into a subdir (using mktemp)
outputbase="${TMPDIR:-/tmp}/mdiag-$host"

echo "========================="
echo "MongoDB Diagnostic Report"
echo "mdiag.sh version $version"
echo "========================="
echo

if [ "$ref" = "" ]; then
	echo "WARNING: No reference has been supplied.  If you have a ticket number or other"
	echo "reference, you should re-run mdiag.sh and pass it on the command line."
	echo "Run \"bash mdiag.sh --help\" for help."
	echo
fi

function read_ynq {
	local msg="$1"
	local default="${2:-y}"
	local choices="("
	if [ "$default" = y ]; then choices+="Y"; else choices+="y"; fi
	choices+="/"
	if [ "$default" = n ]; then choices+="N"; else choices+="n"; fi
	choices+="/"
	if [ "$default" = q ]; then choices+="Q"; else choices+="q"; fi
	choices+=")"
	local prompt="$msg $choices? "
	if [ "${auto_answer+set}" = set ]; then
		REPLY="$auto_answer"
		echo "$prompt$auto_answer (auto-answer)"
	else
		while :; do
			read -r -p "$prompt"
			case "$REPLY" in
				""|[YyNnQq])
					break
					;;
				*)
					echo 'Please enter "y"(es), "n"(o), "q"(uit), or Enter for default '"($default)."
					;;
			esac
		done
	fi
	case "$REPLY" in
		"")
			REPLY="$default"
			;;
		[Qq])
			echo "mdiag.sh: Aborting at user request"
			exit 0
			;;
	esac
}

function clean_download_target {
	rm -f "$download_target"
}

function get_with {
	if ! type -p "$1" > /dev/null; then
		return 1
	fi

	clean_download_target   # remove any old version
	"$@"
	local _rc=$?
	if [ $_rc -ne 0 ]; then
		clean_download_target   # get rid of any partial download
	fi
	return $_rc
}

function get_with_wget {
	get_with wget --quiet --tries 1 --timeout 10 --output-document "$download_target" "$download_url"
}

function get_with_curl {
	get_with curl --silent --retry 0 --connect-timeout 10 --max-time 120 --output "$download_target" "$download_url"
}

# Check for new version
if [ "$inhibit_new_version_check" != y -a "$updated_from" = "" -a "$relaunched_from" = "" ]; then
	download_url='https://raw.githubusercontent.com/mongodb/support-tools/master/mdiag/mdiag.sh'
	# FIXME: put this (and everything) into an $outputbase-based subdir
	download_target="$outputbase-$$-mdiag.sh"
	trap clean_download_target EXIT   # don't leak downloaded script on shell exit
	echo "Checking for a newer version of mdiag.sh..."
	# first try wget, then try curl, then give up
	if ! get_with_wget; then
		if ! get_with_curl; then
			echo "Warning: Unable to check for a newer version."
		fi
	fi
	if [ -s "$download_target" ]; then
		if cmp -s "$0" "$download_target"; then
			echo "No new version available."
		else
			newversion="$(sed -e '/^version="/{s/"$//;s/^.*"//;q}' -e 'd' "$download_target")"
			if [ "$newversion" = "" ]; then
				newversion="(unknown)"
			fi
			echo "NEW VERSION FOUND: $newversion"
			echo
			if [ "$inhibit_version_update" = y ]; then
				echo "Warning: Auto version update $0 not possible (user-inhibited)"
				update_not_possible=y
			elif [ ! -w "$0" ]; then
				echo "Warning: Auto version update $0 not possible (no write permission)"
				update_not_possible=y
			else
				read_ynq "Update $0 to this version"
				case "$REPLY" in
					[Yy]|"")
						echo "Updating $0 to version $newversion..."
						# Using cat like this will preserve ownership, permissions, etc.
						# Important since we might (should) be running as root.
						if cat "$download_target" > "$0"; then
							echo "Launching updated version of $0..."
							echo
							clean_download_target   # trap EXIT doesn't fire on exec
							exec bash "$0" --internal-updated-from "$version" "$@"
						else
							echo "mdiag.sh: ERROR: failed to update $0 to new version..."
							exit 1
						fi
						;;
					[Nn])
						echo "Not updating to $0"
						user_elected_no_update=y
						;;
				esac
			fi
			# If we get here, either user said not to replace $0, or no write permission.
			# Offer to run the new version anyway.
			read_ynq "Use new version of mdiag.sh without updating"
			case "$REPLY" in
				[Yy]|"")
					echo "Running new version without updating $0..."
					echo
					bash "$download_target" --internal-relaunched-from "$version" "$@"
					_rc=$?
					clean_download_target
					exit $_rc
					;;
				[Nn])
					echo "Not using new version $newversion, continuing with existing version $version..."
					user_elected_not_to_run_newversion=y
					;;
			esac
		fi
	fi
	echo
fi


if [ "${validoutputformat["$outputformat"]:+set}" = "set" ]; then
	outputformat="${validoutputformat["$outputformat"]}"
else
	user_error_fatal "unsupported output format \"$outputformat\""
fi

numoutputs=0

# FIXME: use mktemp if possible
mainoutput="$outputbase-$$.$outputformat"
finaloutput="$outputbase.$outputformat"

exec 3>&1


###############################################################
# Internal internal functions (not used by the actual tests)
###############################################################

function _nextoutput {
	numoutputs=$(($numoutputs + 1))
	outputnum=$numoutputs

	# So I know that using $$ is not as good as mktemp, but it needs to stay in here,
	# even if/when we move to mktemp, so that subshells which output don't use the same
	# output files.
	outfile="$outputbase-$$.$outputnum.out"
	errfile="$outputbase-$$.$outputnum.err"
}

function _now {
	date -Ins | sed -e 's/,\([0-9]\{3\}\)[0-9]\{6\}/.\1/'
}

tag="$(_now)"

function _graboutput {
	exec >> "$outfile" 2>> "$errfile"
}

function _ungraboutput {
	exec 1>&3 2>&4
}

_lf="$(echo -ne '\r')"

function _json_strings_arrayify {
	local a=("$@")
	a=("${a[@]//\\/\\\\}") # this fixes vim syntax highlighting -> "
	a=("${a[@]//\"/\\\"}")
	a=("${a[@]//	/\\t}")
	a=("${a[@]//$_lf/\\r}")
	a=("${a[@]/#/\"}")
	a=("${a[@]/%/\",}")
	a[$(( ${#a[@]} - 1 ))]="${a[$(( ${#a[@]} - 1 ))]%,}"
	echo -n "[ ${a[@]} ]"
}

function _json_stringify {
	local s="$*"
	s="${s//\\/\\\\}" # this fixes vim syntax highlighting -> "
	s="${s//\"/\\\"}"
	s="${s//	/\\t}"
	s="${s//$_lf/\\r}"
	echo "\"$s\""
}

function _json_dateify {
	echo "{ \"\$date\" : $(_json_stringify "$1") }"
}

function _json_lines_arrayify {
	# Outputs an unbalanced closing square bracket - make sure there has been an opening square bracket.
	# On empty input, outputs nothing at all (including no closing square bracket).
	sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' -e 's/\r/\\r/g' -e 's/^/    "/' -e 's/$/"/' -e '$s/$/ ]/'
}

function _jsonify {
	local t="$1"
	shift
	local val
	case "$t" in
		string)
			val="$(_json_stringify "$*")"
			;;
		date)
			val="$(_json_dateify "$*")"
			;;
		null)
			val="null"
			;;
		number)
			case "$1" in
				*[^0-9.+-]*)
					# FIXME: check properly
					val="$(_json_stringify "$1")"
					;;
				"")
					val="null"
					;;
				*)
					val="$1"
					;;
			esac
			;;
		boolean)
			# FIXME: check it's valid
			val="$1"
			;;
		strings_array)
			val="$(_json_strings_arrayify "$@")"
			;;
		file_lines_array)
			if [ -s "$1" ]; then
				val="$(echo "[" ; _json_lines_arrayify < "$1")"
			else
				val="null"
			fi
			# feels risky to have this here...
			rm -f "$1"
			;;
		*)
			val="$*"
			;;
	esac
	echo "$val"
}

function _reset_vars {
	unset ts_started ts_ended ts command rc types fields values outputnum output_fieldname
	declare -a types fields values
}
_reset_vars

function _emit_txt {
	echo ""
	echo ""
	echo "=========== start section $section ==========="
	if [ "$subsection" ]; then
		echo "--> start subsection $subsection <--"
	fi
	if [ "$ts" ]; then
		echo "Date: $ts"
	fi
	if [ "$ts_started" ]; then
		echo "Started: $ts_started"
	fi
	if [ "$ts_ended" ]; then
		echo "Ended: $ts_ended"
	fi
	if [ "${#command[@]}" -gt 0 ]; then
		echo "Command: $(_jsonify strings_array "${command[@]}")"
	fi
	if [ "$rc" ]; then
		echo "RC: $rc"
	fi
	if [ "${#fields[@]}" -gt 0 ]; then
		local i val
		echo "Extra info:"
		for i in "${!fields[@]}"; do
			echo "    ${fields[$i]}: ${values[$i]}"
		done
	fi
	if [ -e "$errfile" ]; then
		echo "Stderr output:"
		cat "$errfile"
		rm -f "$errfile"
	fi
	if [ -e "$outfile" ]; then
		echo "Output:"
		grep -Ev '^\+ (_?end ?runcommands( runcommands)?|rc=-?[0-9]+|set \+x)$' "$outfile"
		rm -f "$outfile"
	fi
	if [ "$subsection" ]; then
		echo "--> end subsection $subsection <--"
	fi
	echo "============ end section $section ============"
}

function _output_preamble_txt {
	{
		echo "========================="
		echo "MongoDB Diagnostic Report"
		echo "mdiag.sh version $version"
		echo "========================="
	} >> "$1"
}

function _output_postamble_txt {
	:
}

function _emit_json {
	echo "{"
	{
	echo "\"ref\" : $ref_json"
	echo "\"host\" : $host_json"
	echo "\"tag\" : $tag_json"
	echo "\"version\" : $version_json"
	echo "\"section\" : $(_jsonify string "$section")"
	if [ "$subsection" ]; then
		echo "\"subsection\" : $(_jsonify string "$subsection")"
	fi
	if [ "$ts_started" -o "$ts_ended" ]; then
		echo "\"ts\" : {"
		if [ "$ts_started" ]; then
			echo -n "    \"start\" : $(_jsonify date "$ts_started")"
		fi
		if [ "$ts_started" -a "$ts_ended" ]; then
			echo ""
		fi
		if [ "$ts_ended" ]; then
			echo -n "      \"end\" : $(_jsonify date "$ts_ended")"
		fi
		echo " }"
	elif [ "$ts" ]; then
		echo "\"ts\" : $(_jsonify date "$ts")"
	fi
	if [ "${#command[@]}" -gt 0 ]; then
		echo "\"command\" : $(_jsonify strings_array "${command[@]}")"
	fi
	if [ "$rc" ]; then
		echo "\"rc\" : $(_jsonify number "$rc")"
	fi
	if [ "${#fields[@]}" -gt 0 ]; then
		local i val
		for i in "${!fields[@]}"; do
			echo "$(_jsonify string "${fields[$i]}") : $(_jsonify "${types[$i]}" "${values[$i]}")"
		done
	fi
	echo "\"${output_fieldname:-output}\" : $(_jsonify file_lines_array "$outfile")"
	echo "\"error\" : $(_jsonify file_lines_array "$errfile")"
	} | sed -e 's/^/    /' -e 's/\([^:{[]\)$/\1,/' -e '$s/,$//'
	echo "},"
}

function _output_preamble_json {
	# Static strings that don't change
	ref_json="$(_jsonify string "$ref")"
	host_json="$(_jsonify string "$host")"
	tag_json="$(_jsonify date "$tag")"
	version_json="$(_jsonify string "$version")"

	echo '[' >> "$1"
}

function _output_postamble_json {
	# Change the final comma to "]", to close the array
	sed -e '$s/^},$/}]/' "$1" > "$1.new" && mv -f "$1.new" "$1"
}


function _emit {
	_emit_"$outputformat" >> "$mainoutput"
	# unset all the variables that have been output, except section/subsection/ref/etc
	_reset_vars
}

function _output_preamble {
	# Grab any stray stderr
	_nextoutput
	stray_stderr_outfile="$errfile"
	exec 4>> "$stray_stderr_outfile"
	exec 2>&4

	_output_preamble_"$outputformat" "$mainoutput"
}

function _output_postamble {
	section stray_stderr
	errfile="$stray_stderr_outfile"
	exec 2>&1   # stderr back to console
	exec 4>&-   # close the file so it gets flushed
	_emit
	endsection

	_output_postamble_"$outputformat" "$mainoutput"
}


function _addfield {
	types+=("$1")
	fields+=("$2")
	values+=("$3")
}

function _finish {
	[ -e "$finaloutput" ] && mv -f "$finaloutput" "$finaloutput.out"
	mv -f "$mainoutput" "$finaloutput"
}



###############################################################
# Internal API functions (used by the actual tests)
###############################################################

function section {
	if [ "${section:+set}" = set ]; then
		endsection
	fi
    section="$1"
    shift
    echo -n "Gathering $section info... " 1>&3
    if [ $# -gt 0 ]; then
        "$@"
        endsection
    fi
}

function endsection {
    echo "done" 1>&3
    unset section
}

function subsection {
    subsection="$1"
    shift
    if [ $# -gt 0 ]; then
        "$@"
        endsubsection
    fi
}

function endsubsection {
    unset subsection
}

function runcommands {
	_nextoutput
	_graboutput
	ts_started="$(_now)"
	if [ "$1" != "_notrace" ]; then
		set -x
	fi
}

function endruncommands {
	# Undo redirections
	rc=$?
	set +x
	_ungraboutput
	ts_ended="$(_now)"
	# FIXME: this should be able to be done quicker with sed
	grep -Ev '^\+ (_?end ?runcommands( runcommands)?|rc=-?[0-9]+|set \+x)$' "$errfile" > "$errfile.new" ; mv -f "$errfile.new" "$errfile"
	#_addfield file_lines_array output "$outfile"
	#_addfield file_lines_array error "$errfile"
	_emit
}

function runcommand {
	command=("$@")
	runcommands _notrace
	"$@"
	endruncommands
}

function printeach {
	local i
	for i; do
		echo "$i"
	done
}

function printeach0 {
	xargs -n1 -0
}

function printeach0file {
	local i
	for i; do
		printeach0 < "$i"
	done
}

function fingerprint {
	ts="$(_now)"
	_addfield string "script" "mdiag.sh"
	_addfield string "revdate" "$revdate"
	_addfield string "os" "$_os"
	_addfield string "shell" "$SHELL"
	_addfield string "scriptversion" "$version"
	_emit
}

function getenvvars {
	local i
	for i; do
		ts="$(_now)"
		_addfield string "envvar" "$i"
		if [ "${!i+set}" = set ]; then
			_addfield boolean set true
			_addfield string "value" "${!i}"

			_nextoutput
			_graboutput
			declare -p "$i"
			_ungraboutput
			output_fieldname="declaration"
			#_addfield file_lines_array declaration "$outfile"
			#_addfield file_lines_array error "$errfile"
		else
			_addfield boolean set false
		fi
		subsection '$'"$i" _emit
	done
}

function getfiles {
	local f
	for f; do
		ts="$(_now)"
		_addfield string "filename" "$f"
		if [ -e "$f" ]; then
			_addfield boolean exists true
			_addfield string ls "$(ls -l "$f" 2>&1)"

			declare -lA _stat
			local format
			format+="_stat[mode_oct]='%a' "
			format+="_stat[mode_sym]='%A' "
			format+="_stat[num_blocks]='%b' "
			format+="_stat[block_size]='%B' "
			format+="_stat[context]='%C' "
			format+="_stat[device]='%d' "
			format+="_stat[type]='%F' "
			format+="_stat[gid]='%g' "
			format+="_stat[group]='%G' "
			format+="_stat[links]='%h' "
			format+="_stat[inode]='%i' "
			format+="_stat[mountpoint]='%m' "
			format+="_stat[iohint]='%o' "
			format+="_stat[size]='%s' "
			format+="_stat[major]='%t' "
			format+="_stat[minor]='%T' "
			format+="_stat[uid]='%u' "
			format+="_stat[user]='%U' "
			format+="_stat[time_birth]='%w' "
			format+="_stat[time_birth_epoch]='%W' "
			format+="_stat[time_access]='%x' "
			format+="_stat[time_access_epoch]='%X' "
			format+="_stat[time_mod]='%y' "
			format+="_stat[time_mod_epoch]='%Y' "
			format+="_stat[time_change]='%z' "
			format+="_stat[time_change_epoch]='%Z' "
			eval "$(stat --printf "$format" "$f" 2>/dev/null)"

			local i
			i="mode_oct"          ; _addfield string "$i" "${_stat[$i]}"
			i="mode_sym"          ; _addfield string "$i" "${_stat[$i]}"
			i="num_blocks"        ; _addfield number "$i" "${_stat[$i]}"
			i="block_size"        ; _addfield number "$i" "${_stat[$i]}"
			i="context"           ; _addfield string "$i" "${_stat[$i]}"
			i="device"            ; _addfield number "$i" "${_stat[$i]}"
			i="type"              ; _addfield string "$i" "${_stat[$i]}"
			i="gid"               ; _addfield number "$i" "${_stat[$i]}"
			i="group"             ; _addfield string "$i" "${_stat[$i]}"
			i="links"             ; _addfield number "$i" "${_stat[$i]}"
			i="inode"             ; _addfield number "$i" "${_stat[$i]}"
			i="mountpoint"        ; _addfield string "$i" "${_stat[$i]}"
			i="iohint"            ; _addfield number "$i" "${_stat[$i]}"
			i="size"              ; _addfield number "$i" "${_stat[$i]}"
			i="major"             ; _addfield number "$i" "${_stat[$i]}"
			i="minor"             ; _addfield number "$i" "${_stat[$i]}"
			i="uid"               ; _addfield number "$i" "${_stat[$i]}"
			i="user"              ; _addfield string "$i" "${_stat[$i]}"
			i="time_birth"        ; _addfield string "$i" "${_stat[$i]}"
			i="time_birth_epoch"  ; _addfield number "$i" "${_stat[$i]}"
			i="time_access"       ; _addfield string "$i" "${_stat[$i]}"
			i="time_access_epoch" ; _addfield number "$i" "${_stat[$i]}"
			i="time_mod"          ; _addfield string "$i" "${_stat[$i]}"
			i="time_mod_epoch"    ; _addfield number "$i" "${_stat[$i]}"
			i="time_change"       ; _addfield string "$i" "${_stat[$i]}"
			i="time_change_epoch" ; _addfield number "$i" "${_stat[$i]}"

			_nextoutput
			_graboutput
			cat "$f"
			_ungraboutput
			output_fieldname="content"
			#_addfield file_lines_array content "$outfile"
			#_addfield file_lines_array error "$errfile"
		else
			_addfield boolean exists false
		fi
		subsection "$f" _emit
	done
}

function getstdinfiles {
	local i
	while read i; do
		getfiles "$i"
	done
}

function getfilesfromcommand {
	"$@" | getstdinfiles
}


function lsfiles {
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


##################################################################################


if [ "$ref" ]; then
	echo "Reference: $ref"
	if [ "$ticket_url" ]; then
		echo "Ticket URL: $ticket_url"
	fi
	echo
fi
echo "Please wait while diagnostic information is gathered"
echo "into the $finaloutput file..."
echo
echo "If the display remains stuck for more than 5 minutes,"
echo "please press Control-C."
echo


_output_preamble

shopt -s nullglob


##################################################################################


# Generic/system/distro/boot info
section fingerprint fingerprint
section args runcommand printeach "$@"
section date runcommand date
section hostname runcommand hostname
section hostname_fqdn runcommand hostname -f
section whoami runcommand whoami
section mdiag_upgrade getenvvars inhibit_new_version_check inhibit_version_update updated_from relaunched_from newversion user_elected_no_update update_not_possible user_elected_not_to_run_newversion download_url download_target
section environment getenvvars PATH LD_LIBRARY_PATH LD_PRELOAD PYTHONPATH PYTHONHOME
section distro getfiles /etc/*release /etc/*version
section uname runcommand uname -a
section glibc runcommand lsfiles /lib*/libc.so* /lib/*/libc.so*
section glibc2 runcommand eval "/lib*/libc.so* || /lib/*/libc.so*"
section ld.so.conf getfiles /etc/ld.so.conf /etc/ld.so.conf.d/*
section lsb runcommand lsb_release -a
section rc.local getfiles /etc/rc.local
section sysctl runcommand sysctl -a
section sysctl.conf getfiles /etc/sysctl.conf /etc/sysctl.d/*
section ulimit runcommand ulimit -a
section limits.conf getfiles /etc/security/limits.conf /etc/security/limits.d/*
section selinux runcommand sestatus
section uptime runcommand uptime
section boot runcommand who -b
section runlevel runcommand who -r
section clock_change runcommand who -t
section timezone_config getfiles /etc/timezone /etc/sysconfig/clock
section timedatectl runcommand timedatectl
section localtime runcommand lsfiles /etc/localtime
section localtime_matches runcommand find /usr/share/zoneinfo -type f -exec cmp -s \{\} /etc/localtime \; -print
section clocksource getfiles /sys/devices/system/clocksource/clocksource*/{current,available}_clocksource

section chkconfig_list runcommand chkconfig --list
section initctl_list runcommand initctl list

# Block device/filesystem info
section scsi getfiles /proc/scsi/scsi
section blockdev runcommand blockdev --report
section lsblk runcommand lsblk

section udev_disks
	runcommands
		awk '{ $0 = $4 } /^[sh]d[a-z]+$/' /proc/partitions | xargs -n1 --no-run-if-empty udevadm info --query all --name
	endruncommands
endsection

section fstab getfiles /etc/fstab
section mount runcommand mount
section df-h runcommand df -h
section df-k runcommand df -k

section mdstat getfiles /proc/mdstat
section mdadm_detail_scan runcommand mdadm --detail --scan
section mdadm_detail
	runcommands
		sed -ne 's,^\(md[0-9]\+\) : .*$,/dev/\1,p' < /proc/mdstat | xargs -n1 --no-run-if-empty mdstat --detail
	endruncommands
endsection

section dmsetup runcommand dmsetup ls
section device_mapper runcommand lsfiles -R /dev/mapper /dev/dm-*

section lvm subsection pvs runcommand pvs -v
section lvm subsection vgs runcommand vgs -v
section lvm subsection lvs runcommand lvs -v
section lvm subsection pvdisplay runcommand pvdisplay -m
section lvm subsection vgdisplay runcommand vgdisplay -v
section lvm subsection lvdisplay runcommand lvdisplay -am

section nr_requests getfilesfromcommand find /sys -name nr_requests
section read_ahead_kb getfilesfromcommand find /sys -name read_ahead_kb
section scheduler getfilesfromcommand find /sys -name scheduler
section rotational getfilesfromcommand find /sys -name rotational

# Network info
section ifconfig runcommand ifconfig -a
section route runcommand route -n
section iptables runcommand iptables -L -v -n
section iptables_nat runcommand iptables -t nat -L -v -n
section ip_link runcommand ip link
section ip_addr runcommand ip addr
section ip_route runcommand ip route
section ip_rule runcommand ip rule
section ip_neigh runcommand ip neigh
section hosts getfiles /etc/hosts
section host.conf getfiles /etc/host.conf
section resolv getfiles /etc/resolv.conf
section nsswitch getfiles /etc/nsswitch.conf
section networks getfiles /etc/networks
section rpcinfo runcommand rpcinfo -p
section netstat runcommand netstat -anpoe

# Network time info
section ntp getfiles /etc/ntp.conf
section ntp subsection chkconfig runcommand chkconfig --list ntpd
section ntp subsection status runcommand ntpstat
section ntp subsection peers runcommand ntpq -p
section ntp subsection peers_n runcommand ntpq -pn
section chronyc subsection tracking runcommand chronyc tracking
section chronyc subsection sources runcommand chronyc sources
section chronyc subsection sourcestats runcommand chronyc sourcestats

# Hardware info
section dmesg runcommand dmesg
section lspci runcommand lspci -vvv
section dmidecode runcommand dmidecode --type memory
section sensors runcommand sensors
section mcelog getfiles /var/log/mcelog

# Numa settings
section numactl subsection command runcommand which numactl
section numactl subsection hardware runcommand numactl --hardware
section numactl subsection show runcommand numactl --show

# Process/kernel info
section procinfo getfiles /proc/mounts /proc/self/mountinfo /proc/cpuinfo /proc/meminfo /proc/zoneinfo /proc/swaps /proc/modules /proc/vmstat /proc/loadavg /proc/uptime /proc/cgroups /proc/partitions
section transparent_hugepage getfilesfromcommand find /sys/kernel/mm/{redhat_,}transparent_hugepage -type f
section ps runcommand ps -eLFww

# Dynamic/monitoring info
section top
runcommands
COLUMNS=512 top -b -d 1 -n 30 -c | sed -e 's/ *$//g'
endruncommands
endsection
section top_threads
runcommands
COLUMNS=512 top -b -d 1 -n 30 -c -H | sed -e 's/ *$//g'
endruncommands
endsection
section iostat runcommand iostat -xtm 1 120

# Mongo process info
mongo_pids="`pgrep mongo`"
section mongo_summary runcommand ps -Fww -p $mongo_pids
for pid in $mongo_pids; do
	section proc/$pid
		runcommand lsfiles /proc/$pid/cmdline
		subsection cmdline runcommand printeach0file /proc/$pid/cmdline
		printeach0file /proc/$pid/cmdline | awk '$0 == "-f" || $0 == "--config" { getline; print; }' | getstdinfiles
		getfiles /proc/$pid/limits /proc/$pid/mounts /proc/$pid/mountinfo /proc/$pid/smaps /proc/$pid/numa_maps
		subsection /proc/$pid/fd runcommand lsfiles /proc/$pid/fd
		subsection /proc/$pid/fdinfo runcommand lsfiles /proc/$pid/fdinfo
		getfiles /proc/$pid/cgroup
	endsection
done
section global_mongodb_conf getfiles /etc/mongodb.conf /etc/mongod.conf

# Hardware info with a risk of hanging
section smartctl
	runcommands
		smartctl --scan | sed -e "s/#.*$//" | while read i; do smartctl --all $i; done
	endruncommands
endsection
section scsidevices getfiles /sys/bus/scsi/devices/*/model


##################################################################################


_output_postamble
_finish

cat <<EOF

==============================================================
MongoDB diagnostic information has been recorded in the file:

    $finaloutput

Please upload that file to the ticket${ticket_url:+ at:
    $ticket_url}
==============================================================

EOF

