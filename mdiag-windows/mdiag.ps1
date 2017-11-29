# ====================================
# mdiag.ps1: MongoDB Diagnostic Report
# ====================================
#
# Copyright MongoDB, Inc, 2014, 2015, 2016, 2017
#
#
# DISCLAIMER
#
# Please note: all tools/ scripts in this repo are released for use "AS IS" without any warranties of any kind, 
# including, but not limited to their installation, use, or performance. We disclaim any and all warranties, either 
# express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
# for a particular purpose. We do not warrant that the technology will meet your requirements, that the operation 
# thereof will be uninterrupted or error-free, or that any errors will be corrected.
#
# Any use of these scripts and tools is at your own risk. There is no guarantee that they have been through thorough 
# testing in a comparable environment and we are not responsible for any damage or data loss incurred with their use.
#
# You are responsible for reviewing and testing any scripts you run thoroughly before use in any non-testing environment.
#
#
# LICENSE
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with 
# the License. You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on 
# an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the 
# specific language governing permissions and limitations under the License.
#

[CmdletBinding()]
Param(
   [String]    $CaseReference,
   [switch]    $DoNotElevate,
   [String[]]  $ProbeList  = @(),
   [int]       $Interval   =   1,
   [int]       $Samples    = 120  
)

# =======
# VERSION
# =======

$script:ScriptVersion = "1.9.2"
$script:RevisionDate  = "2017-11-27"

<#
   .SYNOPSIS

     MongoDB Diagnostic Report script that gathers a wide 
     variety of system and hardware diagnostic information.

   .PARAMETER CaseReference

     MongoDB Technical Support case reference.

   .PARAMETER Interval

      Time in seconds between Performance Monitor counter samples.

   .PARAMETER Samples

      Number of Performance Monitor counter samples to collect.
      
   .EXAMPLE

     Start mdiag interactively.
     
     .\mdiag.ps1

   .EXAMPLE

     Start mdiag by specifying your case reference.
     
     .\mdiag.ps1 00345123
   
   .LINK
     
     https://github.com/mongodb/support-tools/tree/master/mdiag-windows
#>

#======================================================================================================================
function Main
#======================================================================================================================
{
   Setup-Environment
   
   $script:FilesToCompress = @($script:DiagFile)
   
   # Only write to output file once all probes have completed
   $probeOutput = Run-Probes 
   $probeOutput | Out-File -Encoding ASCII $script:DiagFile
   
   Write-Progress "Gathering diagnostic information" -Id 1 -Status "Done" -Completed
   Write-Host "`r`nFinished collecting $script:ProbeCount probes.`r`n"

   try
   {      
      $zipFile = [IO.Path]::Combine([IO.Path]::GetDirectoryName($script:DiagFile), 
         [IO.Path]::GetFileNameWithoutExtension($script:DiagFile) + '.zip')    
         
      Compress-Files $zipFile $script:FilesToCompress
      
      $script:FilesToCompress | % {
         Write-Verbose "Removing $_"
         if ([IO.Path]::GetDirectoryName($_) -eq [IO.Path]::GetTempPath().TrimEnd('\') -or $_ -eq $script:DiagFile)
         {
            Remove-Item -Force $_ -ErrorAction SilentlyContinue
            return
         }

         Write-Verbose "Attempt to delete a file not located in temporary path - $_"         
      }
   }
   catch
   {
      Write-Warning "Unable to compress results file : $($_.Exception.Message)"
      $zipFile = $script:DiagFile
   }
   
   if ($CaseReference)
   {
      Write-Host "Please attach '$zipFile' to MongoDB Technical Support case $CaseReference.`r`n"
   }

   Write-Host "Press any key to continue ..."
   $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") | Out-Null
   Write-Host
}

#======================================================================================================================
# Public API
#======================================================================================================================
# * The functions in this section constitute the public API of mdiag.ps1
# * Use these in the script portion below. Please don't directly call other functions; the
#   interfaces there are not guaranteed to be constant between versions of this script.
#======================================================================================================================

#======================================================================================================================
# Run probe specified in $doc
#======================================================================================================================
# $doc should be a hashtable with the following: 
#
#  @{      name    = "section title";
#          cmd     = "invoke-cmd";
#    (opt) alt     = "alternative-invoke-cmd";
#  }
#======================================================================================================================
function probe( $doc ) 
#======================================================================================================================
{
   if (-not $doc.name -or -not $doc.cmd) 
   {
      throw "assert: malformed section descriptor document, must have 'name' and 'cmd' members at least"
   }

   Write-Verbose "Gathering section [$($doc.name)]"

   # run the probe once
   $cmdobj = Run-Command $doc.cmd
   
   if (-not $cmdobj.ok) 
   {
      if ($doc.alt) 
      {
         # preferred cmd failed and we have a fallback, so try that
         Write-Verbose " | Preference attempt failed, but have a fallback to try..."

         $fbcobj = Run-Command $doc.alt

         if ($fbcobj.ok) 
         {
            Write-Verbose " | ... which succeeded!"
         }

         $fbcobj.fallback_from = @{
            command = $cmdobj.command;
            error = $cmdobj.error;
         }
         
         $cmdobj = $fbcobj
      }
   }

   Emit-Document $doc.name $cmdobj

   Write-Verbose "Finished with section [$($doc.name)]. Closing`r`n"
}

#======================================================================================================================
# Generic internal functions
#======================================================================================================================
# Please don't call these in the script portion of the code. The API here will never freeze.
#======================================================================================================================
function Escape-JSON($String) 
#======================================================================================================================
{
   $String = $String.Replace('\','\\').Replace('"','\"')
   $String.Replace("`n",'\n').Replace("`r",'\r').Replace("`t",'\t').Replace("`b",'\b').Replace("`f",'\f')
}

#======================================================================================================================
# Convert the Name and Value properties to a JSON document
#======================================================================================================================
function _tojson_object($Object)
#======================================================================================================================
{
   if ($Object -eq $null -or $Object.Count -eq 0)
   {
      return 'null'
   }
   
   $result = "{`r`n"
   
   try
   {
      $script:Indent += "`t"
      
      if ($Object -is [Collections.IEnumerable])
      {
         $Object = $Object.GetEnumerator()
      }
         
      $Object | % { 
         $result += "$script:Indent$(_tojson_value $_.Name): $(_tojson_value $_.Value),`r`n" 
      }
   }
   finally
   {
      $script:Indent = $script:Indent.SubString(0,$script:Indent.Length-1)
   }
   
   "$($result.TrimEnd(`",`r`n`"))`r`n$script:Indent}"
}

#======================================================================================================================
# JSON encode object value, not using ConvertTo-JSON due to TSPROJ-476
#======================================================================================================================
function _tojson_value($Object) 
#======================================================================================================================
{
   if ($Object -eq $null)
   {
      return 'null'
   }

   if ($script:Indent.Length -gt 20)
   {
      throw "Exceeded $($script:Indent.Length) levels during recursion"
   }

   if ($Object.GetType().IsArray)
   {
      if (([Array] $Object).Count -eq 0)
      {
         return 'null'
      }
      
      try
      {
         $result = "[`r`n"
         $script:Indent += "`t"

         $Object | % { $result += "$script:Indent$(_tojson_value $_),`r`n" }
         $result = $result.TrimEnd(",`r`n")
      }
      finally
      {
         $script:Indent = $script:Indent.SubString(0,$script:Indent.Length-1)
      }
      return "$result`r`n$script:Indent]"
   }
   
   if ($Object.GetType().IsEnum -or $Object -is [String] -or $Object -is [Char] -or $Object -is [TimeSpan])
   {
      return "`"$(Escape-JSON $Object.ToString())`""
   }

   if ($Object -is [DateTime])
   {
      return "{ `"`$date`": `"$(_iso8601_string $Object)`" }"
   }
   
   if ($Object -is [Boolean])
   {
      return @('false','true')[$Object -eq $true]
   }

   if ($Object -is [Collections.IDictionary] -or $Object -is [Collections.IList] -or
         $Object -is [Collections.DictionaryEntry])
   {
      return _tojson_object $Object
   }

   if ($Object.GetType().IsClass)
   {
      return _tojson_object $Object.PSObject.Properties
   }

   $decimal = New-Object Decimal
   try
   {
      if ([Decimal]::TryParse($Object, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref] $decimal))
      {
         return $decimal
      }
   }
   catch
   {
      Write-Verbose "Unable to determine if '$($Object)' ($($Object.GetType().FullName)) is numeric"
   }
   
   Write-Verbose "Using JSON fallback for '$Object' ($($Object.GetType().FullName))"
   "`"$(Escape-JSON $Object.ToString())`""
}

#======================================================================================================================
# get current (or supplied) DateTime formatted as ISO-8601 localtime (with TZ indicator)
#======================================================================================================================
function _iso8601_string([DateTime] $date)
#======================================================================================================================
{
   # TSPROJ-386 timestamp formats
   # turns out the "-s" format of windows is ISO-8601 with the TZ indicator stripped off (it's in localtime)
   # so... we just need to append the TZ that was used in the conversion thusly:
   if (-not $date) 
   {
      $date = Get-Date
   }
   
   if (-not $script:tzstring) 
   {
      # [System.TimeZoneInfo]::Local.BaseUtcOffset; <- should use this "whenever possible" which is .NET 3.5+
      # using the legacy method instead for maximum compatibility
      $tzo = [TimeZone]::CurrentTimeZone.GetUtcOffset($date)
      $script:tzstring = "{0}{1:00}{2:00}" -f @("+","")[$tzo.Hours -lt 0], $tzo.Hours, $tzo.Minutes
   }
   
   # ISO-8601
   return "{0}.{1:000}{2}" -f (Get-Date -Format s -Date $date), $date.Millisecond, $script:tzstring
}

#======================================================================================================================
# Hashing function used by mongod configuration file redaction
#======================================================================================================================
function Hash-SHA256($StringToHash)
#======================================================================================================================
{
   $hasher = New-Object Security.Cryptography.SHA256Managed
   ($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($StringToHash)) | % { ([byte] $_).ToString('X2') }) -join ''
}

#======================================================================================================================
# Return redacted string representation of mongod configuration file
#======================================================================================================================
function Redact-ConfigFile($FilePath)
#======================================================================================================================
{
   if (-not $FilePath -or -not (Test-Path -ErrorAction SilentlyContinue $FilePath))
   {
      return
   }
   
   $optionsToRedact = @('\bqueryPassword:[\s]*([^\s]*)',
                        '\bqueryUser:[\s]*([^\s]*)[\s]*$',
                        '\bqueryUser:[\s]*(CN=.+?)(?<!\\)\,',
                        '\bservers:[\s]*([^\s]*)')

   Get-Content $FilePath -ErrorAction Stop | % {
      if (-not ($currentLine = $_))
      {
         return ''
      }
      
      $optionsToRedact | ? { $currentLine -match $_ } | % {
         $currentLine = $currentLine.Replace($Matches[1], "<redacted sha256 $(Hash-SHA256 $Matches[1])>")
      }
      
      $currentLine
   } 
}

#======================================================================================================================
# Produces Json document that contains probe results
#======================================================================================================================
function Emit-Document($Section, $CmdObj)
#======================================================================================================================
{
   $CmdObj.ref = $script:CaseReference
   $CmdObj.tag = $script:RunDate
   $CmdObj.section = $section
   $CmdObj.ts = Get-Date
   
   try 
   {
      return _tojson_value $CmdObj
   }
   catch 
   {
      $CmdObj.output = ""
      $CmdObj.error = "output conversion to JSON failed : $($_.Exception.Message)"
      $CmdObj.ok = $false

      # give it another shot without the output, just let it die if it still has an issue
      return _tojson_value $CmdObj
   }
}

#======================================================================================================================
# Wrapper for running the command that makes up a probe
#======================================================================================================================
function Run-Command($CommandString)
#======================================================================================================================
{
   if (-not $CommandString)
   {
      throw (New-Object System.ArgumentNullException("CommandString"))
   }

   # selecting only the first arg in the stream now due to possible mongoimport killers like ' " etc (which come out as \u00XX)
   $result = [Collections.SortedList] @{ command = $CommandString.Split("|")[0].Split("`n")[0].Trim() }
   
   try
   {
      Write-Debug "Running command:`r`n$CommandString"
      $output = Invoke-Command -ScriptBlock ([ScriptBlock]::Create($CommandString))
      Write-Debug "Result:`r`n$($output | Out-String)"

      if ($output -is [String])
      {
         $output = [Array] @($output)
      }

      $result.output = $output
      $result.ok = $true
   }
   catch
   {
      Write-Verbose $_.Exception.Message
      $result.ok = $false
      $result.error = $_.Exception.Message
   }
   
   $result
}

