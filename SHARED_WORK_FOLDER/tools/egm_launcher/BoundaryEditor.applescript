-- Boundary Editor launcher: double-click an .egm in Finder -> opens it in the Boundary Editor web page.
-- Source of truth lives in the repo (tools/egm_launcher/); build with build_and_install.sh.

property serverPort : "5051"
property serverUrl : "http://localhost:5051"
property editorPath : "/editor"
property startScript : (POSIX path of (path to home folder)) & ".local/bin/start_web_servers.sh"
property waitSeconds : 90 -- generous: volume mount + Flask import time
property pollInterval : 1

on serverUp()
	try
		do shell script "/usr/bin/curl -s -o /dev/null --max-time 2 " & (quoted form of serverUrl)
		return true
	on error
		return false
	end try
end serverUp

on ensureServer()
	if my serverUp() then return true
	try
		do shell script "/bin/bash " & (quoted form of startScript) & " >/dev/null 2>&1 &"
	end try
	repeat waitSeconds times
		delay pollInterval
		if my serverUp() then return true
	end repeat
	return false
end ensureServer

on urlEncode(thePath)
	-- percent-encode everything except unreserved characters, via python3 (ships with macOS CLT) or perl fallback
	return do shell script "/usr/bin/perl -MURI::Escape -e 'print uri_escape($ARGV[0])' " & (quoted form of thePath)
end urlEncode

on run
	if not my ensureServer() then
		display alert "Boundary Editor server did not start" message "Nothing answered on " & serverUrl & " after " & waitSeconds & " seconds. See ~/Library/Logs/start_web_servers.log"
		return
	end if
	open location serverUrl & editorPath
end run

on open theFiles
	if not my ensureServer() then
		display alert "Boundary Editor server did not start" message "Nothing answered on " & serverUrl & " after " & waitSeconds & " seconds. See ~/Library/Logs/start_web_servers.log"
		return
	end if
	repeat with f in theFiles
		set p to POSIX path of f
		open location serverUrl & editorPath & "?egm=" & my urlEncode(p)
	end repeat
end open