#======================================================================================================================
# Get list of probes and run them
# ---------------------------------------------------------------------------------------------------------------------
# NB: This cmdlet uses -notcontains instead of -notin because we need to support PowerShell v2
#======================================================================================================================
function Run-Probes
#======================================================================================================================
{
   Write-Verbose "Running Probes"
   $script:RunDate = Get-Date

   $sb = New-Object System.Text.StringBuilder
   $sb.Append((_tojson_object $script:Fingerprint)) | Out-Null

   $probes = Get-Probes

   if ($script:ProbeList.Count)
   {
      $probesToSkip = @()
      $probesToRun = @()
      
      $script:ProbeList | % {
         if (($probes | % { $_['name'] }) -notcontains $_.TrimStart('-'))
         {
            Write-Warning "Probe '$($_.TrimStart('-'))' not found"
            return
         }
            
         if ($_.StartsWith('-'))
         {
            $probesToSkip += $_.SubString(1)
         }
         else
         {
            $probesToRun += $_
         }
      }
      
      if ($probesToRun.Count -and $probesToSkip.Count)
      {
         Write-Warning "ProbeList parameter does not accept both probes to run and probes to skip"
         Exit
      }
      
      if ($probesToRun.Count)
      {
         $probes = [Array] ($probes | ? { $probesToRun -contains $_.name })
      }
      else
      {
         $probes = [Array] ($probes | ? { $probesToSkip -notcontains $_.name})
      }
   }

   $script:ProbeCount = $probes.Length
   $probes | % {
      $probesRunCount++
      if ($probes.Length)
      {
         $name = $_.name
         if ($_.name -eq 'performance-counters')
         {
            $name += " (expected duration $($script:Samples * $script:Interval) seconds)"
         }
         Write-Progress "Gathering diagnostic information ($probesRunCount/$script:ProbeCount)" -Id 1 -Status $name -PercentComplete (100 / $script:ProbeCount * $probesRunCount)
      }
      $sb.Append(",`r`n$(probe $_)") | Out-Null
   }
   
   "[$($sb.ToString())]" 
}

#======================================================================================================================
function Compress-Files($ZipFile, [String[]] $Files)
#======================================================================================================================
{
   Set-Content $ZipFile ( [byte[]] @( 80, 75, 5, 6 + (, 0 * 18 ) ) ) -Force -Encoding byte
   
   $zipFolder = (New-Object -Com Shell.Application).NameSpace($ZipFile)

   $Files | % { Resolve-Path $_ -ErrorAction SilentlyContinue | Select -ExpandProperty Path } | % { 
      Write-Verbose "Compressing $_"
      $shortFileName = [IO.Path]::GetFileName($_)
      $zipFolder.CopyHere($_)
      while (-not $zipFolder.Items().Item($shortFileName)) 
      {
         Start-Sleep -m 500
      }
   }
}

#======================================================================================================================
# Extract properties from WMI class
#======================================================================================================================
function Get-WmiClassProperties($WmiClass, $Options)
#======================================================================================================================
{  
   if (-not (Get-WmiObject -Class $WmiClass -List))
   {
      throw "WMI class $WmiClass does not exist"
   }
   
   if (-not ($class = Get-WmiObject $WmiClass -ErrorAction Stop))
   {
      return $null
   }
   
   if ($class -is [Collections.IEnumerable])
   {
      $props = $class.GetEnumerator()
   }
   else
   {
      $props = $class
   }
   
   $results = @()
   $props | % { 
      $result = @{}
      $class = $_
      
      $_ | Get-Member | ? { $_.MemberType -eq 'Property' -and -not $_.Name.StartsWith('__') } | % { 
         $result.Add($_.Name, "$($class.($_.Name))")
      }
      
      $results += $result
   }
   
   if ($Options.OutputArray)
   {
      return ,$results
   }
   
   $results
}

#======================================================================================================================
function Get-RegistryValues($RegPath)
#======================================================================================================================
{
   if (-not (Test-Path $RegPath -ErrorAction SilentlyContinue))
   {
      return
   }
   
   # First we need to check for any values under the supplied key
   if ($regKey = Get-Item $RegPath -ErrorAction SilentlyContinue)
   {
      $outerResult = New-Object Collections.Specialized.OrderedDictionary
      $outerResult.Add("Key", $regKey.PSPath.Split(':')[2])
      $outerResult.Add('LastModified', (Get-RegistryLastWriteTime $RegPath))
      $innerResult = @()
      $regKey | % { 
         $reg = $_
         $reg.Property | % {
            if ($reg.GetValueKind($_) -eq 'String')
            {
               $innerResult += @{ Name = $_; Type = $reg.GetValueKind($_); Data = ([String] $reg.GetValue($_)).TrimEnd("`0") }
            }
            else
            {
               $innerResult += @{ Name = $_; Type = $reg.GetValueKind($_); Data = $reg.GetValue($_) }
            }      
         }
      }
      $outerResult.Add('Values', $innerResult)
      $outerResult
   }
   
   # Then we check for any sub keys and recurse them
   Get-ChildItem $RegPath -Recurse -ErrorAction SilentlyContinue | % {
      $reg = $_
   
      $outerResult = New-Object Collections.Specialized.OrderedDictionary
      $outerResult.Add("Key", $reg.PSPath.Split(':')[2])
      $outerResult.Add('LastModified', (Get-RegistryLastWriteTime $reg.PSPath))
      $innerResult = @()
      
      $reg.Property | % {
         if ($reg.GetValue($_) -is [String])
         {
            $innerResult += @{ Name = $_; Type = $reg.GetValueKind($_); Data = ([String] $reg.GetValue($_)).TrimEnd("`0") }
         }
         else
         {
            $innerResult += @{ Name = $_; Type = $reg.GetValueKind($_); Data = $reg.GetValue($_) }
         }      
      }
      
      $outerResult.Add('Values', $innerResult)
      $outerResult
   }
}

#======================================================================================================================
# Ensure PowerShell environment is initialised, take care of elevation if necessary
#======================================================================================================================
function Setup-Environment
#======================================================================================================================
{  
   if ($PSVersionTable.PSVersion -lt '2.0')
   {
      Write-Warning "This script requires PowerShell 2.0 or greater"
      Exit
   }
   
   $script:Fingerprint = @{
      ref = $script:CaseReference;
      host = $env:COMPUTERNAME;
      tag = [DateTime]::Now;
      version = $script:ScriptVersion;
      section = 'fingerprint'
      script = 'mdiag.ps1';
      revdate = $script:RevisionDate;
      os = 'Windows';
      shell = "PowerShell $($PSVersionTable.PSVersion)";
      output = $null;
      error = $null;
   }

   # check if we are admin
   if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
   {
      Write-Verbose "Script is not run with administrative user"

      # see if we can elevate
      if ($DoNotElevate)
      {
         # user expressly asked to avoid privilege elevation (or the script has already been here)
         Write-Verbose "Instructed not to elevate or we're in a hall of mirrors.. aborting elevation"
         Write-Warning "Not running as administrative user but instructed not to elevate. Some health checks may fail."
      }
      elseif (([int] (Get-WmiObject Win32_OperatingSystem).BuildNumber) -ge 6000) 
      {
         Write-Verbose "Found UAC-enabled system. Attempting to elevate ..."

         # when elevating we need to twiddle the command-line a little to be more robust
         $CommandLine = @('-ExecutionPolicy', 'Unrestricted')
                  
         if ($DebugPreference -eq 'Continue')
         {
            $CommandLine += '-NoExit'
         }
         
         $CommandLine += @('-File', "`"$($script:MyInvocation.MyCommand.Definition)`"")

         # do not attempt elevation again on relaunch, in case some bizarro world DC policy causes Runas to fake us out (because that would cause an infinite loop)
         $CommandLine += '-DoNotElevate'

         $script:PSBoundParameters.Keys | % {
            $CommandLine += "-$_"
            if ($script:PSBoundParameters[$_] -isnot [Management.Automation.SwitchParameter]) 
            {
               $CommandLine += ([string] $script:PSBoundParameters[$_])
            }
         }
         
         try 
         {
            $exePath = "$env:SYSTEMROOT\system32\WindowsPowerShell\v1.0\PowerShell.exe"
            
            Write-Verbose "`$CommandLine: `"$exePath`" $($CommandLine -join ' ')"
            Write-Host "`r`nScript will now attempt to relaunch using elevation.`r`nPlease accept the request and follow progress in the new PowerShell window.`r`n"
            $process = Start-Process -FilePath $exePath -ErrorAction Stop -Verb Runas -ArgumentList $CommandLine -PassThru 
            Exit
         }
         catch 
         {
            Write-Warning "Elevation failed - $($_.Exception.Message)"
            Write-Warning "MDiag will continue without administrative privileges."
         }
      }
      else 
      {
         # Server 2003 ? (it is theoretically possible to install powershell there)
         Write-Verbose "Wow, really?! You got powershell running on a pre-6 kernel.. I salute you sir, good job old chap!"
         Write-Warning "System does not support UAC."
      }
   }
   
   Add-CompiledTypes
   
   $script:DiagFile = Join-Path $([Environment]::GetFolderPath('Personal')) "mdiag-$($env:COMPUTERNAME).json"

   Write-Verbose "`$DiagFile: $DiagFile"

   # get a SFSC ticket number if we don't already have one
   if (-not $script:CaseReference)
   {
      $script:CaseReference = Read-Host 'Please provide a MongoDB Technical Support case reference'
   }
}

#======================================================================================================================
function Add-CompiledTypes
#======================================================================================================================
{
   Add-Type @"
      using Microsoft.Win32;
      using System;
      using System.Text;
      using System.Runtime.InteropServices;

      public class MongoDB_Registry_Helper
      {         
         [DllImport("advapi32.dll", CharSet = CharSet.Auto)]
         public static extern int RegOpenKeyEx(
            IntPtr hKey,
            string subKey,
            int ulOptions,
            int samDesired,
            out UIntPtr hkResult);
   
         [DllImport("advapi32.dll", SetLastError=true, EntryPoint="RegQueryInfoKey")]
         public static extern int RegQueryInfoKey(
            UIntPtr hkey,
            out StringBuilder lpClass,
            ref uint lpcbClass,
            IntPtr lpReserved,
            IntPtr lpcSubKeys,
            IntPtr lpcbMaxSubKeyLen,
            IntPtr lpcbMaxClassLen,
            IntPtr lpcValues,
            IntPtr lpcbMaxValueNameLen,
            IntPtr lpcbMaxValueLen,
            IntPtr lpcbSecurityDescriptor,
            out long lpftLastWriteTime);
            
         const int KEY_QUERY_VALUE = 0x0001;
         
         public static long GetRegistryLastWrite(IntPtr lpRegistryHive, string key)
         {
            UIntPtr hkey = UIntPtr.Zero;
            
            if (RegOpenKeyEx(lpRegistryHive, key, 0, KEY_QUERY_VALUE, out hkey) != 0)
            {
               throw new Exception(string.Format("Unable to open {0}", key));
            }
            
            StringBuilder className = new StringBuilder();
            uint classLength = 0;
            long lastWriteTime;
            
            if (RegQueryInfoKey(hkey, out className, ref classLength, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 
                                    IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, out lastWriteTime) != 0)
            {
               throw new Exception("RegQueryInfoKey failed");
            }
            
            return lastWriteTime;
         }
      }      
"@

   Add-Type @"
      using System;
      using System.Runtime.InteropServices;

      public class MongoDB_FileCache_Utils
      {
         [DllImport("kernel32", SetLastError = true, CharSet = CharSet.Unicode)]
         public static extern bool GetSystemFileCacheSize(
            ref IntPtr lpMinimumFileCacheSize,
            ref IntPtr lpMaximumFileCacheSize,
            ref IntPtr lpFlags
            );

         public static bool GetFileCacheSize(ref IntPtr min, ref IntPtr max, ref IntPtr flags)
         {
            IntPtr lpMinimumFileCacheSize = IntPtr.Zero;
            IntPtr lpMaximumFileCacheSize = IntPtr.Zero;
            IntPtr lpFlags = IntPtr.Zero;

            bool result = GetSystemFileCacheSize(ref lpMinimumFileCacheSize, ref lpMaximumFileCacheSize, ref lpFlags);

            min = lpMinimumFileCacheSize;
            max = lpMaximumFileCacheSize;
            flags = lpFlags;
            
            return result;
         }
      }
"@

   Add-Type @"
      using System;
      using System.Runtime.InteropServices;

      public class MongoDB_CommandLine_Utils
      {
         [DllImport("shell32.dll", SetLastError = true)]
         static extern IntPtr CommandLineToArgvW(
            [MarshalAs(UnmanagedType.LPWStr)] string lpCmdLine, out int pNumArgs);

         public static string[] CommandLineToArgs(string commandLine)
         {
            if (String.IsNullOrEmpty(commandLine))
               return new string[] {};

            int argc;
            IntPtr argv = CommandLineToArgvW(commandLine, out argc);
            if (argv == IntPtr.Zero)
               throw new System.ComponentModel.Win32Exception();

            try
            {
               string[] args = new string[argc];
               for (int i = 0; i < args.Length; i++)
               {
                  IntPtr p = Marshal.ReadIntPtr(argv, i * IntPtr.Size);
                  args[i] = Marshal.PtrToStringUni(p);
               }

               return args;
            }
            finally
            {
               Marshal.FreeHGlobal(argv);
            }
         }
      }
"@
   Add-Type @"
      using System;
      using System.Runtime.InteropServices;
      
      public class MongoDB_Utils_MemoryStatus
      {
         static public MEMORYSTATUSEX GetGlobalMemoryStatusEx()
         {
            MEMORYSTATUSEX msex = new MEMORYSTATUSEX();
            if (GlobalMemoryStatusEx(msex)) 
            {
               return msex;
            }
            throw new Exception(string.Format("Unable to initalize the GlobalMemoryStatusEx API - error {0}", Marshal.GetLastWin32Error()));
         }

         [return: MarshalAs(UnmanagedType.Bool)]
         [DllImport("kernel32.dll", CharSet=CharSet.Auto, SetLastError=true)]
         static extern bool GlobalMemoryStatusEx(
            [In, Out] MEMORYSTATUSEX lpBuffer
         );

         [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)]
         public class MEMORYSTATUSEX
         {
            public uint dwLength;
            public uint MemoryLoad;
            public ulong TotalPhysical;
            public ulong AvailablePhysical;
            public ulong TotalPageFile;
            public ulong AvailablePageFile;
            public ulong TotalVirtual;
            public ulong AvailableVirtual;
            public ulong AvailableExtendedVirtual;

            public MEMORYSTATUSEX()
            {
               this.dwLength = (uint) Marshal.SizeOf(typeof(MEMORYSTATUSEX));
            }
         }
      }
"@

   Add-Type @"
      using System;
      using System.Runtime.InteropServices;

      public class MongoDB_Utils_ProcInfo
      {
         [DllImport("kernel32.dll", SetLastError=true)]
         public static extern bool GetLogicalProcessorInformation(
            IntPtr Buffer,
            ref uint ReturnLength
         );

         [StructLayout(LayoutKind.Sequential)]
         public struct CACHE_DESCRIPTOR
         {
            public byte Level;
            public byte Associativity;
            public ushort LineSize;
            public uint Size;
            public PROCESSOR_CACHE_TYPE Type;
         }

         public enum PROCESSOR_CACHE_TYPE
         {
            Unified = 0,
            Instruction = 1,
            Data = 2,
            Trace = 3,
         }
         
         [StructLayout(LayoutKind.Sequential)]
         public struct SYSTEM_LOGICAL_PROCESSOR_INFORMATION
         {
            public UIntPtr ProcessorMask;
            public LOGICAL_PROCESSOR_RELATIONSHIP Relationship;
            public ProcessorRelationUnion RelationUnion;
         }

         [StructLayout(LayoutKind.Explicit)]
         public struct ProcessorRelationUnion
         {
            [FieldOffset(0)] public CACHE_DESCRIPTOR Cache;
            [FieldOffset(0)] public uint NumaNodeNumber;
            [FieldOffset(0)] public byte ProcessorCoreFlags;
            [FieldOffset(0)] private UInt64 Reserved1;
            [FieldOffset(8)] private UInt64 Reserved2;
         }

         public enum LOGICAL_PROCESSOR_RELATIONSHIP : uint
         {
            RelationProcessorCore    = 0,
            RelationNumaNode         = 1,
            RelationCache            = 2,
            RelationProcessorPackage = 3,
            RelationGroup            = 4,
            RelationAll              = 0xffff
         }
         
         private const int ERROR_INSUFFICIENT_BUFFER = 122;
         
         public static SYSTEM_LOGICAL_PROCESSOR_INFORMATION[] GetLogicalProcessorInformation()
         {
            uint ReturnLength = 0;
            GetLogicalProcessorInformation(IntPtr.Zero, ref ReturnLength);
            if (Marshal.GetLastWin32Error() == ERROR_INSUFFICIENT_BUFFER)
            {
               IntPtr Ptr = Marshal.AllocHGlobal((int)ReturnLength);
               try
               {
                  if (GetLogicalProcessorInformation(Ptr, ref ReturnLength))
                  {
                     int size = Marshal.SizeOf(typeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION));
                     int len = (int)ReturnLength / size;
                     SYSTEM_LOGICAL_PROCESSOR_INFORMATION[] Buffer = new SYSTEM_LOGICAL_PROCESSOR_INFORMATION[len];
                     IntPtr Item = Ptr;
                     for (int i = 0; i < len; i++)
                     {
                        Buffer[i] = (SYSTEM_LOGICAL_PROCESSOR_INFORMATION)Marshal.PtrToStructure(Item, typeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION));
                        Item = (IntPtr)(Item.ToInt64() + (long)size);
                     }
                     return Buffer;
                  }
               }
               finally
               {
                  Marshal.FreeHGlobal(Ptr);
               }
            }
            return null;
         }
         
         public static uint GetNumberOfSetBits(ulong value) 
         {
            uint num = 0;
            while (value > 0)
            {
               if ((value & 1) == 1)
                  num++;
               value >>= 1;
            }
            
            return num;
         }
      }
"@

   Add-Type @'
      using System;
      using System.ComponentModel;
      using System.Runtime.InteropServices;
      using System.Security;
      using System.Security.Principal;
      
      internal sealed class Win32Sec
      {
         [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
         internal static extern uint LsaOpenPolicy(
            LSA_UNICODE_STRING[] SystemName,
            ref LSA_OBJECT_ATTRIBUTES ObjectAttributes,
            int AccessMask,
            out IntPtr PolicyHandle
         );

         [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
         internal static extern uint LsaEnumerateAccountRights(
            IntPtr PolicyHandle,
            IntPtr pSID,
            out IntPtr /*LSA_UNICODE_STRING[]*/ UserRights,
            out ulong CountOfRights
         );

         [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
         internal static extern uint LsaEnumerateAccountsWithUserRight(
            IntPtr PolicyHandle,
            LSA_UNICODE_STRING[] UserRights,
            out IntPtr EnumerationBuffer,
            out ulong CountReturned
         );

         [DllImport("advapi32.dll", SetLastError=false)]
         internal static extern int LsaNtStatusToWinError(int status);

         [DllImport("advapi32.dll", SetLastError=true)]
         internal static extern int LsaClose(IntPtr PolicyHandle);

         [DllImport("advapi32.dll", SetLastError=true)]
         internal static extern int LsaFreeMemory(IntPtr Buffer);
      }
      
      [StructLayout(LayoutKind.Sequential)]
      struct LSA_OBJECT_ATTRIBUTES
      {
         internal int Length;
         internal IntPtr RootDirectory;
         internal IntPtr ObjectName;
         internal int Attributes;
         internal IntPtr SecurityDescriptor;
         internal IntPtr SecurityQualityOfService;
      }

      [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
      internal struct LSA_UNICODE_STRING
      {
         internal ushort Length;
         internal ushort MaximumLength;
         [MarshalAs(UnmanagedType.LPWStr)]
         internal string Buffer;
      }

      [StructLayout(LayoutKind.Sequential)]
      internal struct LSA_ENUMERATION_INFORMATION
      {
         internal IntPtr PSid;
      }
         
      public class MongoDB_LSA_Helper : IDisposable
      {
         enum Access : int
         {
            POLICY_VIEW_LOCAL_INFORMATION = 0x00000001,
            POLICY_LOOKUP_NAMES           = 0x00000800
         }
         
         const uint STATUS_ACCESS_DENIED           = 0xC0000022;
         const uint STATUS_INSUFFICIENT_RESOURCES  = 0xC000009A;
         const uint STATUS_NO_MEMORY               = 0xC0000017;
         const uint STATUS_OBJECT_NAME_NOT_FOUND   = 0xC0000034;
         const uint STATUS_NO_MORE_ENTRIES         = 0x8000001A;

         IntPtr lsaHandle = IntPtr.Zero;

         public MongoDB_LSA_Helper()
         {
            LSA_OBJECT_ATTRIBUTES lsaAttr;
            lsaAttr.RootDirectory = IntPtr.Zero;
            lsaAttr.ObjectName = IntPtr.Zero;
            lsaAttr.Attributes = 0;
            lsaAttr.SecurityDescriptor = IntPtr.Zero;
            lsaAttr.SecurityQualityOfService = IntPtr.Zero;
            lsaAttr.Length = Marshal.SizeOf(typeof(LSA_OBJECT_ATTRIBUTES));
            
            LSA_UNICODE_STRING[] system = null;

            uint ret = Win32Sec.LsaOpenPolicy(system, ref lsaAttr, (int)(Access.POLICY_LOOKUP_NAMES | Access.POLICY_VIEW_LOCAL_INFORMATION), out lsaHandle);
            
            if (ret == 0) 
               return;
            
            if (ret == STATUS_ACCESS_DENIED) 
               throw new UnauthorizedAccessException();
            
            if ((ret == STATUS_INSUFFICIENT_RESOURCES) || (ret == STATUS_NO_MEMORY)) 
               throw new OutOfMemoryException();
            
            throw new Win32Exception(Win32Sec.LsaNtStatusToWinError((int)ret));
         }
         
         public enum Rights
         {
            SeTrustedCredManAccessPrivilege,      // Access Credential Manager as a trusted caller
            SeNetworkLogonRight,                  // Access this computer from the network
            SeTcbPrivilege,                       // Act as part of the operating system
            SeMachineAccountPrivilege,            // Add workstations to domain
            SeIncreaseQuotaPrivilege,             // Adjust memory quotas for a process
            SeInteractiveLogonRight,              // Allow log on locally
            SeRemoteInteractiveLogonRight,        // Allow log on through Remote Desktop Services
            SeBackupPrivilege,                    // Back up files and directories
            SeChangeNotifyPrivilege,              // Bypass traverse checking
            SeSystemtimePrivilege,                // Change the system time
            SeTimeZonePrivilege,                  // Change the time zone
            SeCreatePagefilePrivilege,            // Create a pagefile
            SeCreateTokenPrivilege,               // Create a token object
            SeCreateGlobalPrivilege,              // Create global objects
            SeCreatePermanentPrivilege,           // Create permanent shared objects
            SeCreateSymbolicLinkPrivilege,        // Create symbolic links
            SeDebugPrivilege,                     // Debug programs
            SeDenyNetworkLogonRight,              // Deny access this computer from the network
            SeDenyBatchLogonRight,                // Deny log on as a batch job
            SeDenyServiceLogonRight,              // Deny log on as a service
            SeDenyInteractiveLogonRight,          // Deny log on locally
            SeDenyRemoteInteractiveLogonRight,    // Deny log on through Remote Desktop Services
            SeEnableDelegationPrivilege,          // Enable computer and user accounts to be trusted for delegation
            SeRemoteShutdownPrivilege,            // Force shutdown from a remote system
            SeAuditPrivilege,                     // Generate security audits
            SeImpersonatePrivilege,               // Impersonate a client after authentication
            SeIncreaseWorkingSetPrivilege,        // Increase a process working set
            SeIncreaseBasePriorityPrivilege,      // Increase scheduling priority
            SeLoadDriverPrivilege,                // Load and unload device drivers
            SeLockMemoryPrivilege,                // Lock pages in memory
            SeBatchLogonRight,                    // Log on as a batch job
            SeServiceLogonRight,                  // Log on as a service
            SeSecurityPrivilege,                  // Manage auditing and security log
            SeRelabelPrivilege,                   // Modify an object label
            SeSystemEnvironmentPrivilege,         // Modify firmware environment values
            SeManageVolumePrivilege,              // Perform volume maintenance tasks
            SeProfileSingleProcessPrivilege,      // Profile single process
            SeSystemProfilePrivilege,             // Profile system performance
            SeUnsolicitedInputPrivilege,          // "Read unsolicited input from a terminal device"
            SeUndockPrivilege,                    // Remove computer from docking station
            SeAssignPrimaryTokenPrivilege,        // Replace a process level token
            SeRestorePrivilege,                   // Restore files and directories
            SeShutdownPrivilege,                  // Shut down the system
            SeSyncAgentPrivilege,                 // Synchronize directory service data
            SeTakeOwnershipPrivilege              // Take ownership of files or other objects
         }
    
         internal sealed class Sid : IDisposable
         {
            internal IntPtr pSid = IntPtr.Zero;
            internal SecurityIdentifier sid = null;

            public Sid(string account)
            {
               try 
               { 
                  sid = new SecurityIdentifier(account); 
               }
               catch 
               { 
                  sid = (SecurityIdentifier)(new NTAccount(account)).Translate(typeof(SecurityIdentifier)); 
               }
               
               Byte[] buffer = new Byte[sid.BinaryLength];
               sid.GetBinaryForm(buffer, 0);

               pSid = Marshal.AllocHGlobal(sid.BinaryLength);
               Marshal.Copy(buffer, 0, pSid, sid.BinaryLength);
            }

            public void Dispose()
            {
               if (pSid != IntPtr.Zero)
               {
                  Marshal.FreeHGlobal(pSid);
                  pSid = IntPtr.Zero;
               }
               GC.SuppressFinalize(this);
            }

            ~Sid() 
            { 
               Dispose(); 
            }
         }

         public Rights[] EnumerateAccountPrivileges(string account)
         {
            uint ret = 0;
            ulong count = 0;
            IntPtr privileges = IntPtr.Zero;
            Rights[] rights = null;

            using (Sid sid = new Sid(account))
            {
               ret = Win32Sec.LsaEnumerateAccountRights(lsaHandle, sid.pSid, out privileges, out count);
            }
            
            if (ret == 0)
            {
               rights = new Rights[count];
               for (int i = 0; i < (int)count; i++)
               {
                  LSA_UNICODE_STRING str = (LSA_UNICODE_STRING)Marshal.PtrToStructure(
                     new IntPtr(privileges.ToInt64() + i * Marshal.SizeOf(typeof(LSA_UNICODE_STRING))),
                     typeof(LSA_UNICODE_STRING));
                  
                  rights[i] = (Rights)Enum.Parse(typeof(Rights), str.Buffer);
               }
               Win32Sec.LsaFreeMemory(privileges);
               return rights;
            }
            if (ret == STATUS_OBJECT_NAME_NOT_FOUND) 
               return null;  // No privileges assigned
            
            if (ret == STATUS_ACCESS_DENIED) 
               throw new UnauthorizedAccessException();
            
            if ((ret == STATUS_INSUFFICIENT_RESOURCES) || (ret == STATUS_NO_MEMORY)) 
               throw new OutOfMemoryException();
            
            throw new Win32Exception(Win32Sec.LsaNtStatusToWinError((int)ret));
         }

         public string[] EnumerateAccountsWithUserRight(Rights privilege)
         {
            uint ret = 0;
            ulong count = 0;
            LSA_UNICODE_STRING[] rights = new LSA_UNICODE_STRING[1];
            rights[0] = InitLsaString(privilege.ToString());
            IntPtr buffer = IntPtr.Zero;
            string[] accounts = null;

            ret = Win32Sec.LsaEnumerateAccountsWithUserRight(lsaHandle, rights, out buffer, out count);
            if (ret == 0)
            {
               accounts = new string[count];
               for (int i = 0; i < (int)count; i++)
               {
                  LSA_ENUMERATION_INFORMATION LsaInfo = (LSA_ENUMERATION_INFORMATION)Marshal.PtrToStructure(
                     new IntPtr(buffer.ToInt64() + i * Marshal.SizeOf(typeof(LSA_ENUMERATION_INFORMATION))),
                     typeof(LSA_ENUMERATION_INFORMATION));

                  try 
                  {
                     accounts[i] = (new SecurityIdentifier(LsaInfo.PSid)).Translate(typeof(NTAccount)).ToString();
                  }
                  catch (System.Security.Principal.IdentityNotMappedException) 
                  {
                    accounts[i] = (new SecurityIdentifier(LsaInfo.PSid)).ToString();
                  }
               }
               Win32Sec.LsaFreeMemory(buffer);
               return accounts;
            }
            
            if (ret == STATUS_NO_MORE_ENTRIES) 
               return null;  // No accounts assigned
               
            if (ret == STATUS_ACCESS_DENIED) 
               throw new UnauthorizedAccessException();
            
            if ((ret == STATUS_INSUFFICIENT_RESOURCES) || (ret == STATUS_NO_MEMORY)) 
               throw new OutOfMemoryException();
               
            throw new Win32Exception(Win32Sec.LsaNtStatusToWinError((int)ret));
         }
        
         public void Dispose()
         {
            if (lsaHandle != IntPtr.Zero)
            {
               Win32Sec.LsaClose(lsaHandle);
               lsaHandle = IntPtr.Zero;
            }
            GC.SuppressFinalize(this);
         }

         ~MongoDB_LSA_Helper() 
         { 
            Dispose();
         }
         
         internal static LSA_UNICODE_STRING InitLsaString(string s)
         {
            // Unicode strings max. 32KB
            if (s.Length > 32766) 
               throw new ArgumentException("String too long");
               
            LSA_UNICODE_STRING lus = new LSA_UNICODE_STRING();
            lus.Buffer = s;
            lus.Length = (ushort)(s.Length * sizeof(char));
            lus.MaximumLength = (ushort)(lus.Length + sizeof(char));
            return lus;
         }
      }
'@
   Add-Type @"
      using System;
      using System.Collections.Generic;
      using System.Runtime.InteropServices;
      
      public class MongoDB_Utils_CipherSuites
      {
         [DllImport("Bcrypt.dll", CharSet = CharSet.Unicode, SetLastError = true)]
         static extern uint BCryptEnumContextFunctions(
            uint dwTable, 
            string pszContext, 
            uint dwInterface, 
            ref uint pcbBuffer, 
            ref IntPtr ppBuffer
         );
      
         [DllImport("Bcrypt.dll")]
         static extern void BCryptFreeBuffer(IntPtr pvBuffer);
        
         [StructLayout(LayoutKind.Sequential)]
         public struct CRYPT_CONTEXT_FUNCTIONS
         {
            public uint cFunctions;
            public IntPtr rgpszFunctions;
         }

         public const uint CRYPT_LOCAL = 0x00000001;
         public const uint NCRYPT_SCHANNEL_INTERFACE = 0x00010002;

         public static List<String> EnumerateCiphers()
         {
            uint cbBuffer = 0;
            IntPtr ppBuffer = IntPtr.Zero;
            uint ret = BCryptEnumContextFunctions(
                    CRYPT_LOCAL,
                    "SSL",
                    NCRYPT_SCHANNEL_INTERFACE,
                    ref cbBuffer,
                    ref ppBuffer);
            
            List<String> results = new List<String>();
            if (ret == 0)
            {
               CRYPT_CONTEXT_FUNCTIONS functions = (CRYPT_CONTEXT_FUNCTIONS)Marshal.PtrToStructure(ppBuffer, typeof(CRYPT_CONTEXT_FUNCTIONS));

               IntPtr pStr = functions.rgpszFunctions;
               for (int i = 0; i < functions.cFunctions; i++)
               {
                  results.Add(Marshal.PtrToStringUni(Marshal.ReadIntPtr(pStr)));
                  pStr = new IntPtr(pStr.ToInt64() + IntPtr.Size);
               }
               BCryptFreeBuffer(ppBuffer);
            }
            
            return results;
         }
      }
"@
}

#======================================================================================================================
function Get-RegistryLastWriteTime($RegistryKey)
#======================================================================================================================
{
   if (-not ($key = Get-Item $RegistryKey -ErrorAction SilentlyContinue))
   {
      return
   }
   
   $hive = $key.Name.Split('\',2)[0]
   $subkey = $key.Name.Split('\',2)[1]

   switch ($hive)
   {
      'HKEY_LOCAL_MACHINE'
      {
         $hivePtr = [Microsoft.Win32.RegistryHive]::LocalMachine.value__
      }
      
      default
      {
         throw "Unknown hive $hive"
      }
   }
   
   try
   {
      $timestamp = [MongoDB_Registry_Helper]::GetRegistryLastWrite($hivePtr, $subkey)
      return [DateTime]::FromFileTime($timestamp)
   }
   catch
   {
      throw $_.Exception.Message
   } 
}

#======================================================================================================================
function Collect-PerformanceCounters($Samples = 1, $IntervalSeconds = 60)
#======================================================================================================================
{
   ## NB: If any performance counters are missing run C:\Windows\System32\LODCTR /R
   ##     which will rebuild the perf counters based upon installed .INI files

   $counterList = Get-Counter -ListSet *   
   $counters = @()
   
   ## Virtual Machine counters   
   $counterList | ? { 'Hyper-V Dynamic Memory Integration Service','VM Memory','VM Processor' -contains $_.CounterSetName } | % {
      $counter = $_
      switch ($_.CounterSetType)
      {
         'SingleInstance'
         {
            $counters += $counter.Paths
         }
         'MultiInstance'
         {
            $counters += $counter.PathsWithInstances
         }
         default
         {
            Write-Verbose "Unknown CounterSetType '$_'"
         }
      }
   }
   
   ## Paging File counters - excluding (_total) counters
   $counters += $counterList | ? { $_.CounterSetName -eq 'Paging File' } | Select -ExpandProperty PathsWithInstances | ? { $_ -match '^\\Paging File\([^_][^)]*\)\\' }

   ## IO counters - excluding (_total) counters
   $counters += $counterList | ? { $_.CounterSetName -eq 'PhysicalDisk' } | Select -ExpandProperty PathsWithInstances | ? { $_ -match '^\\PhysicalDisk\([^_][^)]*\)\\' }
   
   ## Memory counters
   $counters += @('\Memory\Available Bytes',
                  '\Memory\Committed Bytes',
                  '\Memory\Commit Limit',
                  '\Memory\Modified Page List Bytes',
                  '\Memory\Free System Page Table Entries',
                  '\Memory\Page Faults/sec',
                  '\Memory\Pages/sec',
                  '\Memory\Page Reads/sec',
                  '\Memory\Page Writes/sec',
                  '\Memory\Pages Input/sec',
                  '\Memory\Pages Output/sec',
                  '\Memory\Cache Faults/sec',
                  '\Memory\Cache Bytes',
                  '\Memory\Cache Bytes Peak',
                  '\Memory\Pool Nonpaged Allocs',
                  '\Memory\Pool Nonpaged Bytes',
                  '\Memory\Pool Paged Allocs',
                  '\Memory\Pool Paged Bytes',
                  '\Memory\Pool Paged Resident Bytes',
                  '\Memory\Transition Faults/sec'
               )
   
   ## CPU time counters
   $counters += @('\Processor(_total)\% Processor Time',
                  '\Processor(_total)\% User Time',
                  '\Processor(_total)\% Privileged Time',
                  '\Processor(_total)\% Interrupt Time',
                  '\Processor(_total)\% DPC Time',
                  '\Processor(_total)\% Idle Time',
                  '\System\Context Switches/sec',
                  '\System\Processor Queue Length',
                  '\System\System Calls/sec'
               )

   ## mongod counters
   $counters += @("\\$($env:COMPUTERNAME)\Process(mongo*)\ID Process",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Page Faults/sec",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Page File Bytes",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Pool Nonpaged Bytes",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Pool Paged Bytes",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Private Bytes",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Virtual Bytes",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Working Set",
                  "\\$($env:COMPUTERNAME)\Process(mongo*)\Working Set - Private"
               )

   Write-Verbose "Collecting the following counters:`r`n - $($counters -join `"`r`n - `")"
   Write-Host -NoNewLine "Collecting $Samples samples of $($counters.Length) performance counters. ETA: $((Get-Date).AddSeconds($Samples * $IntervalSeconds).ToLongTimeString()) "
   $counterData = Get-Counter $counters -MaxSamples $Samples -SampleInterval $IntervalSeconds -ErrorAction SilentlyContinue
   Write-Host -NoNewLine "- Done."
   
   if ($VerbosePreference -eq 'Continue')
   {
      Write-Host
   }
   
   if (Get-Command Export-Counter -ErrorAction SilentlyContinue)
   {
      ## Export PerfMon counters to both binary and csv format
      #  - timeseries.py is able to interpret .csv format
      #  - perfmon.exe is able to interpret .blg format and uses metadata such as counter scale

      try
      {
         $binaryPerformanceLog = [IO.Path]::Combine([IO.Path]::GetTempPath(), "PerfMonCounters-$($env:COMPUTERNAME).blg")
         Write-Verbose "Exporting Performance Counters to $binaryPerformanceLog"
         [Microsoft.PowerShell.Commands.GetCounter.PerformanceCounterSampleSet[]] $counterData | Export-Counter -Force -FileFormat BLG $binaryPerformanceLog -ErrorAction Stop
         $script:FilesToCompress += $binaryPerformanceLog
      }
      catch
      {
         Write-Verbose "Unable to export Performance Counters to $binaryPerformanceLog - $($_.Exception.Message)"
      }

      try
      {
         $csvPerformanceLog = [IO.Path]::Combine([IO.Path]::GetTempPath(), "PerfMonCounters-$($env:COMPUTERNAME).csv")
         Write-Verbose "Exporting Performance Counters to $csvPerformanceLog"
         [Microsoft.PowerShell.Commands.GetCounter.PerformanceCounterSampleSet[]] $counterData | Export-Counter -Force -FileFormat CSV $csvPerformanceLog -ErrorAction Stop
         $script:FilesToCompress += $csvPerformanceLog
      }
      catch
      {
         Write-Verbose "Unable to export Performance Counters to $csvPerformanceLog - $($_.Exception.Message)"
      }
   }
   
   ## WARN: Currently we have to support PowerShell v2 - this explains why some things are done the long way below.
   
   $counters = $counterData | % {
      $_.CounterSamples | % { 
         $obj = New-Object PSObject
         $obj | Add-Member -Name Timestamp -MemberType NoteProperty -Value ([DateTimeOffset](_iso8601_string $_.Timestamp))
         $obj | Add-Member -Name Path -MemberType NoteProperty -Value $_.Path.SubString("\\$($env:COMPUTERNAME)".Length)
         $obj | Add-Member -Name Value -MemberType NoteProperty -Value $_.CookedValue
         $obj
      }
   }

   $data = $counters | Group-Object Path | Sort-Object Name | % {
      $ordered = New-Object Collections.Specialized.OrderedDictionary
      $ordered.Add('Path', $_.Name)

      try
      {
         $result = $_.Group | Measure-Object Value -Minimum -Average -Maximum -ErrorAction Stop
      }
      catch
      {
         Write-Warning "Unable to get statistics for '$($_.Name)'"
      }

      $ordered.Add('Minimum', $result.Minimum)
      $ordered.Add('Maximum', $result.Maximum) 
      $ordered.Add('Average', $result.Average)
      $ordered.Add('Samples', ($_.Group | Sort-Object Timestamp | Select -ExpandProperty Value))
      $ordered
   }

   $minTimestamp = [DateTimeOffset]::MaxValue
   $maxTimestamp = [DateTimeOffset]::MinValue
   $counters | % { 
      if ($_.Timestamp -lt $minTimestamp)
      {
         $minTimestamp = $_.Timestamp
      }
      if ($_.Timestamp -gt $maxTimestamp)
      {
         $maxTimestamp = $_.Timestamp
      }
   }
   
   $ordered = New-Object Collections.Specialized.OrderedDictionary
   $ordered.Add('Start', $minTimestamp.DateTime)
   $ordered.Add('Stop', $maxTimestamp.DateTime)
   $ordered.Add('Samples', $Samples)
   $ordered.Add('Interval', $IntervalSeconds)
   $ordered.Add('SampleTimes', ($counterData | Select -ExpandProperty Timestamp | % { _iso8601_string $_ } | Sort-Object))
   $ordered.Add('Data', $data)
   $ordered
}

#======================================================================================================================
# Wrapper to extract entries from Windows event log
#======================================================================================================================
function Extract-EventLogEntries($FilterXml, $Limit = 20)
#======================================================================================================================
{
   ## Get-WinEvent on PowerShell 2.0 doesn't return a message when culture is not en-US
   
   if ($PSVersionTable.PSVersion -eq '2.0' -and (Get-Culture).Name -ne 'en-US')
   {
      $origCulture = Get-Culture

      try
      {
         [Threading.Thread]::CurrentThread.CurrentCulture = New-Object System.Globalization.CultureInfo 'en-US'
         $events = Get-WinEvent -FilterXml $FilterXml -MaxEvents $Limit -ErrorAction Stop
      }
      catch
      {
         throw $_.Exception.Message
      }
      finally
      {
         [System.Threading.Thread]::CurrentThread.CurrentCulture = $origCulture
      }
   }
   else
   {
      ## This will throw an exception if no events are found
      $events = Get-WinEvent -FilterXml $FilterXml -MaxEvents $Limit -ErrorAction Stop
   }
   
   if (-not $events)
   {
      return
   }
   
   $events | Sort-Object -Descending TimeCreated | `
      Select TimeCreated, ProviderName, Id, LevelDisplayName, Message, ProcessId, ThreadId, @{ Name = 'UserId'; Expression = { $_.UserId.Value } }
}

#======================================================================================================================
# Script portion
#======================================================================================================================
#
#   This is where you define the tests you want to run, using the document structure definition provided:
#
#   probe @{ name = "", cmd = "", alt = "" }
#   
#   name = verbatim content of the "section" value in the output for this probe result
#   cmd = powershell command-line to execute and capture output from
#   alt = alternative to cmd to try if 'cmd' reports any kind of error
#
#======================================================================================================================
function Get-Probes
#======================================================================================================================
{   
   @{ name = "hostname_fqdn";
      cmd = '[Net.Dns]::GetHostByName("localhost").Hostname'
   }

   @{ name = "computersystem";
      cmd = "Get-WmiClassProperties Win32_ComputerSystem"
   }
   
   @{ name = "operatingsystem";
      cmd = "Get-WmiClassProperties Win32_OperatingSystem"
   }
   
   @{ name = "quickfixengineering";
      cmd = "Get-WmiClassProperties Win32_QuickFixEngineering"
   }
   
   @{ name = "reliabilityrecords";
      cmd = "Get-WmiClassProperties Win32_ReliabilityRecords"
   }
   
   @{ name = "is_admin";
      cmd = "([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"
   }
   
   @{ name = "memory-status";
      cmd = "[MongoDB_Utils_MemoryStatus]::GetGlobalMemoryStatusEx() | Select MemoryLoad,TotalPhysical,AvailablePhysical,TotalPageFile,AvailablePageFile,TotalVirtual,AvailableVirtual"
   }
   
   @{ name = "memory-physical";
      cmd = "Get-WmiObject Win32_PhysicalMemory | Select BankLabel,DeviceLocator,FormFactor,Capacity,Speed"
   }

   @{ name = "memory-pagefilesetting";
      cmd = "Get-WmiClassProperties Win32_PageFileSetting"
   }

   @{ name = "memory-pagefileusage";
      cmd = 'Get-WmiClassProperties Win32_PageFileUsage @{ OutputArray = $true }'
   }
   
   @{ name = "bios";
      cmd = "Get-WmiClassProperties Win32_Bios"
   }
   
   @{ name = "kernel-boot";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-Kernel-General' and 'Microsoft-Windows-Kernel-Boot'
         
         if (-not (Get-WinEvent -ListProvider 'Microsoft-Windows-Kernel-Boot' -ErrorAction SilentlyContinue))
         {
            $filterXml = @"
               <QueryList>
                  <Query Id="0" Path="System">
                     <Select Path="System">*[System[Provider[@Name='EventLog'] and (EventID != 6013 and EventID != 6005)]]</Select>
                  </Query>
               </QueryList>
"@
         }
         else
         {
            $filterXml = @"
               <QueryList>
                  <Query Id="0" Path="System">
                     <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-General'] and (EventID=12 or EventID=13)]]</Select>
                  </Query>
                  <Query Id="1" Path="System">
                     <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-Boot']]]</Select>
                  </Query>
               </QueryList>
"@
         }
         
         Extract-EventLogEntries $filterXml
'@
   }
   
   @{ name = "tcpip-eventlog";
      cmd = @'
         # Extract-EventLogEntries for 'Tcpip'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Tcpip'] and (Level=1 or Level=2 or Level=3)]]</Select>
               </Query>
            </QueryList>
"@         
         Extract-EventLogEntries $filterXml
'@
   }
   
   @{ name = "kernel-disk";
      cmd = @'
         # Extract-EventLogEntries for 'disk' and 'Microsoft-Windows-Disk'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='disk']]]</Select>
               </Query>
               <Query Id="1" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Disk']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml
'@
   }
   
   @{ name = "kernel-power";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-Kernel-Power' and 'Microsoft-Windows-Kernel-Processor-Power'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-Power']]]</Select>
               </Query>
               <Query Id="1" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-Processor-Power']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml 50
'@
   }
   
   @{ name = "kernel-filtermanager";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-FilterManager'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-FilterManager']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml
'@
   }
   
   @{ name = "kernel-resource-exhaustion";
      cmd = @'
         # Extract-EventLogEntries for signs of Resource Exhaustion
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Resource-Exhaustion-Detector']]]</Select>
               </Query>
               <Query Id="1" Path="System">
                  <Select Path="System">*[System[Provider[@Name='srv'] and (EventID=2013)]]</Select>
               </Query>
               <Query Id="2" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Application Popup'] and (EventID=26)]]</Select>
               </Query>
               <Query Id="3" Path="Application">
                  <Select Path="System">*[System[Provider[@Name='ESENT'] and (EventID=482)]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml
'@
   }
   
   @{ name = "hardware-cpu";
      cmd = 'Get-WmiClassProperties Win32_Processor @{ OutputArray = $true }'
   }
   
   @{ name = "hardware-logicalprocessors";
      cmd = @'
         # Interop call to GetLogicalProcessorInformation()

         $procCaches = @()

         [MongoDB_Utils_ProcInfo]::GetLogicalProcessorInformation() | % {
            
            $obj = $_
            
            switch ($obj.Relationship) 
            {
               'RelationNumaNode'
               {
                  # Non-NUMA systems report a single record of this type.
                  $numaNodeCount += 1
                  break
               }
               
               'RelationProcessorCore'
               {
                  $processorCoreCount += 1

                  # A hyperthreaded core supplies more than one logical processor.
                  $num = [MongoDB_Utils_ProcInfo]::GetNumberOfSetBits($obj.ProcessorMask)
                  
                  # Write-Host "$($obj.ProcessorMask) = $num"
                  $logicalProcessorCount += $num
                  break
               }
               
               'RelationCache'
               {
                  $procCaches += ($cache = $obj | Select -ExpandProperty RelationUnion | Select -ExpandProperty Cache | `
                                    Select @{ Name = 'ProcessorMask'; Expression = { $obj.ProcessorMask } }, Level, Type, LineSize, Size)
                  break
               }
               
               'RelationProcessorPackage'
               {
                  # Logical processors share a physical package.
                  $processorPackageCount += 1
                  break
               }
               
               default
               {
                  Write-Warning "Unsupported LOGICAL_PROCESSOR_RELATIONSHIP value: $($obj.Relationship)"
                  break
               }
            }
         }

         $results = @{}
         $results.Add("NUMA nodes", $numaNodeCount)
         $results.Add("Physical processor packages", $processorPackageCount)
         $results.Add("Processor cores", $processorCoreCount)
         $results.Add("Logical processors", $logicalProcessorCount)
         $results.Add("Processor caches", $procCaches)
         $results
'@ 
   }

   @{ name = "tasklist";
      cmd = @'
         $processes = Get-WmiObject Win32_Process
         Get-Process | % `
         {
            $processId = $_.Id
            $proc = $processes | ? { $_.ProcessId -eq $processId }
            try
            {
               $owner = $proc.GetOwner()
               $owner = if ($owner.Domain) { "$($owner.Domain)\$($owner.User)" } else { $owner.User } 
               
               $objUser = New-Object System.Security.Principal.NTAccount($owner)
               $sid = $objUser.Translate([Security.Principal.SecurityIdentifier]).Value
            }
            catch
            {
               Write-Verbose "Unable to get owner for process $processId"
            }
            
            Select -InputObject $_ -Property @{ Name = 'Name'; Expr = { if ($_.MainModule.ModuleName) { $_.MainModule.ModuleName } else { $proc.ProcessName } } }, Id, 
               @{ Name = 'ParentProcessId'; Expr = { $proc.ParentProcessId } },
               @{ Name = 'Username'; Expr = { $owner } },
               @{ Name = 'Sid'; Expr = { $sid } },
               Path, Description, Company, Product, FileVersion, ProductVersion, 
               BasePriority, PriorityClass, PriorityBoostEnabled, HandleCount, MinWorkingSet, MaxWorkingSet, 
               @{ Name = 'Modules'; Expr = { $_.Modules.FileName } }, 
               NonpagedSystemMemorySize64, PagedMemorySize64, PeakPagedMemorySize64, PagedSystemMemorySize64, VirtualMemorySize64, PeakVirtualMemorySize64, WorkingSet64, PeakWorkingSet64, PrivateMemorySize64, 
               @{ Name = 'StartTime'; Expr = { [DateTime] $_.StartTime } },
               UserProcessorTime, PrivilegedProcessorTime, TotalProcessorTime,
               @{ Name = 'ThreadCount'; Expr = { $_.Threads.Count } },
               @{ Name = 'Threads'; Expr = { $_.Threads.Id } },
               @{ Name = 'CommandLine'; Expr = { $proc.CommandLine } },
               @{ Name = 'ReadOperationCount'; Expr = { $proc.ReadOperationCount } },
               @{ Name = 'ReadTransferCount'; Expr = { $proc.ReadTransferCount } },
               @{ Name = 'WriteOperationCount'; Expr = { $proc.WriteOperationCount } },
               @{ Name = 'WriteTransferCount'; Expr = { $proc.WriteTransferCount } },
               @{ Name = 'OtherOperationCount'; Expr = { $proc.OtherOperationCount } },
               @{ Name = 'OtherTransferCount'; Expr = { $proc.OtherTransferCount } }
         }
'@
   }
   
   @{ name = "mongo-configuration";
      cmd = @'
         # Collect mongos/mongod configuration 
         $results = @()
         Get-WmiObject Win32_Process -Filter "Name = 'mongod.exe' OR Name = 'mongos.exe'" | % {

            $tempFile = [IO.Path]::GetTempFileName()
            
            try
            {
               Start-Process $_.ExecutablePath '--version' -Wait -NoNewWindow -RedirectStandardOutput $tempFile
               $version = Get-Content $tempFile -ErrorAction SilentlyContinue
            }
            finally
            {
               Remove-Item -Force -ErrorAction SilentlyContinue $tempFile
            }
            
            $configFile = $configFilePath = $null
            
            if ($_.CommandLine)
            {
               $array = [MongoDB_CommandLine_Utils]::CommandLineToArgs($_.CommandLine) | % { $_.Split('=',2) | % { return $_ } }
               for ($i = 0; $i -lt $array.Length; $i++)
               {
                  if ('-f','--config' -contains $array[$i] -and $i+1 -le $array.Length-1)
                  {
                     $configFilePath = $array[$i+1]
                     if (-not ([IO.Path]::IsPathRooted($configFilePath)))
                     {
                        $configFilePath = [IO.Path]::Combine(([IO.Path]::GetDirectoryName($_.ExecutablePath)), ([IO.Path]::GetFileName($configFilePath)))
                     }
                  }
               }
            }
            
            if ($configFilePath)
            {
               Write-Verbose "Discovered configuration file $configFilePath"
               $configFile = Redact-ConfigFile $configFilePath
            }
            
            $results += @{ ConfigurationFilePath = $configFilePath;
                           ProcessId = $_.ProcessId;
                           ExecutablePath = $_.ExecutablePath;
                           Version = $version;
                           ConfigFile = $configFile; }
         }
         ,$results
'@
   }
   
   @{ name = "mongod-dir-listing";
      cmd = @'      
         Get-WmiObject Win32_Process -Filter "Name = 'mongod.exe'" | % {
         
            if (-not $_.CommandLine)
            {
               return   @{ DbFilePath = $null;
                           ProcessId = $_.ProcessId;
                           ExecutablePath = $_.ExecutablePath;
                           DirectoryListing = $null }
            }
            
            $array = [MongoDB_CommandLine_Utils]::CommandLineToArgs($_.CommandLine) | % { $_.Split('=',2) | % { return $_ } }
            
            $dbPath = $null
            
            for ($i = 0; $i -lt $array.Length; $i++)
            {
               if ('--dbpath' -contains $array[$i] -and $i+1 -le $array.Length-1)
               {
                  $dbPath = $array[$i+1]
                  continue
               }
               
               if (-not $dbPath)
               {
                  if ('-f','--config' -contains $array[$i] -and $i+1 -le $array.Length-1)
                  {
                     $path = $array[$i+1]
                     if (-not ([IO.Path]::IsPathRooted($path)))
                     {
                        $path = [IO.Path]::Combine(([IO.Path]::GetDirectoryName($_.ExecutablePath)), ([IO.Path]::GetFileName($path)))
                     }

                     Write-Verbose "Reading mongod configuration file $path"
                     
                     Get-Content $path -ErrorAction Stop | % `
                     {
                        if ($_.StartsWith('dbpath=', [StringComparison]::InvariantCultureIgnoreCase))
                        {
                           $dbPath = $_.SubString(7).Trim()
                        }
                        
                        if ($_.StartsWith('storage:'))
                        {
                           $inStorage = $true
                        }
                        elseif ($inStorage -and $_.TrimStart().StartsWith('dbPath'))
                        {
                           $dbPath = $_.Replace('dbPath:','').Trim()
                        }
                        elseif ($inStorage -and -not $_.StartsWith(' '))
                        {
                           $inStorage = $false
                        }
                     }
                  }
               }
            }
            
            if (-not $dbPath)
            {
               return   @{ DbFilePath = $null;
                           ProcessId = $_.ProcessId;
                           ExecutablePath = $_.ExecutablePath;
                           DirectoryListing = $null }
            }

            Write-Verbose "Discovered dbPath $dbPath"
            
            $dirListing = Get-ChildItem -Force -Recurse $dbPath | % {
               $ordered = New-Object Collections.Specialized.OrderedDictionary
               $ordered.Add('FullName', $_.FullName);
               if ($_.Attributes -notcontains 'Directory')
               {
                  $ordered.Add('Length', $_.Length);
               }
               $ordered.Add('Attributes', $_.Attributes);
               $ordered.Add('CreationTime', [DateTime] $_.CreationTime);
               $ordered.Add('LastWriteTime', [DateTime] $_.LastWriteTime);
               $ordered
            }

            @{ DbFilePath = $dbPath;
               ProcessId = $_.ProcessId
               ExecutablePath = $_.ExecutablePath;
               DirectoryListing = $dirListing
            }
         }
'@
   }
   
   @{ name = "network-adapter";
      cmd = "Get-NetAdapter | Select ifIndex,ifAlias,ifDesc,ifName,DriverVersion,MacAddress,Status,LinkSpeed,MediaType,MediaConnectionState,DriverInformation,DriverFileName,NdisVersion,DeviceName,DriverName,DriverVersionString,MtuSize";
      alt = "netsh wlan show interfaces";
   }
   
   @{ name = "network-interface";
      cmd = "Get-NetIPAddress | Select ifIndex,PrefixOrigin,SuffixOrigin,Type,AddressFamily,AddressState,Name,ProtocolIFType,IPv4Address,IPv6Address,IPVersionSupport,PrefixLength,SubnetMask,InterfaceAlias,PreferredLifetime,SkipAsSource,ValidLifetime";
      alt = "ipconfig /all";
   }
   
   @{ name = "network-route";
      cmd = "Get-NetRoute | Select DestinationPrefix,InterfaceAlias,InterfaceIndex,RouteMetric,TypeOfRoute";
      alt = "route print";
   }
   
   @{ name = "network-tcpv4-dynamicports";
      cmd = "netsh int ipv4 show dynamicport tcp";
   }

   @{ name = "network-tcpv6-dynamicports";
      cmd = "netsh int ipv6 show dynamicport tcp";
   }
   
   @{ name = "network-dns-cache";
      cmd = "Get-DnsClientCache | Get-Unique | Select Entry,Name,Data,DataLength,Section,Status,TimeToLive,Type";
      alt = "ipconfig /displaydns"
   }
   
   @{ name = "network-dns-names";
      cmd = @'
         $FQDN = [Net.Dns]::GetHostByName('localhost').Hostname
         @{ Host = $FQDN; Entries = ([Net.Dns]::GetHostByName($FQDN) | Select -ExpandProperty AddressList | Select -ExpandProperty IPAddressToString | Sort-Object) }

         if ($ipAddresses = [Net.Dns]::GetHostByName($FQDN) | Select -ExpandProperty AddressList | Select -ExpandProperty IPAddressToString | Sort-Object)
         {
            $ipAddresses | % { @{ Host = $_; Entries = ([Net.Dns]::GetHostByAddress($_) | Select -ExpandProperty Hostname) } }
         }
'@
   }

   @{ name = "network-tcp-active";
      cmd = @'
         netstat -ano -p TCP | Select -Skip 4 | % {
            $row = $_.Split(' ', [StringSplitOptions]::RemoveEmptyEntries) 
            if ($row.Count -ne 5)
            {
               Write-Verbose 'Unexpected line in netstat output'
               return
            }
            
            $result = New-Object Collections.Specialized.OrderedDictionary
            $result.Add('Proto', $row[0])
            $result.Add('Local Address', $row[1])
            $result.Add('Foreign Address', $row[2])
            $result.Add('State', $row[3])
            $result.Add('PID', $row[4])
            $result
         }
'@
   }

   @{ name = "services";
      cmd = "Get-WmiClassProperties Win32_Service";
   }

   @{ name = "account-privileges"
      cmd = @'
         # Interop call to LsaEnumerateAccountsWithUserRight()
         
         $lsa = New-Object MongoDB_LSA_Helper
         $results = @{}
         
         [Enum]::GetValues([MongoDB_LSA_Helper+Rights]) | % {
            $priv = $_.ToString()
            try
            {
               $results.Add($priv, $lsa.EnumerateAccountsWithUserRight($priv))
            }
            catch
            {
               Write-Verbose "Could not enumerate privilege $priv"
            }
         }
         
         $results
'@
   }
   
   @{ name = "firewall";
      cmd = "Get-NetFirewallRule | Where-Object {`$_.DisplayName -like '*mongo*'} | Select Name,DisplayName,Enabled,@{Name='Profile';Expression={`$_.Profile.ToString()}},@{Name='Direction';Expression={`$_.Direction.ToString()}},@{Name='Action';Expression={`$_.Action.ToString()}},@{Name='PolicyStoreSourceType';Expression={`$_.PolicyStoreSourceType.ToString()}}";
   }

   @{ name = "storage-filecachesize";
      cmd = @'
         # Interop call to GetSystemFileCacheSize()

         $min = $max = $flags = 0

         if ([MongoDB_FileCache_Utils]::GetFileCacheSize([ref] $min, [ref] $max, [ref] $flags))
         {
            @{ min = $min; max = $max; flags = $flags }
         }
'@ }

   @{ name = "storage-fsutil";
      cmd = "fsutil behavior query DisableLastAccess; fsutil behavior query EncryptPagingFile"
   }
   
   @{ name = "storage-disk";
      cmd = 'Get-WmiClassProperties Win32_DiskDrive @{ OutputArray = $true }'
   }
   
   @{ name = "storage-partition";
      cmd = 'Get-WmiClassProperties Win32_DiskPartition @{ OutputArray = $true }'
   }
   
   @{ name = "storage-volume";
      cmd = 'Get-WmiClassProperties Win32_Volume @{ OutputArray = $true }'
   }
   
   @{ name = "storage-logicaldisk";
      cmd = 'Get-WmiClassProperties Win32_LogicalDisk @{ OutputArray = $true }'
   }
   
   @{ name = "storage-logicaldisktopartition";
      cmd = @'
         # Get Win32_DiskDrive to Win32_DiskPartition mapping
         $results = @()
         Get-WmiObject Win32_DiskDrive | % {
            $devId = $_.DeviceId
            $model = $_.Model
           
            Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskDrive.DeviceID=`"$($devId.Replace('\','\\'))`"} WHERE AssocClass = Win32_DiskDriveToDiskPartition" | % {
               $partition = $_
               $driveLetter = Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskPartition.DeviceID=`"$($partition.DeviceID)`"} WHERE AssocClass = Win32_LogicalDiskToPartition"  | Select -ExpandProperty DeviceID
            }
            
            $results += @{ DeviceId = $devId;
                           Partition = $partition.Name;
                           DriveLetter = $driveLetter }
         }

         ,$results
'@ }
   
   @{ name = "storage-ntfs.sys-version";
      cmd = "(Get-Item $env:SYSTEMROOT\system32\drivers\ntfs.sys -ErrorAction Stop).VersionInfo";
   }
   
   @{ name = "environment";
      cmd = "Get-Childitem env: | ForEach-Object {`$j=@{}} {`$j.Add(`$_.Name,`$_.Value)} {`$j}";
   }

   @{ name = "drivers";
      cmd = "Get-WmiObject Win32_SystemDriver | Select Name, Description, PathName, ServiceType, StartMode, Status"
   }

   @{ name = "time-change";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-Kernel-General' and 'Microsoft-Windows-Time-Service'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-General'] and (EventID=1)]]</Select>
               </Query>
               <Query Id="1" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Time-Service']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml 20
'@
   }

   @{ name = "kerberos-parameters";
      cmd = 'Get-RegistryValues HKLM:\SYSTEM\CurrentControlSet\Control\Lsa\Kerberos\Parameters'
   }
   
   @{ name = "kerberos-spn-registrations";
      cmd = @'
         $accounts = @("$($env:COMPUTERNAME)$")
         
         $accounts += Get-WmiObject Win32_Service | ? { $_.PathName -and ($_.PathName.Contains('\mongod.exe') -or $_.PathName.Contains('\mongos.exe')) } | `
            Select -ExpandProperty StartName | Sort-Object -Unique | ? { $_ -and -not $_.StartsWith('NT AUTHORITY\') -and $_ -ne 'LocalSystem' }

         $accounts | % {
            $searcher = New-Object System.DirectoryServices.DirectorySearcher
            $searcher.SearchRoot = New-Object DirectoryServices.DirectoryEntry
            $searcher.SearchScope = 'Subtree'
            if ($_.Contains('@'))
            {
               $searcher.Filter = "(userPrincipalName=$_)"
            }
            else
            {
               $searcher.Filter = "(samAccountName=$_)"
            }
            'userprincipalname','distinguishedname','serviceprincipalname','samaccountname','dnshostname','cn' | % { 
               $searcher.PropertiesToLoad.Add($_) | Out-Null
            }

            $ordered = New-Object Collections.Specialized.OrderedDictionary
            $ordered.Add('requestedAccount', $_)

            try
            {
               if ($result = $searcher.FindOne())
               {
                  $result.Properties.PropertyNames | ? { $_ -ne 'adspath' } | % {
                     if ($result.Properties[$_].Count -eq 1)
                     {
                        $ordered.Add($_, $result.Properties[$_][0])
                     }
                     else
                     {
                        $ordered.Add($_, $result.Properties[$_])
                     }
                  }
               }
            }
            catch
            {
               Write-Verbose $_.Exception.Message
               $ordered.Add('error', $_.Exception.Message)
            }
            
            $ordered
         }
'@
   }
   
   @{ name = "kerberos-binding-cache";
      cmd = @'
         $bindings = klist.exe query_bind
         $line = 0 
         $bindings | % {
            if ($_ -match "^#\d") 
            { 
               $binding = New-Object PSObject 
               $binding | Add-Member -MemberType NoteProperty -Name "Index" -Value $bindings[$line].Split('>')[0].Replace('#','')
               $binding | Add-Member -MemberType NoteProperty -Name "RealmName" -Value $bindings[$line].Split('>')[1].Split(':',2)[1].Trim()
               $binding | Add-Member -MemberType NoteProperty -Name "KDC Address" -Value $bindings[$line+1].Split(':',2)[1].Trim()
               $binding | Add-Member -MemberType NoteProperty -Name "KDC Name" -Value $bindings[$line+2].Split(':',2)[1].Trim()
               $binding | Add-Member -MemberType NoteProperty -Name "Flags" -Value $bindings[$line+3].Split(':',2)[1].Trim()
               $binding | Add-Member -MemberType NoteProperty -Name "DC Flags" -Value $bindings[$line+4].Split(':',2)[1].Trim()
               $binding | Add-Member -MemberType NoteProperty -Name "Cache Flags" -Value $bindings[$line+5].Split(':',2)[1].Trim()
               $binding 
            }
            $line++
         }
'@
   }

   @{ name = "kerberos-sessions";
      cmd = @'
         $klistSessions = klist.exe sessions
         $sessioninfo = @{}
         $klistSessions | % {
            if ($_ -match '^\[\d+\] Session \d+ 0:(0x[0-9a-f]+) (.+) ([^:]+):([^\s]+)') 
            { 
               $session = New-Object PSObject 
               $session | Add-Member -MemberType NoteProperty -Name 'LoginId' -Value $Matches[1]
               $session | Add-Member -MemberType NoteProperty -Name 'Identity' -Value $Matches[2] 
               $session | Add-Member -MemberType NoteProperty -Name 'AuthenticationPackage' -Value $Matches[3]          
               $session | Add-Member -MemberType NoteProperty -Name 'LogonType' -Value $Matches[4]
               $sessioninfo.Add($Matches[1], $session)
            }
         }

         Get-WmiObject Win32_LogonSession | % {

            $session = New-Object PSObject
            $session | Add-Member -MemberType NoteProperty -Name 'LogonId' -Value "0x$([Convert]::ToString($_.LogonId, 16))"
            $session | Add-Member -MemberType NoteProperty -Name 'AuthenticationPackage' -Value $_.AuthenticationPackage

            if ($sessionInfo.ContainsKey($session.LogonId))
            { 
               $session | Add-Member -MemberType NoteProperty -Name 'LogonType' -Value $sessionInfo[$session.LogonId].LogonType
               $session | Add-Member -MemberType NoteProperty -Name 'Identity' -Value $sessioninfo[$session.LogonId].Identity
            }
            else
            { 
               $session | Add-Member -MemberType NoteProperty -Name 'LogonType' -Value $_.LogonType
            } 

            $line = 0
            $rawTGT = klist.exe tgt -li $session.LogonId 
            $tgt = New-Object PSObject
            $rawTGT | % {
               if ($_.Trim() -match '^Current LogonId is 0:([x0-9a-f]+)$')
               {
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Current LogonId' -Value $Matches[1]
                  $startLine = $line+1
               }

               ## Microsoft changed the spelling of "Targeted" between releases
               if ($_.Trim() -match '^Targe[t]{1,2}ed LogonId is 0:([x0-9a-f]+)$')
               {
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Targeted LogonId' -Value $Matches[1]
                  $startLine = $line+1
               }
               
               if ($_.StartsWith('Cached TGT:'))
               {
                  $tgt | Add-Member -MemberType NoteProperty -Name 'ServiceName' -Value $rawTGT[$line+2].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'TargetName SPN' -Value $rawTGT[$line+3].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'ClientName' -Value $rawTGT[$line+4].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'DomainName' -Value $rawTGT[$line+5].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'TargetDomainName' -Value $rawTGT[$line+6].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'AltTargetDomainName' -Value $rawTGT[$line+7].Split(':',2)[1].Trim()
                  
                  $ticketFlagsLine = $rawTGT[$line+8].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Ticket Flags' -Value $ticketFlagsLine.SubString(0,10)
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Ticket Flags Data' -Value $ticketFlagsLine.SubString(14).Trim()
                  
                  $sessionKeyLine = $rawTGT[$line+9].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Session Key Type' -Value $sessionKeyLine.Split('-',2)[0].Trim().Split(' ',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Session Key Type Data' -Value $sessionKeyLine.Split('-',2)[1].Trim()

                  $sessionKeyLine = $rawTGT[$line+10].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Session Key Length' -Value $sessionKeyLine.Split('-',2)[0].Trim().Split(' ',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'Session Key Length Data' -Value $sessionKeyLine.Split('-',2)[1].Trim()
                  
                  $dt = $rawTGT[$line+11].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'StartTime' -Value ([DateTime] $dt.SubString(0, $dt.LastIndexOf(' ')))
                  $dt = $rawTGT[$line+12].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'EndTime' -Value ([DateTime] $dt.SubString(0, $dt.LastIndexOf(' ')))
                  $dt = $rawTGT[$line+13].Split(':',2)[1].Trim()
                  $tgt | Add-Member -MemberType NoteProperty -Name 'RenewUntil' -Value ([DateTime] $dt.SubString(0, $dt.LastIndexOf(' ')))
                  $tgt | Add-Member -MemberType NoteProperty -Name 'TimeSkew' -Value $rawTGT[$line+14].Split(':',2)[1].Trim()
               }
               $line++              
            }
            
            if (-not $tgt.ServiceName)
            {
               $tgt | Add-Member -MemberType NoteProperty -Name Error -Value ($rawTGT[$startLine..($rawTGT.Length-1)] | ? { $_ })
            }

            $session | Add-Member -MemberType NoteProperty -Name 'Ticket Granting Ticket' -Value $tgt
            
            $line = 0 
            $tickets = klist.exe tickets -li $session.LogonId
            $sessionTickets = $tickets | % {
               if ($_ -match "^#\d") 
               { 
                  $ticket = New-Object PSObject 
                  $dateTime = New-Object DateTime
                  
                  $ticket | Add-Member -MemberType NoteProperty -Name 'Index' -Value $tickets[$line].Split('>')[0].Replace('#','')
                  $ticket | Add-Member -MemberType NoteProperty -Name 'Client' -Value $tickets[$line].Split('>')[1].Split(':',2)[1].Trim()
                  $ticket | Add-Member -MemberType NoteProperty -Name 'Server' -Value $tickets[$line+1].Split(':',2)[1].Trim()
                  $ticket | Add-Member -MemberType NoteProperty -Name 'KerbTicket Encryption Type' -Value $tickets[$line+2].Split(':',2)[1].Trim()
                  
                  $ticketFlagsLine = $tickets[$line+3].Replace('Ticket Flags','').Trim()
                  $ticket | Add-Member -MemberType NoteProperty -Name 'Ticket Flags' -Value $ticketFlagsLine.Split(' ')[0]
                  $ticket | Add-Member -MemberType NoteProperty -Name 'Ticket Flags Data' -Value $ticketFlagsLine.SubString(14)
                  
                  $dt = $tickets[$line+4].Split(':',2)[1].Replace('(local)','').Trim()
                  if ([DateTime]::TryParseExact($dt, 'M/d/yyyy H:mm:ss', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref] $dateTime))
                  {
                     $ticket | Add-Member -MemberType NoteProperty -Name 'Start Time' -Value $dateTime
                  }
                  else
                  {
                     $ticket | Add-Member -MemberType NoteProperty -Name 'Start Time' -Value $null
                  }
                  
                  $dt = $tickets[$line+5].Split(':',2)[1].Replace('(local)','').Trim()
                  if ([DateTime]::TryParseExact($dt, 'M/d/yyyy H:mm:ss', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref] $dateTime))
                  {
                     $ticket | Add-Member -MemberType NoteProperty -Name 'End Time' -Value $dateTime
                  }
                  else
                  {
                     $ticket | Add-Member -MemberType NoteProperty -Name 'End Time' -Value $null
                  }
                  
                  $dt = $tickets[$line+6].Split(':',2)[1].Replace('(local)','').Trim()
                  if ([DateTime]::TryParseExact($dt, 'M/d/yyyy H:mm:ss', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref] $dateTime))
                  {
                     $ticket | Add-Member -MemberType NoteProperty -Name 'Renew Time' -Value $dateTime
                  }
                  else
                  {
                     $ticket | Add-Member -MemberType NoteProperty -Name 'Renew Time' -Value $null
                  }
                  
                  $ticket | Add-Member -MemberType NoteProperty -Name 'Session Key Type' -Value $tickets[$line+7].Split(':',2)[1].Trim()

                  if ((Get-WmiObject Win32_OperatingSystem).BuildNumber -ge 9200) 
                  { 
                     $ticket | Add-Member -MemberType NoteProperty -Name 'Cache Flags' -Value $tickets[$line+8].Split(':',2)[1].Trim()
                     $ticket | Add-Member -MemberType NoteProperty -Name 'KDC Called' -Value $tickets[$line+9].Split(':',2)[1].Trim()
                  }
                  $ticket 
               }
               $line++ 
            } 
            
            $session | Add-Member -MemberType NoteProperty -Name 'Session Tickets' -Value $sessionTickets
            $session
         }
'@
   }
   
   @{ name = "security-cipher-suites";
      cmd = '[MongoDB_Utils_CipherSuites]::EnumerateCiphers()'
   }
   
   @{ name = "security-providers";
      cmd = 'Get-RegistryValues HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders'
   }

   @{ name = "security-fips-policy";
      cmd = 'Get-RegistryValues HKLM:\SYSTEM\CurrentControlSet\Control\Lsa\FipsAlgorithmPolicy'
   }
   
   @{ name = "tcpip-parameters";
      cmd = 'Get-RegistryValues HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters'
   }

   @{ name = 'mcafee-av-exclusions';
      cmd = @'
         # McAfee Exclusions
         if ([IntPtr]::Size -eq 8)
         {
            ## 64 bit process
            Get-RegistryValues "HKLM:\SOFTWARE\Wow6432Node\McAfee\SystemCore\vscore\On Access Scanner\McShield\Configuration\Default"'
         }
         else
         {
            Get-RegistryValues "HKLM:\SOFTWARE\McAfee\SystemCore\vscore\On Access Scanner\McShield\Configuration\Default"'
         }
         
         Get-RegistryValues "HKLM:\SOFTWARE\McAfee\ManagedServices\VirusScan\Exclude"
'@
   }
   
   @{ name = 'symantec-av-exclusions';
      cmd = @'
         # Symantec Exclusions
         if ([IntPtr]::Size -eq 8)
         {
            ## 64 bit process
            Get-RegistryValues "HKLM:\SOFTWARE\Wow6432Node\Symantec\Symantec Endpoint Protection\AV\Exclusions"'
         }
         else
         {
            Get-RegistryValues "HKLM:\SOFTWARE\Symantec\Symantec Endpoint Protection\AV\Exclusions"'
         }
'@
   }

   @{ name = 'windows-defender';
      cmd = @'
         # Windows Defender Real-Time Protection and Exclusion settings
         Get-RegistryValues "HKLM:\Software\Microsoft\Windows Defender\Real-Time Protection"
         Get-RegistryValues "HKLM:\Software\Microsoft\Windows Defender\Exclusions"
'@
   }
   
   @{ name = 'windows-eventlogs';
      cmd = @'
         Get-WmiObject Win32_NTEventlogFile | ? { 'Application','System' -contains $_.LogfileName } | % { `
            $destFile = [IO.Path]::Combine([IO.Path]::GetTempPath(), "$($env:COMPUTERNAME)_$([IO.Path]::GetFileName($_.Name))")

            Write-Verbose "Exporting $($_.LogfileName) to $destFile"
            Remove-Item -Force $destFile -ErrorAction SilentlyContinue
            $exported = $_.BackupEventlog($destFile)
            
            if ($exported.ReturnValue -eq 0)
            {
               $script:FilesToCompress += $destFile
            }
            
            $_ | Select LogFileName, 
                        Name, 
                        NumberOfRecords, 
                        FileSize, 
                        MaxFileSize, 
                        OverwriteOutDated, 
                        OverwritePolicy, 
                        @{ Name = 'ReturnValue'; Expr = { $exported.ReturnValue } }
         }
'@
   }
   
   ## Present this last within results file
   @{ name = "performance-counters";
      cmd = "Collect-PerformanceCounters $script:Samples $script:Interval"
   }
}

#======================================================================================================================
# Call script entrypoint
#======================================================================================================================
Main
